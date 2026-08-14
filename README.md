# Ticket Market Intelligence

A data pipeline for tracking and analyzing event ticket resale prices on Facebook Marketplace. Built initially for Toronto EDM events (VELD, Electric Island, etc.), designed to support any event via config files with zero code changes.

## How it works

The pipeline runs in two stages:

**Stage 1 — Extract:** Scrapes listings from Facebook Marketplace via the [Apify raider-api actor](https://apify.com/raidr/facebook-marketplace-scraper) and loads them into a raw table using Change Data Capture (CDC). Each listing is tracked over time — when price, title, or location changes, the old version is closed and a new one is inserted, preserving the full price history.

**Stage 2 — Transform:** Reads new raw records and enriches them into a clean `transformed` table entirely via SQL: quantity extraction (`2x` patterns), ticket type classification (VIP / GA), event day detection (Friday / Saturday / Sunday), price anomaly flagging, and relevance scoring.

Both stages are idempotent — re-running them is always safe.

```
Apify scraper
      │
      ▼
raw_extract  (CDC — full history per listing)
      │
      ▼
transformed  (enriched, analytics-ready)
```

## Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| Database | PostgreSQL |
| ORM / migrations | SQLAlchemy 2.x, Alembic |
| Scraper | Apify `raider-api/facebook-marketplace-scraper` |
| Config | YAML + `.env` via Pydantic Settings |
| CLI | Click + Rich |

## Project structure

```
├── configs/                    # One YAML file per event
│   └── veld_2026.yaml
├── src/ticket_tracker/
│   ├── config.py               # Settings loaded from .env
│   ├── run_pipeline.py         # CLI entry point
│   ├── db/
│   │   ├── engine.py
│   │   └── models/
│   │       ├── event.py                        # Event registry
│   │       ├── facebook_listing_raw.py         # Raw CDC table
│   │       ├── facebook_listing_transformed.py # Enriched table
│   │       └── pipeline_tables.py              # Pipeline run audit log
│   ├── pipeline/
│   │   ├── stage1_extract/pipeline.py
│   │   └── stage2_transform/pipeline.py
│   └── scraper/
│       └── apify.py            # Apify actor client wrapper
└── alembic/                    # Database migrations
```

## Setup

### Prerequisites

- Python 3.12+
- PostgreSQL 14+
- An [Apify](https://apify.com) account with the `raider-api/facebook-marketplace-scraper` actor (required only for live scraping; not needed for file-based runs)

### Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Environment variables

Copy `.env.example` to `.env` and fill in your values:

```dotenv
DATABASE_URL=postgresql://user:password@localhost:5432/ticket_tracker
APIFY_API_TOKEN=your_apify_token   # leave empty for file-based runs
```

### Database setup

Run all migrations to create the schema:

```bash
alembic upgrade head
```

To generate a new migration after model changes:

```bash
alembic revision --autogenerate -m "describe_the_change"
alembic upgrade head
```

## Usage

### Fetch live from Apify and run both pipeline stages

```bash
# Full initial scrape — no date filter, gets everything available (~30 day FB window)
run-pipeline from-apify --config veld_2026 --mode initial

# Periodic update — recent listings only, uses Apify deduplication
run-pipeline from-apify --config veld_2026 --mode periodic
```

Cities are read from the config file. Multiple cities trigger one Apify run per city; all records are merged before Stage 1.

### Load from a saved JSON file (dev / backfill)

```bash
run-pipeline from-file --config veld_2026 --file sample_data/my_dump.json
```

### Re-run Stage 2 transform only

Useful after editing the transform SQL without new raw data:

```bash
run-pipeline transform --config veld_2026
```

### Run a specific stage only

Any command accepts `--stage stage1`, `--stage stage2`, or `--stage all` (default):

```bash
run-pipeline from-apify --config veld_2026 --mode periodic --stage stage1
```

## Adding a new event

1. Create a new config file in `configs/`:

```yaml
# configs/electric_island_sep_2026.yaml
event_key: "electric_island_sep_2026"
event_name: "Electric Island September 2026"
event_keyword: "electric island"
apify_actor_id: "raidr-api/facebook-marketplace-scraper"
radius_km: "100"

proxy:
  use_apify_proxy: true
  apify_proxy_groups: ["RESIDENTIAL"]
  apify_proxy_country: "CA"

search_terms:
  - "electric island"
  - "electric island 2026"
  - "electric island ticket"
  # ... add more

initial_run:
  cities:
    - "Toronto, Ontario"
  use_deduplication: false
  fetch_detailed_items: false
  listings_per_search: 50

periodic_run:
  cities:
    - "Toronto, Ontario"
  use_deduplication: true
  fetch_detailed_items: false
  listings_per_search: 24
  days_listed: "1"
```

2. Run the pipeline:

```bash
run-pipeline from-apify --config electric_island_sep_2026 --mode initial
```

The event is automatically registered in the database on first run. No code changes, no migrations.

## Config reference

| Field | Description |
|-------|-------------|
| `event_key` | Unique slug used as the DB identifier (matches the filename) |
| `event_name` | Human-readable name stored in the events table |
| `event_keyword` | Word used to score `is_relevant` in transformed listings |
| `apify_actor_id` | Apify actor to call |
| `radius_km` | Search radius from each city center |
| `search_terms` | List of search queries — shared across all cities and modes |
| `{mode}_run.cities` | Cities to search for this mode (one Apify run per city) |
| `{mode}_run.listings_per_search` | Max listings returned per search term |
| `{mode}_run.use_deduplication` | Apify-level dedup (skip listings seen in prior runs) |
| `{mode}_run.days_listed` | Only return listings posted within N days (omit for no filter) |

> Apify advanced mode caps at 50 searches per actor run. Trim `search_terms` if you exceed that.

## Database schema

| Table | Purpose |
|-------|---------|
| `events` | Registry of tracked events — auto-populated on first pipeline run |
| `raw_extract` | Raw CDC records from scrape runs. One row per version of a listing per event. `valid_to IS NULL` = current version |
| `transformed` | Enriched analytics-ready records. One row per raw record. Populated by Stage 2 |
| `pipeline_runs` | Audit log for every Stage 1 and Stage 2 execution with record counts |

### CDC (Change Data Capture)

Stage 1 tracks listing changes over time rather than overwriting:

- **New listing** → insert with `valid_from = now()`, `valid_to = NULL`
- **Existing listing, no change** → skip
- **Existing listing, price/title/location changed** → close old row (`valid_to = now()`), insert new row

A partial unique index on `(event_id, fb_listing_id) WHERE valid_to IS NULL` enforces that each listing has exactly one current version.

## Pipeline run output

Each run prints a summary table:

```
────────────── STAGE 1 — Fetch & Extract ──────────────
  Run ID           3f2a1b...
  Status           completed
  Total records    312
  ✓ Newly added    48
  ~ Changed version  5
  – Skipped        259
  ✗ Errors         0
  Elapsed: 4.2s
```
