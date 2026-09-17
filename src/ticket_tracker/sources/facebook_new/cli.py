"""Facebook Marketplace (futurafree actor) pipeline CLI.

Commands:
    run-facebook-marketplace from-config --config olivia_rodrigo_toronto_oct2026 --mode initial
    run-facebook-marketplace from-config --config olivia_rodrigo_toronto_oct2026 --mode periodic
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
from ticket_tracker.sources.facebook_new.scraper import FuturafreeRunner, build_run_input
from ticket_tracker.sources.facebook_new.stage1 import run_from_records, PipelineResult

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


def _print_result(title: str, result: PipelineResult, elapsed: float) -> None:
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", width=26)
    table.add_column()
    table.add_row("Run ID", str(result.run_id))
    table.add_row("Status", result.status)
    table.add_row("Total records", str(result.total))
    table.add_row("[green]✓ Newly added[/green]", f"[green]{result.newly_added}[/green]")
    table.add_row("[cyan]~ Changed version[/cyan]", f"[cyan]{result.change_added}[/cyan]")
    table.add_row("[dim]– Skipped[/dim]", f"[dim]{result.skipped}[/dim]")
    table.add_row("[red]✗ Errors[/red]", f"[red]{result.errors}[/red]")
    console.print(table)
    console.print(f"  [dim]Elapsed: {elapsed:.1f}s[/dim]")
    console.print()


@click.group()
def cli() -> None:
    """Ticket Market Intelligence — Facebook Marketplace (futurafree) pipeline."""
    _run_migrations()


@cli.command("from-config")
@click.option("--config", "-c", "config_name", required=True)
@click.option(
    "--mode", "-m",
    type=click.Choice(["initial", "periodic"], case_sensitive=False),
    required=True,
)
def from_config(config_name: str, mode: str) -> None:
    """Fetch FB Marketplace listings via futurafree actor and load to facebook.facebook_listings_new_raw."""
    console.print()
    total_start = time.monotonic()

    config = _load_config(config_name)
    fb_config = config.get("sources", {}).get("facebook_marketplace", {})

    if not fb_config.get("enabled", False):
        console.print("[yellow]facebook_marketplace source is disabled in this config.[/yellow]")
        return

    event_id = _resolve_event(config)
    mode_cfg = fb_config[f"{mode}_run"]

    run_input = build_run_input(
        search_terms=fb_config["search_terms"],
        latitude=str(fb_config["latitude"]),
        longitude=str(fb_config["longitude"]),
        min_price=str(fb_config.get("min_price", "0")),
        max_price=str(fb_config.get("max_price", "10000")),
        days_listed=int(mode_cfg["days_listed"]),
        listings_per_search=int(mode_cfg["listings_per_search"]),
        search_radius_km=fb_config.get("search_radius_km"),
        use_deduplication=bool(mode_cfg.get("use_deduplication", False)),
    )

    runner = FuturafreeRunner(settings.apify_api_token, fb_config["actor_id"])
    logger.info(f"[FB-Mkt] Running actor for {config_name!r} mode={mode!r}")
    records = runner.run(run_input)

    t0 = time.monotonic()
    result = run_from_records(
        records,
        source=f"{config_name}:{mode}",
        event_id=event_id,
        event_key=config["event_key"],
    )
    _print_result("FB Marketplace — Stage 1", result, time.monotonic() - t0)
    console.print(Rule(f"[dim]Done in {time.monotonic() - total_start:.1f}s[/dim]"))
    console.print()


if __name__ == "__main__":
    cli()
