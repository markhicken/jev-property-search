"""Build a marketplace start URL from the user's actual location and rent/buy mode.

Each of the four marketplaces used to always open a URL hardcoded to San Francisco,
regardless of what the user searched for. This module builds the start URL per
request instead, so "which city" and "rent or buy" are just inputs to one function
rather than baked-in literals.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

STATE_ABBREVIATIONS = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY", "district of columbia": "DC",
}

# Craigslist's ~420 regions are a fixed list; this covers the largest US metros by a
# curated (city, state) -> region code lookup. "sfbay" covers the whole Bay Area,
# including Oakland, San Jose, and Berkeley, so those map to the same region.
CRAIGSLIST_REGIONS: dict[tuple[str, str], str] = {
    ("san francisco", "CA"): "sfbay", ("oakland", "CA"): "sfbay", ("san jose", "CA"): "sfbay",
    ("berkeley", "CA"): "sfbay", ("los angeles", "CA"): "losangeles", ("san diego", "CA"): "sandiego",
    ("sacramento", "CA"): "sacramento", ("fresno", "CA"): "fresno", ("seattle", "WA"): "seattle",
    ("portland", "OR"): "portland", ("new york", "NY"): "newyork", ("brooklyn", "NY"): "newyork",
    ("buffalo", "NY"): "buffalo", ("rochester", "NY"): "rochester", ("boston", "MA"): "boston",
    ("chicago", "IL"): "chicago", ("denver", "CO"): "denver", ("austin", "TX"): "austin",
    ("dallas", "TX"): "dallas", ("houston", "TX"): "houston", ("san antonio", "TX"): "sanantonio",
    ("phoenix", "AZ"): "phoenix", ("tucson", "AZ"): "tucson", ("las vegas", "NV"): "lasvegas",
    ("miami", "FL"): "miami", ("orlando", "FL"): "orlando", ("tampa", "FL"): "tampa",
    ("jacksonville", "FL"): "jacksonville", ("atlanta", "GA"): "atlanta", ("nashville", "TN"): "nashville",
    ("memphis", "TN"): "memphis", ("philadelphia", "PA"): "philadelphia", ("pittsburgh", "PA"): "pittsburgh",
    ("washington", "DC"): "washingtondc", ("baltimore", "MD"): "baltimore", ("minneapolis", "MN"): "minneapolis",
    ("detroit", "MI"): "detroit", ("columbus", "OH"): "columbus", ("cleveland", "OH"): "cleveland",
    ("cincinnati", "OH"): "cincinnati", ("charlotte", "NC"): "charlotte", ("raleigh", "NC"): "raleigh",
    ("new orleans", "LA"): "neworleans", ("kansas city", "MO"): "kansascity", ("st louis", "MO"): "stlouis",
    ("saint louis", "MO"): "stlouis", ("indianapolis", "IN"): "indianapolis", ("milwaukee", "WI"): "milwaukee",
    ("salt lake city", "UT"): "saltlakecity", ("albuquerque", "NM"): "albuquerque",
    ("oklahoma city", "OK"): "oklahomacity", ("louisville", "KY"): "louisville", ("richmond", "VA"): "richmond",
    ("virginia beach", "VA"): "hamptonroads", ("honolulu", "HI"): "honolulu", ("boise", "ID"): "boise",
    ("omaha", "NE"): "omaha", ("providence", "RI"): "providence", ("hartford", "CT"): "hartford",
}

REDFIN_AUTOCOMPLETE_URL = "https://www.redfin.com/stingray/do/location-autocomplete"


def slugify(text: str) -> str:
    """Normalize a location string to a URL slug, e.g. "San Francisco, CA" -> "san-francisco-ca"."""
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")


def split_location(raw: str) -> tuple[str, str | None]:
    """Parse "City, ST" / "City, State" / bare "City" into (city, state_abbr | None)."""
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        return "", None
    city = parts[0]
    if len(parts) < 2:
        return city, None
    state_raw = parts[1].strip().lower()
    if len(state_raw) == 2:
        return city, state_raw.upper()
    return city, STATE_ABBREVIATIONS.get(state_raw)


def resolve_craigslist_region(city: str, state: str | None) -> tuple[str, bool]:
    """Return (region, matched). Falls back to Craigslist's own geo-redirecting site if unmatched."""
    key_city = re.sub(r"[^a-z ]", "", city.strip().lower())
    if state and (region := CRAIGSLIST_REGIONS.get((key_city, state))):
        return region, True
    # A city name unique across the curated table is still a safe match without its state.
    matches = {region for (candidate_city, _), region in CRAIGSLIST_REGIONS.items() if candidate_city == key_city}
    if len(matches) == 1:
        return next(iter(matches)), True
    return "www", False


