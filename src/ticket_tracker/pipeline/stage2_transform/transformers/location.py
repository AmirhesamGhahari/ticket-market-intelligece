"""Parse location strings and map cities to GTA regions.

Input format from Facebook/Apify: "City, Province"  e.g. "Toronto, ON"
"""

from __future__ import annotations

from typing import NamedTuple

# Maps lowercase city names to GTA region buckets.
_GTA_REGION_MAP: dict[str, str] = {
    # Toronto proper
    "toronto": "Toronto",
    "north york": "Toronto",
    "scarborough": "Toronto",
    "etobicoke": "Toronto",
    "york": "Toronto",
    "east york": "Toronto",
    # West GTA
    "mississauga": "West GTA",
    "brampton": "West GTA",
    "oakville": "West GTA",
    "burlington": "West GTA",
    "halton hills": "West GTA",
    "milton": "West GTA",
    # North GTA
    "richmond hill": "North GTA",
    "markham": "North GTA",
    "vaughan": "North GTA",
    "thornhill": "North GTA",
    "woodbridge": "North GTA",
    "aurora": "North GTA",
    "newmarket": "North GTA",
    "king city": "North GTA",
    # East GTA
    "pickering": "East GTA",
    "ajax": "East GTA",
    "whitby": "East GTA",
    "oshawa": "East GTA",
    "clarington": "East GTA",
    "bowmanville": "East GTA",
    "durham": "East GTA",
    # Outside GTA
    "hamilton": "Outside GTA",
    "niagara falls": "Outside GTA",
    "st. catharines": "Outside GTA",
    "st catharines": "Outside GTA",
    "guelph": "Outside GTA",
    "kitchener": "Outside GTA",
    "waterloo": "Outside GTA",
    "cambridge": "Outside GTA",
    "barrie": "Outside GTA",
    "kingston": "Outside GTA",
    "london": "Outside GTA",
    "windsor": "Outside GTA",
    "ottawa": "Outside GTA",
}


class LocationResult(NamedTuple):
    location_city: str | None
    location_province: str | None
    location_region: str | None


def transform(location_raw: str | None) -> LocationResult:
    """Parse "City, Province" into structured location fields."""
    if not location_raw or not location_raw.strip():
        return LocationResult(None, None, None)

    parts = location_raw.split(",", maxsplit=1)
    city = parts[0].strip() if parts else None
    province = parts[1].strip() if len(parts) > 1 else None

    region = _GTA_REGION_MAP.get((city or "").lower(), "Unknown")

    return LocationResult(
        location_city=city or None,
        location_province=province or None,
        location_region=region,
    )
