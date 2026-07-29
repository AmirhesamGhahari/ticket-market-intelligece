# Ticket Market Intelligence — Development Plan

> Living document. Update this file as decisions are made, milestones are hit, and the plan evolves.
> Vision & product philosophy → see `Ticket_Project_Vision_Blueprint.md`
> High-level feature list → see `Ticket_Market_Intelligence_Project_Plan.md`

---

## Status

| Phase | Status |
|-------|--------|
| 1 — Ingest pipeline | Not started |
| 2 — API server | Not started |
| 3 — Website (MVP) | Not started |
| 4 — Event matching (LLM) | Not started |
| 5 — Alerts & notifications | Not started |

---

## Decisions Log

A record of key decisions made and the reasoning behind them. Add new entries here as decisions are finalized.

| Date | Decision | Reasoning |
|------|----------|-----------|
| 2026-07-24 | MVP data source: Facebook Marketplace only | Highest listing volume for Toronto EDM. Apify + BrightData scrapers handle the access layer. |
| 2026-07-24 | No AWS for MVP | Too much DevOps overhead for a solo/small team. VPS + Vercel achieves the same outcome at this scale for $10-30/month. Migrate to AWS when justified by scale. |
| 2026-07-24 | Infrastructure: VPS (Docker Compose) + Vercel | Single server handles FastAPI + PostgreSQL + Nginx. Vercel handles Next.js frontend for free. Simple, cheap, one bill. |
| 2026-07-24 | No queue/worker system in Phase 1 | Apify/BrightData handle scheduling. Webhook triggers ingest directly. Celery/Redis added later when background jobs are needed. |
| 2026-07-24 | Event matching: keyword rules first, LLM fallback in batch | Keyword rules cover ~90% of listings at zero cost. LLM runs nightly on unmatched listings in batch, not per-listing in real time. |
| 2026-07-24 | Never overwrite price or listing state | Always insert `price_snapshots`. This is the core data asset — immutable history enables price charts, trend analysis, and future ML. |

---

## Infrastructure

### Hosting

| Component | Service | Cost |
|-----------|---------|------|
| API server (FastAPI) | DigitalOcean / Hetzner VPS | ~$8-12/month |
| Database (PostgreSQL) | Same VPS (Docker) | included |
| Reverse proxy (Nginx + SSL) | Same VPS (Docker) | included |
| Frontend (Next.js) | Vercel | free tier |
| Scraping | Apify + BrightData | pay-per-run |

**Total estimated infrastructure cost (MVP): ~$10-30/month**

### Deployment

The VPS runs a single `docker-compose.yml` with three services: `api`, `db`, `nginx`.
Deploy by SSH into the server and running `docker compose pull && docker compose up -d`.

Later: set up GitHub Actions for automatic deploy on push to `main`.

### When to migrate to AWS

Only when one of these is true:
- Need S3 for bulk image archiving
- Need SES for transactional email at scale (>10k emails/day)
- Need RDS multi-AZ for production-grade database HA
- Monthly bill on VPS exceeds $100 (means the product has real scale)

