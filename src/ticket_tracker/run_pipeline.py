"""CLI entry point for the Ticket Market Intelligence data pipeline.

Usage:
    # Full pipeline (stage 1 → stage 2)
    python -m ticket_tracker.run_pipeline --file sample_data/apify_raider-api.json

    # Stage 1 only (ingest to raw table)
    python -m ticket_tracker.run_pipeline --file sample_data/apify_raider-api.json --stage stage1

    # Stage 2 only (transform records already in raw table)
    python -m ticket_tracker.run_pipeline --stage stage2
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

from ticket_tracker.pipeline.orchestrator import StageResult, run_stage1, run_stage2

console = Console()

# Configure loguru: clean format, no default handler.
logger.remove()
logger.add(sys.stderr, format="<level>{level: <8}</level> | {message}", level="INFO")


# ── Formatting helpers ────────────────────────────────────────────────────────


def _print_stage1_summary(result: StageResult, elapsed: float) -> None:
    console.print(Rule("[bold cyan]STAGE 1 — Extract & Load Raw[/bold cyan]"))

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", width=26)
    table.add_column()

    table.add_row("Run ID", str(result.run_id))
    table.add_row("Total records", str(result.total))
    table.add_row("[green]✓ Loaded to raw[/green]", f"[green]{result.success}[/green]")
    table.add_row("[red]✗ Errors[/red]", f"[red]{result.errors}[/red]")

    console.print(table)

    if result.error_breakdown:
        for code, count in sorted(result.error_breakdown.items()):
            console.print(f"    [dim]└─[/dim] {code:<30} {count:>4}")

    console.print(f"  [dim]Elapsed: {elapsed:.1f}s[/dim]")
    console.print()


def _print_stage2_summary(result: StageResult, elapsed: float) -> None:
    console.print(Rule("[bold cyan]STAGE 2 — Transform[/bold cyan]"))

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", width=26)
    table.add_column()

    table.add_row("Run ID", str(result.run_id))
    table.add_row("Raw records read", str(result.total))
    table.add_row("[green]✓ Transformed[/green]", f"[green]{result.success}[/green]")
    table.add_row("[red]✗ Errors[/red]", f"[red]{result.errors}[/red]")

    console.print(table)

    if result.listing_type_counts:
        console.print("  [dim]Listing type breakdown:[/dim]")
        for lt, count in sorted(result.listing_type_counts.items()):
            console.print(f"    [dim]└─[/dim] {lt:<20} {count:>4}")

    if result.error_breakdown:
        console.print("  [dim]Error breakdown:[/dim]")
        for code, count in sorted(result.error_breakdown.items()):
            console.print(f"    [dim]└─[/dim] {code:<30} {count:>4}")

    console.print(f"  [dim]Elapsed: {elapsed:.1f}s[/dim]")
    console.print()


# ── CLI ───────────────────────────────────────────────────────────────────────


@click.command()
@click.option(
    "--file",
    "-f",
    "source_file",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to Apify JSON output file. Required for stage1 and all.",
)
@click.option(
    "--stage",
    "-s",
    type=click.Choice(["all", "stage1", "stage2"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Which pipeline stage to run.",
)
def cli(source_file: Path | None, stage: str) -> None:
    """Ticket Market Intelligence — data pipeline runner."""
    stage = stage.lower()

    if stage in ("all", "stage1") and source_file is None:
        raise click.UsageError(
            "--file is required when running stage1 or all.\n"
            "Use --stage stage2 to run only the transform step."
        )

    if source_file is not None and not source_file.exists():
        raise click.BadParameter(
            f"File not found: {source_file}", param_hint="'--file'"
        )

    console.print()
    total_start = time.monotonic()

    if stage in ("all", "stage1"):
        t0 = time.monotonic()
        result1 = run_stage1(source_file)  # type: ignore[arg-type]
        _print_stage1_summary(result1, time.monotonic() - t0)

    if stage in ("all", "stage2"):
        t0 = time.monotonic()
        result2 = run_stage2()
        _print_stage2_summary(result2, time.monotonic() - t0)

    total_elapsed = time.monotonic() - total_start
    console.print(Rule(f"[dim]Done in {total_elapsed:.1f}s[/dim]"))
    console.print()


if __name__ == "__main__":
    cli()
