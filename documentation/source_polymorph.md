# Source Polymorph — Change Summary

Complete record of all files created and modified to add the `facebook_marketplace`
(curious_coder actor) and `stubhub` (Scrapfly) sources alongside the existing `facebook`
(raidr-api) source. Existing code and tables are untouched.

---

## Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| DB isolation | New PostgreSQL schemas (`facebook`, `stubhub`) | Clean separation; existing `public` tables untouched |
| FB old vs new actor | Completely separate tables | Existing data collection continues uninterrupted; no schema changes to live data |
| StubHub CDC tracking | `(event_id, listing_id)` key; tracks `raw_price`, `available_tickets`, `display_price`, `is_cheapest` | Price changes are the core product signal |
| Scrapfly integration | httpx direct HTTP calls (no extra dependency) | httpx already in project; saves one package |
| curious_coder input | `urls` field with constructed FB Marketplace search URLs | One actor run covers all search terms simultaneously |

---

## New Files Created (13)

### Database Models

**`src/ticket_tracker/db/models/facebook_marketplace_listing_raw.py`**
- SQLAlchemy model for `facebook.listing_raw`
- Maps curious_coder actor output fields: `marketplace_listing_title`, `listing_price.amount`, `creation_time` (seconds), `is_sold`, `is_pending`, `listing_photos`, etc.
- CDC: `valid_from` / `valid_to`, unique partial index on `(event_id, fb_listing_id) WHERE valid_to IS NULL`
- FK to `public.events` and `public.pipeline_runs`

**`src/ticket_tracker/db/models/stubhub_listing_raw.py`**
- SQLAlchemy model for `stubhub.listing_raw`
- Fields: `listing_id`, `section`, `ticket_class`, `row`, `seat_from/to`, `available_tickets`, `available_quantities`, `raw_price`, `display_price`, `total_price`, `currency`, `face_value`, `face_value_currency`, `ticket_type`, `deal_score`, `star_rating`, `listing_notes`, `is_cheapest`, `is_sponsored`, `stubhub_created_at`
- CDC: `valid_from` / `valid_to`, unique partial index on `(event_id, listing_id) WHERE valid_to IS NULL`
- FK to `public.events` and `public.pipeline_runs`

### Alembic Migration

**`alembic/versions/b9c0d1e2f3a4_add_facebook_and_stubhub_schemas.py`**
- `down_revision = '3e833675849f'` (chains from the classify table migration)
- `upgrade()`: creates `facebook` schema + `facebook.listing_raw`, creates `stubhub` schema + `stubhub.listing_raw`
- `downgrade()`: drops both tables and schemas in reverse order
- Run with: `alembic upgrade head`

### Sources — `facebook_marketplace`

**`src/ticket_tracker/sources/facebook_marketplace/__init__.py`** — empty package marker

**`src/ticket_tracker/sources/facebook_marketplace/scraper.py`**
- `CuriousCoderRunner` — wraps `ApifyClient`, calls actor, returns items (identical pattern to existing `ApifyRunner`)
- `build_run_input()` — constructs Facebook Marketplace search URLs from `location_slug` + `search_terms` and passes them via the `urls` field so one actor run covers all terms
- `onlyNewListings=True` for periodic runs, `False` for initial; `cacheStorageId` persists across runs for actor-level dedup

**`src/ticket_tracker/sources/facebook_marketplace/stage1.py`**
- CDC into `facebook.listing_raw` (same pattern as `sources/facebook/stage1.py`)
- Updated field mappings vs old actor:

| Old (raidr-api) | New (curious_coder) |
|---|---|
| `record.get("listingId") or record.get("id")` | `record.get("id")` |
| `record.get("title")` | `record.get("marketplace_listing_title")` |
| `price.get("formatted")` (parse string) | `listing_price.get("amount")` (already numeric) |
| `price.get("currency")` | `listing_price.get("currency")` |
| `record.get("primaryImage")` | `listing_photos[0].get("uri")` |
| `record.get("isSold")` | `record.get("is_sold")` |
| `listing_date_ms` (milliseconds → divide by 1000) | `creation_time` (Unix seconds → use directly) |
| — | `record.get("is_pending")` (new field) |
| — | `seller.get("name")` / `seller.get("id")` (new fields) |
| `redacted_description.text` | same |

- `_parse_listed_at()`: uses `datetime.fromtimestamp(seconds)` not `/1000`
- CDC fields: `price`, `is_sold`, `is_pending`, `title`, `location_city`, `location_state`
- Entry point: `run_from_records(records, source, event_id, event_key)`

**`src/ticket_tracker/sources/facebook_marketplace/cli.py`**
- CLI group `run-facebook-marketplace`
- Command: `from-config --config <name> --mode [initial|periodic]`
- Reads `sources.facebook_marketplace` block from new-format YAML configs
- Guards on `enabled: true/false`

### Sources — `stubhub`

**`src/ticket_tracker/sources/stubhub/__init__.py`** — empty package marker