---

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Language | Python 3.12 | |
| API framework | FastAPI | Handles both ingest webhook and public API |
| Database | PostgreSQL 16 | Core data store |
| ORM | SQLAlchemy 2.x | With Alembic for migrations |
| Task queue | — (Phase 1: none) | Add Celery + Redis in Phase 4+ |
| Frontend | Next.js 14 (App Router) | |
| UI | Tailwind CSS | |
| Charts | Recharts or Tremor | Price history visualization |
| Reverse proxy | Nginx | SSL via Let's Encrypt / Certbot |
| Containerization | Docker + Docker Compose | |
| Scraping | Apify, BrightData | Managed scrapers, webhook delivery |
| LLM | Claude API (Anthropic) | Event matching fallback, batch only |

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Apify / BrightData                                          │
│  Scheduled runs (configurable cadence per event proximity)   │
│  Webhook fires on run completion → POST raw JSON payload     │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI  —  Ingest Layer                                    │
│                                                              │
│  POST /ingest/facebook-marketplace                           │
│    1. parse_price()          "CA$250" → 250.00 CAD           │
│    2. normalize_location()   "Richmond Hill" → "GTA"         │
│    3. extract_quantity()     "2x VELD" → quantity=2          │
│    4. filter_promoters()     price == $1 → flag/skip         │
│    5. match_event()          keyword lookup → event_id        │
│    6. dedup_check()          by listing URL (has listing ID) │
│    7. upsert_listing()       create or update last_seen      │
│    8. insert_price_snapshot() always append, never overwrite │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  PostgreSQL                                                  │
│  events · listings · price_snapshots · event_keywords        │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI  —  Public API Layer                                │
│                                                              │
│  GET /api/events                                             │
│  GET /api/events/{id}                                        │
│  GET /api/events/{id}/stats                                  │
│  GET /api/events/{id}/listings                               │
│  GET /api/events/{id}/price-history                          │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  Next.js  (Vercel)                                           │
│  /events/veld-2026  →  price chart, stats, listing cards     │
└──────────────────────────────────────────────────────────────┘
```

---

## Data Pipeline — Step by Step

### 1. Scraping cadence (configured on Apify/BrightData side)

| Time until event | Crawl frequency |
|-----------------|-----------------|
| > 30 days | Daily |
| 8–30 days | Every 6 hours |
| 2–7 days | Every hour |
| < 48 hours | Every 15 minutes |

Configure these as separate scheduled actors on Apify. Each actor webhooks the same `/ingest` endpoint.

### 2. Ingest processing steps

**Price parsing**
- Strip currency symbol and code: `"CA$250"` → `250.00`
- Store original string and parsed float separately
- Flag anomalies: price < $10 (likely promoter), price > $2000 (likely scam or multi-ticket)

**Location normalization**
- Map granular city names to GTA region:
  - Toronto, North York, Scarborough, Etobicoke → `"Toronto"`
  - Mississauga, Brampton, Oakville, Burlington → `"West GTA"`
  - Richmond Hill, Markham, Vaughan, Thornhill → `"North GTA"`
  - Hamilton, Niagara Falls → `"Outside GTA"`
- Store both raw city and normalized region

**Quantity extraction**
- Parse title for patterns: `"2x"`, `"2 tickets"`, `"pair"`, `"single"`, `"1x"`
- Default to `quantity=1` if no pattern found
- Store as `quantity_listed` — affects per-unit price calculation

**Promoter / spam filter**
- Flag listings where `price == 1` as `listing_type = "promoter"` — exclude from analytics
- Flag listings with titles containing "official promoter", "INK promoter" as `listing_type = "promoter"`
- These are stored but excluded from price stats by default

**Event matching (keyword layer)**
- Lowercase the listing title
- Check against `event_keywords` table (keyword → event_id)
- On match: set `event_id`
- On no match: set `event_id = NULL`, `needs_review = true`

**Deduplication**
- Primary dedup key: listing URL (contains Facebook's listing ID)
- On existing URL: update `last_seen`, update price if changed
- On new URL: insert new listing

**Snapshot**
- Every ingest run, insert one row into `price_snapshots` regardless of whether price changed
- This gives us the full time series for charting

### 3. Event matching — two layers

**Layer 1: Keyword rules (synchronous, in-request)**
```
event_keywords table:
  "veld"             → veld-2026
  "veld 2026"        → veld-2026
  "veld festival"    → veld-2026
  "osheaga"          → osheaga-2026
  "electric island"  → electric-island-2026
  ...
