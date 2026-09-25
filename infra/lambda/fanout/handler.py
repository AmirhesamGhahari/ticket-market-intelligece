"""Pipeline task_producer Lambda.

Called once per Step Functions execution (TaskProducer state).

1. Determines morning / evening from current UTC hour.
2. Reads EVENT_CONFIGS env var (list of {name, event_dates} objects set by Terraform).
3. Applies per-source frequency rules to decide which events to run.
4. Batch-reads DynamoDB to get mode (initial | periodic) per event×source.
5. Returns {run, tasks: {facebook_legacy:[...], facebook_new:[...], stubhub:[...]}}.

Frequency rules (based on days until earliest upcoming show date)
─────────────────────────────────────────────────────────────────
FB legacy + FB new
  days_until > 30   → evening run only, even calendar day of month
  15 ≤ days ≤ 30    → evening run, every day
  days_until < 15   → morning + evening

StubHub
  days_until > 30   → evening run only, even calendar day of month
  7 ≤ days ≤ 30     → evening run, every day
  days_until < 7    → morning + evening

Multi-date events
─────────────────
FB: one task per config (frequency based on nearest show date).
StubHub: one task per upcoming show date.

DynamoDB state keys
───────────────────
FB:                    "{config}#{source}"
StubHub single-date:   "{config}#stubhub"
StubHub multi-date:    "{config}#stubhub#{date}"

DynamoDB item schema (pk = state_key):
  mode — "initial" | "periodic"
  (written to "periodic" by the SetModePeriodic SFN state after each success)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import boto3

dynamodb = boto3.resource("dynamodb")


def lambda_handler(event, context):
    return _task_producer(event)


# ── task_producer ──────────────────────────────────────────────────────────────

def _task_producer(event: dict) -> dict:
    now = datetime.now(timezone.utc)

    # Manual override: pass {"run": "morning"} when starting SFN from the console
    run = event.get("run")
    if run not in ("morning", "evening"):
        # 12:00 UTC = 8am ET (morning); 00:00 UTC = 8pm ET (evening)
        run = "morning" if now.hour >= 8 else "evening"

    event_configs = json.loads(os.environ["EVENT_CONFIGS"])

    # qualified_fb: (config_name, source, state_key)
    # qualified_sh: (config_name, state_key, date_str_for_cmd)
    #   date_str_for_cmd is None for single-date events (no --date flag in command)
    qualified_fb: list[tuple[str, str, str]] = []
    qualified_sh: list[tuple[str, str, str | None]] = []

    for cfg in event_configs:
        name        = cfg["name"]
        event_dates = cfg.get("event_dates", [])

        # Filter to upcoming dates only
        upcoming: list[tuple[datetime, str]] = []
        for d in event_dates:
            try:
                dt = datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
                if dt > now:
                    upcoming.append((dt, d))
            except (ValueError, TypeError):
                print(f"[WARN] {name}: bad date {d!r} — skipping")

        if not upcoming:
            print(f"[SKIP] {name}: no upcoming show dates")
            continue

        upcoming.sort()
        earliest_dt, _ = upcoming[0]
        days_until = (earliest_dt - now).days

        # FB: one task per config (frequency based on nearest show date)
        for fb_source in ("facebook_legacy", "facebook_new"):
            if _should_run(fb_source, run, days_until, now):
                state_key = f"{name}#{fb_source}"
                qualified_fb.append((name, fb_source, state_key))
                print(f"[QUEUE] {name}/{fb_source}: {days_until}d, run={run}")
            else:
                print(f"[SKIP]  {name}/{fb_source}: {days_until}d, run={run} — freq gate")

        # StubHub: one task per upcoming show date
        if _should_run("stubhub", run, days_until, now):
            is_multi = len(event_dates) > 1
            for _, date_str in upcoming:
                state_key    = f"{name}#stubhub#{date_str}" if is_multi else f"{name}#stubhub"
                date_for_cmd = date_str if is_multi else None
                qualified_sh.append((name, state_key, date_for_cmd))
                print(f"[QUEUE] {name}/stubhub/{date_str}: {days_until}d, run={run}")
        else:
            print(f"[SKIP]  {name}/stubhub: {days_until}d, run={run} — freq gate")

    # ── Batch-read DynamoDB for mode ──────────────────────────────────────────
    all_state_keys = [sk for _, _, sk in qualified_fb] + [sk for _, sk, _ in qualified_sh]
    states = _batch_get_states(all_state_keys) if all_state_keys else {}

    # ── Build per-source task lists ───────────────────────────────────────────
    tasks: dict[str, list[dict]] = {
        "facebook_legacy": [],
        "facebook_new":    [],
        "stubhub":         [],
    }

    for name, source, state_key in qualified_fb:
        state = states.get(state_key, {})
        mode  = state.get("mode") or "initial"
        tasks[source].append({
            "command":   _build_command(name, source, mode),
            "state_key": state_key,
            "mode":      mode,
        })

    for name, state_key, date_for_cmd in qualified_sh:
        state = states.get(state_key, {})
        mode  = state.get("mode") or "initial"
        tasks["stubhub"].append({
            "command":   _build_command(name, "stubhub", mode, date_str=date_for_cmd),
            "state_key": state_key,
            "mode":      mode,
        })

    counts = {s: len(t) for s, t in tasks.items()}
    print(f"[PLAN] run={run} tasks={counts}")
    return {"run": run, "tasks": tasks}


def _should_run(source: str, run: str, days_until: int, now: datetime) -> bool:
    if source in ("facebook_legacy", "facebook_new"):
        if days_until > 30:
            return run == "evening" and now.day % 2 == 0
        elif days_until >= 15:
            return run == "evening"
        else:
            return True
    elif source == "stubhub":
        if days_until > 30:
            return run == "evening" and now.day % 2 == 0
        elif days_until >= 7:
            return run == "evening"
        else:
            return True
    return False


def _build_command(config_name: str, source: str, mode: str, date_str: str | None = None) -> list[str]:
    if source == "facebook_legacy":
        return ["run-facebook-legacy", "from-apify", "--config", config_name, "--mode", mode, "--stage", "all"]
    if source == "facebook_new":
        return ["run-facebook-new", "from-config", "--config", config_name, "--mode", mode, "--stage", "all"]
    if source == "stubhub":
        cmd = ["run-stubhub", "from-config", "--config", config_name]
        if date_str:
            cmd += ["--date", date_str]
        return cmd
    raise ValueError(f"Unknown source: {source!r}")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _batch_get_states(state_keys: list[str]) -> dict[str, dict]:
    table_name = os.environ["STATE_TABLE_NAME"]
    try:
        response = dynamodb.batch_get_item(
            RequestItems={table_name: {"Keys": [{"pk": k} for k in state_keys]}}
        )
        if response.get("UnprocessedKeys"):
            print(f"[WARN] DynamoDB UnprocessedKeys — some items may default to initial mode")
        return {item["pk"]: item for item in response.get("Responses", {}).get(table_name, [])}
    except Exception as exc:
        print(f"[WARN] batch_get_states failed: {exc} — defaulting all to initial mode")
        return {}
