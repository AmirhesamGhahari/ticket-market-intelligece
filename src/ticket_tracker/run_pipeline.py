"""CLI entry point for the data pipeline.

Commands:
    # Fetch live from Apify and run both stages (cities come from the config file)
    run-pipeline from-apify --config veld_2026 --mode initial
    run-pipeline from-apify --config veld_2026 --mode periodic

    # Load from a saved Apify JSON file (dev / backfill)
    run-pipeline from-file --config veld_2026 --file sample_data/actual_data_raider_craper.json

    # Classify only — run across all events or a specific one
    run-pipeline classify
    run-pipeline classify --config veld_2026
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
from ticket_tracker.pipeline.stage1_extract.pipeline import run as run_stage1
from ticket_tracker.pipeline.stage1_extract.pipeline import run_from_records as run_stage1_from_records
from ticket_tracker.pipeline.stage2_classify.pipeline import run as run_classify
from ticket_tracker.scraper.apify import ApifyRunner

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
    """Upsert the event into the events table and return its UUID."""
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


def _build_run_inputs(config: dict, mode: str) -> list[dict]:
    """Return one Apify run_input dict per city defined in the config for this mode."""
    run_config = config[f"{mode}_run"]

    searches = []
    for term in config["search_terms"]:
        entry: dict = {"searchTerm": term}
        if run_config.get("listings_per_search"):
            entry["listingsPerSearch"] = run_config["listings_per_search"]
        if run_config.get("days_listed"):
            entry["daysListed"] = run_config["days_listed"]
        if run_config.get("filter_keywords"):
            entry["filterKeywords"] = run_config["filter_keywords"]
        searches.append(entry)

    run_inputs = []
    for city in run_config["cities"]:
        run_input: dict = {
            "searchMode": "advanced",
            "location": city,
            "radiusKm": str(config["radius_km"]),
            "searches": searches,
            "listingsPerSearch": run_config["listings_per_search"],
            "useDeduplication": run_config["use_deduplication"],
            "fetchDetailedItems": run_config.get("fetch_detailed_items", False),
            "proxyConfiguration": {
                "useApifyProxy": config["proxy"]["use_apify_proxy"],
                "apifyProxyGroups": config["proxy"]["apify_proxy_groups"],
                "apifyProxyCountry": config["proxy"]["apify_proxy_country"],
            },
        }
        if run_config.get("max_listing_age") is not None:
            run_input["maxListingAge"] = run_config["max_listing_age"]
        run_inputs.append(run_input)

    return run_inputs


# ── Formatting helpers ────────────────────────────────────────────────────────


def _print_scrape_result(title: str, result, elapsed: float) -> None:
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


def _print_classify_result(title: str, result, elapsed: float) -> None:
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


# ── CLI group ─────────────────────────────────────────────────────────────────


@click.group()
def cli() -> None:
    """Ticket Market Intelligence — data pipeline runner."""
    _run_migrations()


# ── from-apify ────────────────────────────────────────────────────────────────


@cli.command("from-apify")
@click.option(
    "--config", "-c", "config_name", required=True,
    help="Event config name (e.g. veld_2026). Looks in configs/ directory.",
)
@click.option(
    "--mode", "-m",
    type=click.Choice(["initial", "periodic"], case_sensitive=False),
    required=True,
    help="initial = full history fetch. periodic = recent listings only.",
)
@click.option(
    "--stage", "-s",
    type=click.Choice(["scrape", "classify", "all"], case_sensitive=False),
    default="all", show_default=True,
    help="scrape = fetch & store raw only. classify = LLM classify only. all = both.",
)
def from_apify(config_name: str, mode: str, stage: str) -> None:
    """Fetch listings from Apify for every city in the config and run the pipeline."""
    stage = stage.lower()
    console.print()
    total_start = time.monotonic()

    config = _load_config(config_name)
    event_id = _resolve_event(config)

    if stage in ("scrape", "all"):
        run_inputs = _build_run_inputs(config, mode)
        runner = ApifyRunner(settings.apify_api_token, config["apify_actor_id"])

        all_records: list[dict] = []
        for run_input in run_inputs:
            city = run_input["location"]
            logger.info(f"[Apify] Fetching city: {city!r}")
            all_records.extend(runner.run(run_input))

        source_label = f"{config_name}:{mode}"
        t0 = time.monotonic()
        result1 = run_stage1_from_records(all_records, source=source_label, event_id=event_id, event_key=config["event_key"])
        _print_scrape_result("STAGE 1 — Fetch & Extract", result1, time.monotonic() - t0)

    if stage in ("classify", "all"):
        t0 = time.monotonic()
        result2 = run_classify(event_id=event_id)
        _print_classify_result("STAGE 2 — LLM Classify", result2, time.monotonic() - t0)

    console.print(Rule(f"[dim]Done in {time.monotonic() - total_start:.1f}s[/dim]"))
    console.print()


# ── from-file ─────────────────────────────────────────────────────────────────


@cli.command("from-file")
@click.option(
    "--config", "-c", "config_name", required=True,
    help="Event config name (e.g. veld_2026). Looks in configs/ directory.",
)
@click.option(
    "--file", "-f", "source_file",
    required=True,
    type=click.Path(path_type=Path, exists=True),
    help="Path to a saved Apify JSON file.",
)
@click.option(
    "--stage", "-s",
    type=click.Choice(["scrape", "classify", "all"], case_sensitive=False),
    default="all", show_default=True,
    help="scrape = load raw records only. classify = LLM classify only. all = both.",
)
def from_file(config_name: str, source_file: Path, stage: str) -> None:
    """Load listings from a saved Apify JSON file and run the pipeline."""
    stage = stage.lower()
    console.print()
    total_start = time.monotonic()

    config = _load_config(config_name)
    event_id = _resolve_event(config)

    if stage in ("scrape", "all"):
        t0 = time.monotonic()
        result1 = run_stage1(source_file, event_id=event_id, event_key=config["event_key"])
        _print_scrape_result("STAGE 1 — Extract & Load", result1, time.monotonic() - t0)

    if stage in ("classify", "all"):
        t0 = time.monotonic()
        result2 = run_classify(event_id=event_id)
        _print_classify_result("STAGE 2 — LLM Classify", result2, time.monotonic() - t0)

    console.print(Rule(f"[dim]Done in {time.monotonic() - total_start:.1f}s[/dim]"))
    console.print()


# ── classify ──────────────────────────────────────────────────────────────────


@cli.command("classify")
@click.option(
    "--config", "-c", "config_name", required=False, default=None,
    help="Event config name. Omit to classify all unclassified listings across all events.",
)
def classify_cmd(config_name: Optional[str]) -> None:
    """Run LLM classification on unclassified raw listings.

    Without --config, classifies all unclassified listings across every event.
    """
    console.print()
    t0 = time.monotonic()

    event_id = None
    if config_name:
        config = _load_config(config_name)
        event_id = _resolve_event(config)

    result = run_classify(event_id=event_id)
    _print_classify_result("STAGE 2 — LLM Classify", result, time.monotonic() - t0)
    console.print(Rule(f"[dim]Done in {time.monotonic() - t0:.1f}s[/dim]"))
    console.print()


if __name__ == "__main__":
    cli()