```
Covers ~90% of listings. Zero cost. Runs inline during ingest.

**Layer 2: LLM fallback (async, nightly batch)**
- Nightly cron job: `SELECT * FROM listings WHERE event_id IS NULL AND needs_review = true`
- Send title + description in batches to Claude API
- Claude returns: `{ event_id: "veld-2026" | null, confidence: "high|medium|low" }`
- Low confidence → flag for manual review
- Only run on listings collected in last 7 days (older unmatched = probably irrelevant)

---

## Database Schema

```sql
-- Canonical events
CREATE TABLE events (
    id          TEXT PRIMARY KEY,          -- e.g. "veld-2026"
    name        TEXT NOT NULL,             -- "VELD Music Festival 2026"
    date_start  DATE,
    date_end    DATE,
    venue       TEXT,
    city        TEXT,
    face_value  NUMERIC(10,2),             -- official ticket price if known
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Keywords that map to events (many keywords → one event)
CREATE TABLE event_keywords (
    keyword     TEXT PRIMARY KEY,
    event_id    TEXT REFERENCES events(id)
);

-- One row per unique listing (by URL / listing ID)
CREATE TABLE listings (
    id              BIGSERIAL PRIMARY KEY,
    platform        TEXT NOT NULL,             -- "facebook_marketplace"
    listing_url     TEXT UNIQUE NOT NULL,      -- dedup key
    event_id        TEXT REFERENCES events(id),
    title           TEXT,
    price_raw       TEXT,                      -- "CA$250" (original)
    price           NUMERIC(10,2),             -- 250.00 (parsed)
    currency        TEXT DEFAULT 'CAD',
    quantity        INT DEFAULT 1,             -- number of tickets
    price_per_unit  NUMERIC(10,2),             -- price / quantity
    location_raw    TEXT,                      -- "Richmond Hill"
    location_region TEXT,                      -- "North GTA"
    image_url       TEXT,
    is_sold         BOOLEAN DEFAULT false,
    listing_type    TEXT DEFAULT 'resale',     -- 'resale' | 'promoter' | 'spam'
    needs_review    BOOLEAN DEFAULT false,     -- unmatched listings
    first_seen      TIMESTAMPTZ NOT NULL,
    last_seen       TIMESTAMPTZ NOT NULL,
    search_query    TEXT                       -- which search triggered this
);

-- Append-only price history (one row per crawl per listing)
CREATE TABLE price_snapshots (
    id          BIGSERIAL PRIMARY KEY,
    listing_id  BIGINT REFERENCES listings(id),
    event_id    TEXT REFERENCES events(id),
    price       NUMERIC(10,2),
    is_sold     BOOLEAN,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX ON listings(event_id);
CREATE INDEX ON listings(event_id, listing_type, is_sold);
CREATE INDEX ON price_snapshots(event_id, observed_at);
CREATE INDEX ON price_snapshots(listing_id, observed_at);
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/events` | List all tracked events |
| GET | `/api/events/{id}` | Event metadata |
| GET | `/api/events/{id}/stats` | Min/avg/median price, active listing count, last updated |
| GET | `/api/events/{id}/listings` | All active resale listings (sorted by price) |
| GET | `/api/events/{id}/price-history` | Time-series data for price chart |
| POST | `/ingest/facebook-marketplace` | Webhook receiver (internal, not public) |

### Example `/api/events/{id}/stats` response

```json
{
  "event_id": "veld-2026",
  "event_name": "VELD Music Festival 2026",
  "active_listings": 47,
  "price_min": 175.00,
  "price_avg": 342.00,
  "price_median": 320.00,
  "price_max": 850.00,
  "face_value": 299.00,
  "last_crawled_at": "2026-07-24T14:30:00Z"
}
```

---

## Website Pages (MVP)

### `/events/[slug]` — Event page (core MVP page)

- Event name, date, venue
- Price stats bar: Min · Median · Avg · Max
- Price history chart (line chart, last 7/14/30 days)
- Active listings table: title, price, per-unit price, location, link to original
- Filter by: ticket type (GA/VIP), day, quantity

### `/` — Homepage

- Search bar
- List of tracked events (Toronto EDM focus)

### Future pages

- `/events/[slug]/alerts` — set a price alert
- `/compare` — compare two events

---

## Development Phases

### Phase 1 — Ingest Pipeline
**Goal:** Raw Facebook Marketplace data flowing into PostgreSQL reliably.

- [ ] Set up VPS (DigitalOcean or Hetzner)
- [ ] Docker Compose: FastAPI + PostgreSQL + Nginx
- [ ] PostgreSQL schema + Alembic migrations
- [ ] `POST /ingest/facebook-marketplace` endpoint
- [ ] Price parser (`"CA$250"` → `250.00`)
- [ ] Location normalizer (city → GTA region)
- [ ] Quantity extractor from title
- [ ] Promoter filter (price == $1, keyword patterns)
- [ ] Keyword-based event matcher
- [ ] Listing upsert (dedup by URL)
- [ ] Price snapshot insert
- [ ] Configure Apify/BrightData webhook to hit `/ingest`
- [ ] Verify real data flows end-to-end

### Phase 2 — API Server
**Goal:** Clean JSON endpoints the frontend can consume.

- [ ] `GET /api/events`
- [ ] `GET /api/events/{id}/stats`
- [ ] `GET /api/events/{id}/listings`
- [ ] `GET /api/events/{id}/price-history`
- [ ] Filtering: listing_type=resale, is_sold=false
- [ ] Basic auth / API key on ingest endpoint (security)

### Phase 3 — Website MVP
**Goal:** One working event page a real user could find useful.

- [ ] Next.js project setup on Vercel
- [ ] Event page `/events/[slug]`
- [ ] Price stats display
- [ ] Price history chart (Recharts or Tremor)
- [ ] Listings table with link to original FB listing
- [ ] Homepage with event list
- [ ] Mobile responsive

### Phase 4 — Event Matching (LLM)
**Goal:** Automatically classify listings that keyword rules miss.

- [ ] Nightly batch job for `needs_review = true` listings
- [ ] Claude API integration
- [ ] Confidence scoring
- [ ] Manual review queue for low-confidence matches

### Phase 5 — Alerts & Notifications
**Goal:** Users can get notified when price drops.

- [ ] User accounts (simple email + password)
- [ ] Alert creation: event + price threshold
- [ ] Notification trigger: on ingest, check alerts
- [ ] Email delivery (Resend or Postmark)

### Phase 6 — Duplicate Detection
**Goal:** Detect the same ticket listed multiple times across sessions.

- [ ] Image hash comparison
- [ ] Title similarity scoring (fuzzy match)
- [ ] Same seller + same event + similar price → flag as likely duplicate

---

## Key Data Insights from Sample Data

Observations from `brightdata_fb-market-scraper.json` (VELD 2026 listings):

- **Price range**: CA$175 – CA$850 for legitimate resale
- **Promoter listings at CA$1**: These are official promoters (INK Promoter, etc.) — must be filtered out of analytics
- **"Looking for tickets" listings at CA$1**: Buyers posting wanted ads — also filter
- **Quantity in title is inconsistent**: "2x", "2 tickets", "Saturday and Sunday", "pair", "3 day" — all need parsing
- **Seller info not present** in BrightData flat format — need to confirm if Apify format includes seller profile URL
- **`listing_date_ms`** is reliable for `first_seen` tracking
- **`isSold`** field exists — important for inventory tracking (poll and update)
- **Cities span GTA**: Toronto, Mississauga, Richmond Hill, Markham, Hamilton, Whitby, Pickering, Burlington, Vaughan, Oakville, Brampton, Clarington — normalize to region

---

## Open Questions

- [ ] Does Apify raider format include seller profile URL or seller ID? (critical for cross-listing dedup and seller scoring)
- [ ] What is the Apify/BrightData cost per run at the planned crawl frequency?
- [ ] Will Apify/BrightData scrapers need separate configurations per search query, or can one actor handle multiple queries?
- [ ] Domain name and brand name decided?
- [ ] VPS preference: DigitalOcean vs Hetzner vs other?

---

## Future Roadmap (Post-MVP)

- Seller scoring (reputation, account age, repost frequency)
- Scam detection (image hash reuse, suspicious language, unrealistic pricing)
- Price prediction ("buy now or wait")
- Multi-source ingestion (StubHub, SeatGeek, Reddit, Kijiji)
- Organizer-facing analytics dashboard (B2B)
- Public API with rate limiting + API keys
- Expand to other Canadian cities
- ClickHouse for analytics at scale
