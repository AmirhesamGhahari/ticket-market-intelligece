# Ticket Market Intelligence — Code and Product Suggestions

## Overall opinion

The product idea is strong and worth pursuing. The positioning — helping buyers understand the resale market before purchasing — is useful, and Toronto plus EDM events is a sensible initial niche.

The current repository, however, is not yet a reliable implementation of the documented platform. It is currently a narrow BrightData/VELD batch experiment, while the documentation describes an Apify-based, multi-source historical intelligence system.

Keep the product idea, but strengthen the data foundation before adding AI, prediction, or many platforms.

## What is good

- Clear customer problem and useful positioning.
- Toronto/VELD is a reasonable starting wedge.
- Data-first thinking is correct.
- PostgreSQL, SQLAlchemy, Alembic, raw/silver separation, and Decimal pricing are appropriate choices.
- Incremental transformation and pipeline-run tracking are good foundations.
- Avoiding AWS, Celery, and unnecessary infrastructure at MVP stage is sensible.
- The documentation shows strong product ambition and thoughtful future direction.

## Critical issues to fix immediately

### 1. Sensitive Facebook cookies are committed

The tracked Apify fixture contains cookie data in all 720 records, despite the documentation saying cookies were stripped.

Treat this as compromised data:

- Revoke or rotate the Facebook session immediately.
- Remove the cookies from the working tree.
- Remove them from Git history if the repository has been shared.
- Add automated secret scanning.
- Never store scraper authentication material in raw payloads.

Relevant fixture: `sample_data/apify_raider-api.json`.

### 2. The documented Apify input does not work with the current code

Stage 1 expects BrightData fields such as `price.formatted`, `location.city`, `location.state`, `primaryImage`, and `isSold`.

The Apify fixture uses fields such as `initial_price`, `final_price`, `product_id`, `profile_id`, `location`, `images`, and `is_sold`.

The current loader would incorrectly ingest scraper error records and produce mostly-null listing data when run against the Apify fixture.

Choose one of these approaches:

1. Standardize on BrightData and update the Apify documentation and fixture.
2. Standardize on Apify and restore an Apify adapter.
3. Recommended: create source adapters that convert each provider into one canonical internal record.

### 3. CDC can create duplicate current records

The loader loads current state once and does not update its in-memory state after inserting a record. Duplicate URLs in one input file can therefore create multiple rows with `valid_to IS NULL`.

The database has a partial index, but not a unique partial index. Concurrent pipeline runs can also race.

Add:

- Deduplication within each input batch.
- A unique database constraint/index for one current row per listing.
- Database-level upsert logic or an advisory lock.
- Idempotency based on source plus external listing ID.

### 4. The pipeline does not actually create price history

The vision says every crawl should create an immutable price observation. The current implementation only creates a new CDC version when selected fields change. Unchanged crawls are skipped entirely.

Add a separate append-only `listing_observations` table containing:

- listing ID
- observed timestamp
- price and currency
- sold/active state
- source run ID
- raw record hash

Use CDC for versioned attributes and observations for market history.

## Data-quality problems

The current Stage 2 transformation is weaker than the documentation promises:

- It hard-codes CAD.
- It hard-codes anomaly thresholds of `$50–$2000`.
- It ignores `PRICE_MIN` and `PRICE_MAX` from configuration.
- It only recognizes `Nx` quantity patterns.
- It does not recognize “2 tickets,” “pair,” or “2 passes.”
- It does not normalize locations.
- It does not identify promoter or wanted listings.
- It sets every listing to `resale`.
- It uses only the title for relevance.
- It has no event model or event matching.
- Null titles can produce null values for non-nullable output fields.

The sample data includes merchandise, clothing, promoters, wanted ads, zero-dollar listings, and extreme outliers. These cases require explicit classification rather than a simple title keyword.

## Reliability problems

- No tests exist.
- No CI or linting configuration exists.
- No per-record error table exists.
- Unexpected database errors can leave a pipeline run stuck as `running`.
- Stage 2 has a concurrency race.
- `rowcount` is not a robust inserted-record count.
- Missing listings are never marked inactive.
- `scraped_at` is always null in the BrightData adapter.
- Changes to images, seller, description, or listing date are ignored by CDC.
- The current model is hard-coded to `veld_2026_*` tables.

## Recommended architecture

Do not build the full multi-source platform yet, but create a generic data model now:

```text
sources
events
listings
listing_observations
sellers
ingestion_runs
ingestion_errors
```

Use source adapters:

```text
BrightData adapter ┐
Apify adapter      ├── canonical listing record ── database
Future source      ┘
```

Avoid tables named `veld_2026_raw_extract`. VELD should be an event stored in the database, not encoded into the schema.

## Product strategy for the first real MVP

1. Track one or two Toronto events.
2. Support one reliable source.
3. Build one useful event page containing current listings, lowest comparable price, median price, price history, listing freshness, and original source links.
4. Add price alerts.
5. Manually review event matches and suspicious listings.
6. Measure ingestion success, coverage, duplicate rate, match precision, freshness, alert usage, and repeat visitors.

Do not prioritize prediction, LLM matching, or sophisticated scam scoring yet. Those features depend on clean historical data and can create false confidence. The first moat is trustworthy coverage and historical data.

## Documentation concerns

The documentation and code currently disagree in several places:

- Apify is described as the primary source, while the code uses BrightData.
- The first development plan describes validation and `pipeline_errors`, but those modules were removed.
- The development plan says important features are not started even though some pipeline code exists.
- The Alembic guide claims `pipeline_errors` exists, but the migrations do not create it.
- `.env.example` documents settings that the current `Settings` class no longer defines.
- The product documents describe `events`, `listings`, and `price_snapshots`, but the migrations create none of those tables.

Choose one current architecture and update all documentation to match it.

## Final recommendation

Keep the idea and change the implementation approach.

The next milestone should be:

> Reliably ingest one source, normalize it, preserve every observation, classify listings accurately, and expose one trustworthy event page.

Once that works for VELD and one additional Toronto event, there will be a strong foundation for expanding to other platforms and adding analytics.
