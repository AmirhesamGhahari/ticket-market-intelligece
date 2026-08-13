"""CLI entry point for the data pipeline.

Commands:
    # Fetch live from Apify and run both stages
    run-pipeline from-apify --config veld_2026 --mode initial --location "Toronto, Ontario"
    run-pipeline from-apify --config veld_2026 --mode periodic --location "Montreal, QC"

    # Load from a saved Apify JSON file (dev / backfill)
    run-pipeline from-file --file sample_data/actual_data_raider_craper.json

    # Re-run Stage 2 transform only (no new data needed)
    run-pipeline transform
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import click
import yaml
from loguru import logger
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from ticket_tracker.config import settings
from ticket_tracker.pipeline.stage1_extract.pipeline import run as run_stage1
from ticket_tracker.pipeline.stage1_extract.pipeline import run_from_records as run_stage1_from_records
from ticket_tracker.pipeline.stage2_transform.pipeline import run as run_stage2
from ticket_tracker.scraper.apify import ApifyRunner

console = Console()

logger.remove()
logger.add(sys.stderr, format="<level>{level: <8}</level> | {message}", level="INFO")

_CONFIGS_DIR = Path(__file__).parents[2] / "configs"


# ── Config helpers ────────────────────────────────────────────────────────────


def _load_config(config_name: str) -> dict:
    config_path = _CONFIGS_DIR / f"{config_name}.yaml"
    if not config_path.exists():
        raise click.BadParameter(
            f"Config file not found: {config_path}", param_hint="'--config'"
        )
    with open(config_path) as fh:
        return yaml.safe_load(fh)


def _build_run_input(config: dict, mode: str, location: str) -> dict:
    run_config = config[f"{mode}_run"]

    searches = []
    for s in run_config["searches"]:
        entry: dict = {"searchTerm": s["search_term"]}
        if s.get("min_price") is not None:
            entry["minPrice"] = s["min_price"]
        if s.get("max_price") is not None:
            entry["maxPrice"] = s["max_price"]
        if s.get("days_listed"):
            entry["daysListed"] = s["days_listed"]
        if s.get("listings_per_search"):
            entry["listingsPerSearch"] = s["listings_per_search"]
        if s.get("filter_keywords"):
            entry["filterKeywords"] = s["filter_keywords"]
        searches.append(entry)

    run_input: dict = {
        "searchMode": "advanced",
        "location": location,
        "radiusKm": str(config["radius_km"]),
        "searches": searches,
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
    return run_input


# ── Formatting helpers ────────────────────────────────────────────────────────


def _print_result(title: str, result, elapsed: float) -> None:
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


# ── CLI group ─────────────────────────────────────────────────────────────────


@click.group()
def cli() -> None:
    """Ticket Market Intelligence — data pipeline runner."""


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
    "--location", "-l", required=True,
    help="City or location to search (e.g. 'Toronto, Ontario', 'Montreal, QC').",
)
@click.option(
    "--stage", "-s",
    type=click.Choice(["stage1", "stage2", "all"], case_sensitive=False),
    default="all", show_default=True,
    help="Which pipeline stage to run.",
)
def from_apify(config_name: str, mode: str, location: str, stage: str) -> None:
    """Fetch listings from Apify and run the pipeline."""
    stage = stage.lower()
    console.print()
    total_start = time.monotonic()

    if stage in ("stage1", "all"):
        config = _load_config(config_name)
        run_input = _build_run_input(config, mode, location)
        runner = ApifyRunner(settings.apify_api_token, config["apify_actor_id"])
        t0 = time.monotonic()
        records = runner.run(run_input)
        source_label = f"{config_name}:{mode}:{location}"
        result1 = run_stage1_from_records(records, source=source_label)
        _print_result("STAGE 1 — Fetch & Extract", result1, time.monotonic() - t0)

    if stage in ("stage2", "all"):
        t0 = time.monotonic()
        result2 = run_stage2()
        _print_result("STAGE 2 — Transform", result2, time.monotonic() - t0)

    console.print(Rule(f"[dim]Done in {time.monotonic() - total_start:.1f}s[/dim]"))
    console.print()


# ── from-file ─────────────────────────────────────────────────────────────────


@cli.command("from-file")
@click.option(
    "--file", "-f", "source_file",
    required=True,
    type=click.Path(path_type=Path, exists=True),
    help="Path to a saved Apify JSON file.",
)
@click.option(
    "--stage", "-s",
    type=click.Choice(["stage1", "stage2", "all"], case_sensitive=False),
    default="all", show_default=True,
    help="Which pipeline stage to run.",
)
def from_file(source_file: Path, stage: str) -> None:
    """Load listings from a saved Apify JSON file and run the pipeline."""
    stage = stage.lower()
    console.print()
    total_start = time.monotonic()

    if stage in ("stage1", "all"):
        t0 = time.monotonic()
        result1 = run_stage1(source_file)
        _print_result("STAGE 1 — Extract & Load", result1, time.monotonic() - t0)

    if stage in ("stage2", "all"):
        t0 = time.monotonic()
        result2 = run_stage2()
        _print_result("STAGE 2 — Transform", result2, time.monotonic() - t0)

    console.print(Rule(f"[dim]Done in {time.monotonic() - total_start:.1f}s[/dim]"))
    console.print()


# ── transform ─────────────────────────────────────────────────────────────────


@cli.command("transform")
def transform() -> None:
    """Run Stage 2 transform on any pending raw records (no new data needed)."""
    console.print()
    t0 = time.monotonic()
    result = run_stage2()
    _print_result("STAGE 2 — Transform", result, time.monotonic() - t0)
    console.print(Rule(f"[dim]Done in {time.monotonic() - t0:.1f}s[/dim]"))
    console.print()


if __name__ == "__main__":
    cli()
