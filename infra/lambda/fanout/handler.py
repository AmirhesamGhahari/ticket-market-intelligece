import json
import os

import boto3

ecs = boto3.client("ecs")


def lambda_handler(event, context):
    cluster = os.environ["ECS_CLUSTER_ARN"]
    task_family = os.environ["TASK_DEFINITION_FAMILY"]
    subnets = os.environ["SUBNET_IDS"].split(",")
    sg = os.environ["SECURITY_GROUP_ID"]
    event_configs = json.loads(os.environ["EVENT_CONFIGS"])

    # Optional payload overrides — omit all to keep the default scheduled fan-out behaviour.
    # config_name: run only this one config instead of the full event list
    # command:
    #   "from-facebook-legacy"     — legacy raidr-api FB scrape (run-facebook-legacy from-apify)
    #   "classify-facebook-legacy" — legacy FB classify only
    #   "from-facebook-new"        — new futurafree FB scrape + classify (run-facebook-new from-config)
    #   "classify-facebook-new"    — new FB classify only
    #   "from-seatgeek"            — SeatGeek price snapshot
    #   "from-stubhub"             — StubHub price snapshot (run-stubhub from-config)
    # mode:  "initial" | "periodic" (default "periodic")
    # stage: "scrape" | "classify" | "all" (default "all", applies to facebook sources)
    target_config = event.get("config_name")
    command = event.get("command")
    mode = event.get("mode", "periodic")
    stage = event.get("stage", "all")

    def _run_cmd(cmd):
        resp = ecs.run_task(
            cluster=cluster,
            taskDefinition=task_family,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": subnets,
                    "securityGroups": [sg],
                    "assignPublicIp": "ENABLED",
                }
            },
            overrides={
                "containerOverrides": [{"name": "pipeline", "command": cmd}]
            },
        )
        return resp

    results = []

    def _launch(config_name, cmd):
        resp = _run_cmd(cmd)
        task_arns = [t["taskArn"] for t in resp.get("tasks", [])]
        failures = resp.get("failures", [])
        results.append({"config": config_name, "command": cmd, "tasks": task_arns, "failures": failures})
        print(f"Launched {config_name} ({' '.join(cmd)}): tasks={task_arns} failures={failures}")

    configs = [target_config] if target_config else event_configs

    # ── Explicit single-pipeline commands ─────────────────────────────────────

    if command in ("from-apify", "from-facebook-legacy"):
        for cfg in configs:
            _launch(cfg, ["run-facebook-legacy", "from-apify", "--config", cfg, "--mode", mode, "--stage", stage])

    elif command in ("classify", "classify-facebook-legacy"):
        for cfg in configs:
            _launch(cfg, ["run-facebook-legacy", "classify", "--config", cfg])

    elif command == "from-facebook-new":
        for cfg in configs:
            _launch(cfg, ["run-facebook-new", "from-config", "--config", cfg, "--mode", mode, "--stage", stage])

    elif command == "classify-facebook-new":
        for cfg in configs:
            _launch(cfg, ["run-facebook-new", "classify", "--config", cfg])

    elif command == "from-seatgeek":
        for cfg in configs:
            _launch(cfg, ["run-seatgeek", "from-api", "--config", cfg, "--mode", mode])

    elif command == "from-stubhub":
        for cfg in configs:
            _launch(cfg, ["run-stubhub", "from-config", "--config", cfg])

    else:
        # Scheduled full run — fan out all pipelines for all events.
        # Each CLI exits early if its source is disabled in the event config.
        for cfg in configs:
            _launch(cfg, ["run-facebook-legacy", "from-apify", "--config", cfg, "--mode", mode, "--stage", stage])
            _launch(cfg, ["run-facebook-new", "from-config", "--config", cfg, "--mode", mode, "--stage", stage])
            _launch(cfg, ["run-seatgeek", "from-api", "--config", cfg, "--mode", mode])
            _launch(cfg, ["run-stubhub", "from-config", "--config", cfg])

    return {"launched": len(results), "results": results}
