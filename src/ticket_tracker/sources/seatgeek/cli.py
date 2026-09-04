"""SeatGeek pipeline CLI.

Commands:
    run-seatgeek from-api --config veld_2026
    run-seatgeek from-api --config veld_2026 --mode initial
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import click
import yaml
from loguru import logger
from rich.console import Console
from rich.rule import Rule
from rich.table import Table
from sqlalchemy import text

from ticket_tracker.config import settings
from ticket_tracker.db.engine import SessionLocal
from ticket_tracker.sources.seatgeek.scraper import SeatGeekClient
from ticket_tracker.sources.seatgeek.stage1 import run_snapshot

console = Console()

logger.remove()
logger.add(sys.stderr, format="<level>{level: <8}</level> | {message}", level="INFO")

_CONFIGS_DIR = Path.cwd() / "configs"


def _run_migrations() -> None:
    from alembic import command as alembic_command
    from alembic.config import Config
    cfg = Config("alembic.ini")
    alembic_command.upgrade(cfg, "head")


# ── Config helpers ────────────────────────────────────────────────────────────


def _load_config(config_name: str) -> dict:
    config_path = _CONFIGS_DIR / f"{config_name}.yaml"
    if not config_path.exists():
        raise click.BadParameter(
            f"Config file not found: {config_path}", param_hint="'--config'"
        )
    with open(config_path) as fh:
        return yaml.safe_load(fh)


def _resolve_event(config: dict) -> uuid.UUID:
    with SessionLocal() as session:
        session.execute(
            text("""
                INSERT INTO events (id, event_key, event_name)
                VALUES (:id, :event_key, :event_name)
                ON CONFLICT (event_key) DO NOTHING
            """),
            {
                "id": str(uuid.uuid4()),
                "event_key": config["event_key"],
                "event_name": config["event_name"],
            },
        )
        session.commit()
        event_id = session.execute(
            text("SELECT id FROM events WHERE event_key = :key"),
            {"key": config["event_key"]},
        ).scalar()
    return event_id


# ── Formatting ────────────────────────────────────────────────────────────────


def _print_result(title: str, result, elapsed: float) -> None:
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", width=26)
    table.add_column()
    table.add_row("Run ID", str(result.run_id))
    table.add_row("Status", result.status)
    table.add_row("[green]✓ Snapshot recorded[/green]", f"[green]{result.fetched}[/green]")
    table.add_row("[red]✗ Errors[/red]", f"[red]{result.errors}[/red]")
    console.print(table)
    console.print(f"  [dim]Elapsed: {elapsed:.1f}s[/dim]")
    console.print()


# ── CLI group ─────────────────────────────────────────────────────────────────


@click.group()
def cli() -> None:
    """Ticket Market Intelligence — SeatGeek pipeline."""
    _run_migrations()


# ── from-api ─────────────────────────────────────────────────────────────────


@cli.command("from-api")
@click.option("--config", "-c", "config_name", required=True)
@click.option(
    "--mode", "-m",
    type=click.Choice(["initial", "periodic"], case_sensitive=False),
    default="periodic", show_default=True,
    help="initial or periodic — both fetch the same aggregate price stats from SeatGeek.",
)
def from_api(config_name: str, mode: str) -> None:
    """Fetch aggregate price stats from SeatGeek for the event in the config.

    SeatGeek's public API does not expose individual ticket listings — only an
    aggregate stats object (lowest/highest/average price, listing count) per
    event. This command appends one price-trend snapshot per run.
    """
    console.print()
    total_start = time.monotonic()

    config = _load_config(config_name)
    sg_event_id = config.get("seatgeek_event_id")

    if not sg_event_id:
        console.print(
            f"[yellow]No seatgeek_event_id in config {config_name!r} — skipping.[/yellow]\n"
            "[dim]Add seatgeek_event_id to the config YAML to enable SeatGeek for this event.[/dim]"
        )
        console.print()
        return

    if not settings.seatgeek_client_id:
        console.print("[red]SEATGEEK_CLIENT_ID is not set in .env — cannot fetch SeatGeek data.[/red]")
        raise SystemExit(1)

    event_id = _resolve_event(config)

    client = SeatGeekClient(settings.seatgeek_client_id)
    event_data = client.get_event(int(sg_event_id))

    source_label = f"{config_name}:seatgeek:{mode}"
    t0 = time.monotonic()
    result = run_snapshot(
        event_data,
        source=source_label,
        event_id=event_id,
        event_key=config["event_key"],
        sg_event_id=int(sg_event_id),
    )
    _print_result("STAGE 1 — SeatGeek Price Snapshot", result, time.monotonic() - t0)

    console.print(Rule(f"[dim]Done in {time.monotonic() - total_start:.1f}s[/dim]"))
    console.print()


if __name__ == "__main__":
    cli()
