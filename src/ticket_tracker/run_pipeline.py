"""CLI entry point for the data pipeline.

Usage:
    # Stage 1 only — extract from BrightData file into raw table
    python -m ticket_tracker.run_pipeline --stage stage1 --file sample_data/brightdata_fb-market-scraper.json

    # Stage 2 only — transform raw records into transformed table
    python -m ticket_tracker.run_pipeline --stage stage2

    # Both stages in sequence
    python -m ticket_tracker.run_pipeline --stage all --file sample_data/brightdata_fb-market-scraper.json
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click
from loguru import logger
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from ticket_tracker.pipeline.stage1_extract.pipeline import run as run_stage1
from ticket_tracker.pipeline.stage2_transform.pipeline import run as run_stage2

console = Console()

logger.remove()
logger.add(sys.stderr, format="<level>{level: <8}</level> | {message}", level="INFO")


# ── Formatting helpers ────────────────────────────────────────────────────────


def _print_result(title: str, result, elapsed: float) -> None:
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", width=26)
    table.add_column()

    table.add_row("Run ID", str(result.run_id))
    table.add_row("Status", result.status)
    table.add_row("Total records", str(result.total))
    table.add_row("[green]✓ Success[/green]", f"[green]{result.success}[/green]")
    table.add_row("[red]✗ Errors[/red]", f"[red]{result.errors}[/red]")

    console.print(table)
    console.print(f"  [dim]Elapsed: {elapsed:.1f}s[/dim]")
    console.print()


# ── CLI ───────────────────────────────────────────────────────────────────────


@click.command()
@click.option(
    "--stage",
    "-s",
    type=click.Choice(["stage1", "stage2", "all"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Which pipeline stage to run.",
)
@click.option(
    "--file",
    "-f",
    "source_file",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to BrightData JSON file. Required for stage1 and all.",
)
def cli(stage: str, source_file: Path | None) -> None:
    """Ticket Market Intelligence — data pipeline runner."""
    stage = stage.lower()

    if stage in ("stage1", "all") and source_file is None:
        raise click.UsageError(
            "--file is required when running stage1 or all.\n"
            "Use --stage stage2 to run the transform step without a file."
        )

    if source_file is not None and not source_file.exists():
        raise click.BadParameter(
            f"File not found: {source_file}", param_hint="'--file'"
        )

    console.print()
    total_start = time.monotonic()

    if stage in ("stage1", "all"):
        t0 = time.monotonic()
        result1 = run_stage1(source_file)  # type: ignore[arg-type]
        _print_result("STAGE 1 — Extract & Load", result1, time.monotonic() - t0)

    if stage in ("stage2", "all"):
        t0 = time.monotonic()
        result2 = run_stage2()
        _print_result("STAGE 2 — Transform", result2, time.monotonic() - t0)

    total_elapsed = time.monotonic() - total_start
    console.print(Rule(f"[dim]Done in {total_elapsed:.1f}s[/dim]"))
    console.print()


if __name__ == "__main__":
    cli()
