"""Facebook Marketplace (futurafree actor) pipeline CLI.

Commands:
    run-facebook-new from-config --config olivia_rodrigo_toronto_oct2026 --mode initial
    run-facebook-new from-config --config olivia_rodrigo_toronto_oct2026 --mode periodic
    run-facebook-new from-config --config olivia_rodrigo_toronto_oct2026 --mode periodic --stage classify
    run-facebook-new classify
    run-facebook-new classify --config olivia_rodrigo_toronto_oct2026
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from typing import Optional

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
from ticket_tracker.sources.facebook_new.scraper import FuturafreeRunner, build_run_input
from ticket_tracker.sources.facebook_new.stage1 import run_from_records, PipelineResult
from ticket_tracker.sources.facebook_new.stage2_classify import run as run_classify, ClassifyResult

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


def _print_scrape_result(title: str, result: PipelineResult, elapsed: float) -> None:
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


def _print_classify_result(title: str, result: ClassifyResult, elapsed: float) -> None:
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", width=26)
    table.add_column()
    table.add_row("Run ID", str(result.run_id))
    table.add_row("Status", result.status)
    table.add_row("Total pending", str(result.total))
    table.add_row("[green]✓ Classified[/green]", f"[green]{result.classified}[/green]")
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
@click.option(
    "--stage", "-s",
    type=click.Choice(["scrape", "classify", "all"], case_sensitive=False),
    default="all", show_default=True,
)
def from_config(config_name: str, mode: str, stage: str) -> None:
    """Fetch FB Marketplace listings and optionally classify them.

    --stage scrape    scrape only (no Gemini)
    --stage classify  classify already-scraped rows (no Apify call)
    --stage all       scrape then classify (default)
    """
    stage = stage.lower()
    console.print()
    total_start = time.monotonic()

    scrape_result   = None
    classify_result = None

    try:
        config    = _load_config(config_name)
        fb_config = config.get("sources", {}).get("facebook_new", {})

        if not fb_config.get("enabled", False):
            console.print(f"[yellow]facebook_new is disabled for {config_name!r} — skipping.[/yellow]")
            report_success({"new_count": 0, "updated_count": 0, "skipped_count": 0, "error_count": 0, "classified_count": 0})
            return

        event_id = _resolve_event(config)

        if stage in ("scrape", "all"):
            mode_cfg = fb_config[f"{mode}_run"]
            runner   = FuturafreeRunner(settings.apify_api_token, fb_config["actor_id"])

            all_records: list[dict] = []
            for term in fb_config["search_terms"]:
                run_input = build_run_input(
                    search_terms=[term],
                    latitude=str(fb_config["latitude"]),
                    longitude=str(fb_config["longitude"]),
                    min_price=str(fb_config.get("min_price", "0")),
                    max_price=str(fb_config.get("max_price", "10000")),
                    days_listed=int(mode_cfg["days_listed"]),
                    listings_per_search=int(mode_cfg["listings_per_search"]),
                    search_radius_km=fb_config.get("search_radius_km"),
                    use_deduplication=bool(mode_cfg.get("use_deduplication", False)),
                    filter_keywords=fb_config.get("filter_keywords") or None,
                )
                logger.info(f"[FB-New] {config_name!r} mode={mode!r} term={term!r}")
                all_records.extend(runner.run(run_input))

            t0            = time.monotonic()
            scrape_result = run_from_records(all_records, source=f"{config_name}:{mode}",
                                             event_id=event_id, event_key=config["event_key"], mode=mode)
            _print_scrape_result("FB Marketplace — Stage 1 (Scrape)", scrape_result, time.monotonic() - t0)

        if stage in ("classify", "all"):
            t0              = time.monotonic()
            classify_result = run_classify(event_id=event_id, event_key=config["event_key"])
            _print_classify_result("FB Marketplace — Stage 2 (Classify)", classify_result, time.monotonic() - t0)

        report_success({
            "new_count":        scrape_result.newly_added   if scrape_result   else 0,
            "updated_count":    scrape_result.change_added  if scrape_result   else 0,
            "skipped_count":    scrape_result.skipped       if scrape_result   else 0,
            "error_count":      scrape_result.errors        if scrape_result   else 0,
            "classified_count": classify_result.classified  if classify_result else 0,
        })
        console.print(Rule(f"[dim]Done in {time.monotonic() - total_start:.1f}s[/dim]"))
        console.print()

    except Exception as exc:
        report_failure(type(exc).__name__, str(exc))
        raise


@cli.command("classify")
@click.option("--config", "-c", "config_name", required=False, default=None)
def classify_cmd(config_name: Optional[str]) -> None:
    """Run LLM classification on unclassified facebook_listings_new_raw rows.

    Without --config, classifies all unclassified listings across every event.
    """
    console.print()
    total_start = time.monotonic()

    event_id = None
    event_key = None
    if config_name:
        config = _load_config(config_name)
        event_id = _resolve_event(config)
        event_key = config["event_key"]

    result = run_classify(event_id=event_id, event_key=event_key)
    _print_classify_result("FB Marketplace — Stage 2 (Classify)", result, time.monotonic() - total_start)
    console.print(Rule(f"[dim]Done in {time.monotonic() - total_start:.1f}s[/dim]"))
    console.print()


if __name__ == "__main__":
    cli()