**`src/ticket_tracker/sources/stubhub/scraper.py`**
- `scrape_event(api_key, event_url, max_listings)` — implements the confirmed GET+POST Scrapfly strategy documented in `stubhub_record_extraction.md`
- Phase 1: GET with `asp=true`, `render_js=false`, `session=stubhub_<random>`, `proxy_pool=public_datacenter_pool`, `country=us`
- Extracts `window.digitalData` JSON from HTML using `json.JSONDecoder().raw_decode()` (robust, no fragile regex)
- Phase 2: POST same URL with `Method: IndexShGridOnly`, `CurrentPage: N`, per page 2..N
- Same session on all requests — DataDome cookie carried forward automatically (sticky proxy)
- Uses httpx directly (no extra dependency); POST body passed as `method=POST&body=...` GET params to Scrapfly

**`src/ticket_tracker/sources/stubhub/stage1.py`**
- CDC into `stubhub.listing_raw`
- CDC key: `(event_id, listing_id)`
- CDC fields: `raw_price`, `available_tickets`, `display_price`, `is_cheapest`
- Field mapping directly from StubHub listing JSON (`listingId`, `section`, `row`, `rawPrice`, `ticketTypeName`, `inventoryListingScore.dealScore`, etc.)
- Entry point: `run_from_items(items, source, event_id, event_key)`

**`src/ticket_tracker/sources/stubhub/cli.py`**
- CLI group `run-stubhub`
- Command: `from-config --config <name>`
- Reads `sources.stubhub` block from new-format YAML configs
- Calls scraper → stage1 in sequence

### Config

**`configs/olivia_rodrigo_toronto_oct2026.yaml`** — First event using the new multi-source format:
```
event_key:  olivia_rodrigo_toronto_oct2026
event_name: Olivia Rodrigo Toronto 2026
event_date: 2026-10-26

sources:
  facebook_marketplace:
    enabled: true
    actor_id: curious_coder/facebook-marketplace
    cache_storage_id: fb_cache_olivia_rodrigo_toronto_2026
    location_slug: toronto
    search_terms: [12 terms]
    initial_run: { listings_per_search: 500 }
    periodic_run: { listings_per_search: 100, days_listed: 1 }

  stubhub:
    enabled: true
    event_url: https://www.stubhub.com/olivia-rodrigo.../event/161041533/?quantity=0
    max_listings: 9999
```

---

## Modified Files (4)

**`src/ticket_tracker/db/models/__init__.py`**
- Added imports for `FacebookMarketplaceListingRaw` and `StubHubListingRaw`
- Added both to `__all__`

**`alembic/env.py`**
- Added `facebook_marketplace_listing_raw, stubhub_listing_raw` to the model import line so Alembic's metadata includes the new schemas

**`src/ticket_tracker/config.py`**
- Added `scrapfly_api_key: str = ""` setting
- Add `SCRAPFLY_API_KEY=your_key` to `.env`

**`pyproject.toml`**
- Added two new CLI entry points:
  - `run-facebook-marketplace = "ticket_tracker.sources.facebook_marketplace.cli:cli"`
  - `run-stubhub = "ticket_tracker.sources.stubhub.cli:cli"`

---

## Nothing Touched

These files and tables are completely unchanged:

- `sources/facebook/` — raidr-api pipeline continues as-is
- `sources/seatgeek/` — untouched
- `public.facebook_listing_raw` — no schema changes
- `public.facebook_listing_classifications` — no schema changes
- `public.pipeline_runs`, `public.events` — no changes
- All existing YAML configs in `configs/` — no changes; they use the old format which only the old pipeline reads

---

## Setup Steps

```bash
# 1. Add your Scrapfly API key to .env
echo "SCRAPFLY_API_KEY=scp-live-xxxx" >> .env

# 2. Re-install the package to register new CLI entry points
pip install -e .

# 3. Run the migration (creates facebook and stubhub schemas + tables)
alembic upgrade head

# 4. First run — FB Marketplace initial scrape for Olivia Rodrigo
run-facebook-marketplace from-config --config olivia_rodrigo_toronto_oct2026 --mode initial

# 5. First run — StubHub for Olivia Rodrigo
run-stubhub from-config --config olivia_rodrigo_toronto_oct2026

# Run both in parallel (background jobs):
run-facebook-marketplace from-config --config olivia_rodrigo_toronto_oct2026 --mode periodic &
run-stubhub from-config --config olivia_rodrigo_toronto_oct2026 &
```

---

## New Config Format for Future Events

Add new events using the `sources:` format. Old events keep the old format — both coexist.
Disable a source by setting `enabled: false` if an event isn't on FB Marketplace or StubHub.

---

## Database Layout After Migration

```
public (unchanged)
  ├── events
  ├── pipeline_runs
  ├── facebook_listing_raw          ← raidr-api, live
  ├── facebook_listing_classifications
  └── seatgeek_event_stats

facebook (new)
  └── listing_raw                   ← curious_coder/facebook-marketplace

stubhub (new)
  └── listing_raw                   ← Scrapfly GET+POST
```
