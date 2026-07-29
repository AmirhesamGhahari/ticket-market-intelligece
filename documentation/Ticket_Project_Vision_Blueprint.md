# Ticket Market Intelligence Platform - Vision & Product Blueprint

## Purpose

This document explains the vision of the project. It is intended to give
an AI coding assistant enough context to understand **why** the project
exists before implementing it.

The goal is not simply to build another ticket website.

The goal is to build the world's best **ticket market intelligence
platform**.

Think of it as a combination of:

-   Google Flights (aggregates options)
-   CamelCamelCamel (historical prices)
-   Bloomberg Terminal (market intelligence)
-   Zillow (market trends)
-   but focused on resale tickets.

## The Problem

People buying tickets for concerts, festivals, EDM events and sports
currently search many disconnected places:

-   Facebook Marketplace
-   Facebook Buy & Sell Groups
-   Reddit
-   Discord
-   StubHub
-   Ticketmaster Resale
-   SeatGeek
-   Kijiji
-   others

Each source contains only part of the market.

Users waste time searching multiple places and still cannot answer
simple questions:

-   What is the cheapest ticket right now?
-   Is this a fair price?
-   Is this seller likely legitimate?
-   Should I buy now or wait?
-   Are prices falling?
-   How many tickets are available today versus yesterday?

## Core Product Idea

We do **not** sell tickets.

We continuously discover public ticket listings from many sources,
normalize them into a single database, analyze them and present
insights.

The platform links users back to the original seller.

Our product is information, transparency and analytics.

## Why This Is Valuable

The average user can search Facebook.

The average user cannot understand the entire market.

Our competitive advantage is helping users make better decisions.

Instead of "find tickets", our message is:

**Know the market before you buy.**

## Product Philosophy

The company is a DATA company first.

The website is simply a presentation layer.

Every engineering decision should increase the value of our proprietary
dataset.

Over months and years we will build information that competitors cannot
recreate instantly because they did not collect it over time.

## Initial Scope

Start with Toronto only.

Focus on: - EDM festivals - Music festivals - Concerts - Popular
venues - High-demand local events

After validation expand city by city.

## Data Collection Strategy

Multiple ingestion pipelines collect listings from supported platforms.

Every listing is normalized into one canonical format.

Important: Facebook Marketplace does not reliably sort results by
newest.

Instead of trusting Facebook ordering we repeatedly crawl searches and
store: - first_seen - last_seen - every observed price - every observed
status

This creates our own historical timeline.

## Data Pipeline

Sources → Crawlers → Raw listings → Cleaning → Event matching →
Duplicate detection → Seller analysis → Historical snapshots → Analytics
→ API → Website

## AI Components

-   Match noisy listing titles to official events.
-   Detect duplicate listings across platforms.
-   Estimate scam probability using observable signals.
-   Estimate seller quality.
-   Predict short-term price movement.
-   Recommend buy now vs wait.

## User Experience

Each event page should answer:

-   Lowest available price
-   Average and median prices
-   Price distribution
-   Historical trend
-   Number of active listings
-   Cheapest trusted seller
-   Newly discovered listings
-   Biggest recent price drops
-   AI recommendation
-   Links to original listings

Users can: - search - filter - follow events - receive price alerts -
receive notifications when inventory or prices change.

## Long-Term Vision

Over time the platform becomes the default destination before purchasing
any resale ticket.

Consumers use it for pricing.

Organizers use it for demand insights.

Researchers use it for market trends.

Developers may eventually use an API.

The historical dataset becomes the company's strongest moat.

## Engineering Principles

-   Modular architecture.
-   Source connectors isolated from business logic.
-   Store immutable historical snapshots whenever possible.
-   Design for additional data sources from day one.
-   Every feature should improve the quality of the data asset.
-   Prioritize correctness, observability and scalability over quick
    hacks.

## Success Definition

Success is not measured by the number of listings collected.

Success means users trust the platform enough that, before buying any
resale ticket, their first step is checking our website to understand
the market.