def resolve_redfin_city_path(location: str, *, fetch=httpx.get) -> str | None:
    """Resolve a location to Redfin's opaque `/city/<id>/<ST>/<Name>` path via Redfin's own
    public autocomplete endpoint. Returns None on any failure so callers can fall back."""
    try:
        response = fetch(
            REDFIN_AUTOCOMPLETE_URL,
            params={"location": location, "v": 2},
            timeout=3.0,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        text = response.text
        if text.startswith("{}&&"):
            text = text[4:]
        data = json.loads(text)
    except (httpx.HTTPError, OSError, ValueError, AttributeError):
        return None
    for section in data.get("payload", {}).get("sections", []):
        for row in section.get("rows", []):
            url = row.get("url")
            if url and url.startswith("/city/"):
                return url
    return None


@dataclass(frozen=True)
class StartUrl:
    url: str
    needs_manual_region: bool = False


VALID_SCOPES = frozenset({"city", "metro", "nearby"})


def build_start_url(source: str, location: str, mode: str = "rent", scope: str = "metro") -> StartUrl:
    """Build the marketplace URL to open first, for the user's actual location, mode and scope.

    `scope` widens how far the search reaches: "city" stays inside city limits, "metro"
    covers the surrounding metro area, and "nearby" also pulls in adjacent regions. Only the
    parts a site's own URL can express deterministically are set here — Craigslist regions are
    already metro-wide, so only its "nearby" flag is URL-controlled; broadening Zillow and
    Redfin beyond their city page is left to the agent, which widens the map in the site's UI.
    """
    location = (location or "").strip() or "San Francisco, CA"
    scope = scope if scope in VALID_SCOPES else "metro"
    city, state = split_location(location)
    slug = slugify(location)
    buy = mode == "buy"

    if source == "zillow":
        # Rentals live under an explicit /rentals/ suffix; the bare city page is Zillow's
        # own default "homes for sale" search, so buy mode simply drops the suffix.
        return StartUrl(f"https://www.zillow.com/{slug}/rentals/" if not buy else f"https://www.zillow.com/{slug}/")

    if source == "redfin":
        city_path = resolve_redfin_city_path(location)
        if not city_path:
            return StartUrl("https://www.redfin.com/", needs_manual_region=True)
        # As with Zillow, the bare city page is Redfin's own "homes for sale" default.
        return StartUrl(f"https://www.redfin.com{city_path}/apartments-for-rent" if not buy
                         else f"https://www.redfin.com{city_path}")

    if source == "craigslist":
        region, matched = resolve_craigslist_region(city, state)
        # Verified against craigslist.org: "apa" is rentals, "rea" is real estate for sale.
        category = "rea" if buy else "apa"
        # A Craigslist region already spans the whole metro, so only "nearby" widens the URL,
        # pulling in adjacent Craigslist sites via its own searchNearby flag.
        nearby = "&searchNearby=1" if scope == "nearby" else ""
        return StartUrl(f"https://www.craigslist.org/search/area/{region}?cat={category}{nearby}",
                         needs_manual_region=not matched)

    if source == "marketplace":
        # Facebook Marketplace has no public location-slug URL; it always follows the
        # signed-in account's own location, same limitation as before this change.
        category = "propertyforsale" if buy else "propertyrentals"
        return StartUrl(f"https://www.facebook.com/marketplace/category/{category}/", needs_manual_region=True)

    raise ValueError(f"Unknown marketplace source: {source!r}")
