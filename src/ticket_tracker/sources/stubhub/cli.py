"""StubHub pipeline CLI.

Commands:
    run-stubhub from-config --config olivia_rodrigo_toronto_oct2026
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
from ticket_tracker.sfn import report_failure, report_success
from ticket_tracker.sources.stubhub.scraper import scrape_event
from ticket_tracker.sources.stubhub.stage1 import run_from_items, PipelineResult

console = Console()
logger.remove()
logger.add(sys.stderr, format="<level>{level: <8}</level> | {message}", level="INFO")

_CONFIGS_DIR = Path.cwd() / "configs"


def _run_migrations() -> None:
    from alembic import command as alembic_command
    from alembic.config import Config
    cfg = Config("alembic.ini")
    alembic_command.upgrade(cfg, "head")


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
                "id":         str(uuid.uuid4()),
                "event_key":  config["event_key"],
                "event_name": config["event_name"],
            },
        )
        session.commit()
        event_id = session.execute(
            text("SELECT id FROM events WHERE event_key = :key"),
            {"key": config["event_key"]},
        ).scalar()
    return event_id


def _print_result(title: str, result: PipelineResult, elapsed: float) -> None:
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", width=26)
    table.add_column()
    table.add_row("Run ID", str(result.run_id))
    table.add_row("Status", result.status)
    table.add_row("Total listings", str(result.total))
    table.add_row("[green]✓ Newly added[/green]", f"[green]{result.newly_added}[/green]")
    table.add_row("[cyan]~ Price/qty changed[/cyan]", f"[cyan]{result.change_added}[/cyan]")
    table.add_row("[dim]– Unchanged[/dim]", f"[dim]{result.skipped}[/dim]")
    table.add_row("[red]✗ Errors[/red]", f"[red]{result.errors}[/red]")
    console.print(table)
    console.print(f"  [dim]Elapsed: {elapsed:.1f}s[/dim]")
    console.print()


@click.group()
def cli() -> None:
    """Ticket Market Intelligence — StubHub pipeline."""
    _run_migrations()


@cli.command("from-config")
@click.option("--config", "-c", "config_name", required=True)
@click.option("--date", "show_date", default=None,
              help="Show date (YYYY-MM-DD) for multi-date events. Selects the matching stubhub_url from event_dates in the YAML.")
def from_config(config_name: str, show_date: str) -> None:
    """Scrape StubHub listings and load to stubhub.listing_raw."""
    console.print()
    total_start = time.monotonic()

    try:
        config    = _load_config(config_name)
        sh_config = config.get("sources", {}).get("stubhub", {})

        if not sh_config.get("enabled", False):
            console.print("[yellow]stubhub source is disabled in this config.[/yellow]")
            report_success({"new_count": 0, "updated_count": 0, "skipped_count": 0, "error_count": 0})
            return

        event_id = _resolve_event(config)

        # Multi-date: --date selects the URL from the event_dates list in YAML.
        # Single-date (no --date): fall back to sources.stubhub.event_url.
        if show_date:
            event_dates = config.get("event_dates", [])
            match = next((e for e in event_dates if e.get("date") == show_date), None)
            if match is None:
                raise click.BadParameter(
                    f"No entry for date {show_date!r} in event_dates list", param_hint="'--date'"
                )
            event_url = match["stubhub_url"]
        else:
            event_url = sh_config["event_url"]

        logger.info(f"[StubHub] Scraping {event_url!r} (show_date={show_date})")
        t0    = time.monotonic()
        items = scrape_event(api_key=settings.scrapfly_api_key, event_url=event_url)
        logger.info(f"[StubHub] Scrape done: {len(items)} items in {time.monotonic() - t0:.1f}s")

        t0     = time.monotonic()
        result = run_from_items(items, source=config_name, event_id=event_id,
                                event_key=config["event_key"], show_date=show_date)
        _print_result("StubHub — Stage 1", result, time.monotonic() - t0)

        report_success({
            "new_count":     result.newly_added,
            "updated_count": result.change_added,
            "skipped_count": result.skipped,
            "error_count":   result.errors,
        })
        console.print(Rule(f"[dim]Done in {time.monotonic() - total_start:.1f}s[/dim]"))
        console.print()

    except Exception as exc:
        report_failure(type(exc).__name__, str(exc))
        raise


if __name__ == "__main__":
    cli()
