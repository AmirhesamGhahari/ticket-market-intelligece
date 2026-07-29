# Ticket Market Intelligence Platform

## Vision

Build a data-first platform that helps users make better decisions when
buying resale tickets for concerts, festivals, raves, and live events.

This is **not** a ticket marketplace.

It is an **AI-powered ticket market intelligence platform**.

Primary value: - Aggregate listings from multiple sources. - Show the
cheapest available tickets. - Detect scams. - Track historical prices. -
Predict future price movement. - Notify users when prices fall.

Initial focus: - Toronto - EDM festivals - Concerts - Summer events

Expand later to other cities.

------------------------------------------------------------------------

# Core Problem

Users currently search:

-   Facebook Marketplace
-   Facebook Groups
-   Reddit
-   Discord
-   StubHub
-   Ticketmaster Resale

Problems:

-   No single search.
-   Prices scattered.
-   Hard to know fair price.
-   Hard to identify scams.
-   No price history.
-   No price prediction.

------------------------------------------------------------------------

# Product Principles

Data first. Website second.

The moat is the historical dataset and analytics.

------------------------------------------------------------------------

# MVP

Data Sources (priority)

Tier 1 - Facebook Marketplace - Facebook Buy/Sell Groups - Reddit -
StubHub - Ticketmaster Resale - Discord

Tier 2 - SeatGeek - TickPick - Kijiji

Use Apify or similar for initial Facebook ingestion.

------------------------------------------------------------------------

# High Level Architecture

Scrapers ↓ Raw Listings ↓ Normalizer ↓ AI Event Matcher ↓ Duplicate
Detection ↓ Seller Scoring ↓ Historical Database ↓ Prediction Engine ↓
Public API ↓ Website

------------------------------------------------------------------------

# Suggested Tech Stack

Backend - Python - FastAPI

Workers - Celery or Temporal - Playwright - Apify integration

Database - PostgreSQL

Cache - Redis

Search - OpenSearch or PostgreSQL Full Text

Frontend - Next.js - React - Tailwind

Hosting - AWS

Storage - S3

Analytics - ClickHouse (future)

------------------------------------------------------------------------

# Database Concepts

Events Venues Listings Sellers Platforms Price History Listing Snapshots
Predictions Notifications

Store for every listing: - platform - listing_id - url - seller_id -
title - description - event_id - asking_price - currency - first_seen -
last_seen - active - image hashes

Never overwrite. Store snapshots.

------------------------------------------------------------------------

# AI Components

1.  Event matching Map noisy listing text to a canonical event.

2.  Duplicate detection Detect reposts across groups/platforms.

3.  Scam scoring Signals:

-   account age if public
-   repeated reposting
-   unrealistic price
-   image reuse
-   suspicious language
-   frequent deletions

Return confidence score.

4.  Price prediction

Predict: - likely lowest future price - buy now vs wait

------------------------------------------------------------------------

# User Features

Event page

Display: - lowest price - average price - median - price trend -
listings - scam score - seller score - historical graph - prediction -
inventory count

Search

Alerts

Favorites

Daily email

Push notifications

------------------------------------------------------------------------

# Historical Data

Every crawl: - insert snapshot - never replace previous state

Allows: - price charts - inventory charts - demand prediction - market
reports

------------------------------------------------------------------------

# Crawling Strategy

Never assume Facebook sorts by newest.

Instead: - poll frequently - record first_seen - compare snapshots

Suggested cadence: Upcoming events: hourly

Within 7 days: 15 minutes

Within 48 hours: 5 minutes

------------------------------------------------------------------------

# Monetization

Free - search - current prices

Premium - alerts - prediction - historical analytics - advanced filters

Future: API Organizer analytics

------------------------------------------------------------------------

# Marketing

Launch only Toronto.

SEO: One landing page per event.

Social: TikTok Instagram Reddit Discord

Share: Daily price charts Price drops Market insights

------------------------------------------------------------------------

# Long-term Vision

Become the Bloomberg of secondary ticket markets.

Eventually support: North America Sports Concerts Festivals Comedy
Theatre

The long-term competitive advantage is the proprietary historical ticket
market dataset collected continuously over years.
