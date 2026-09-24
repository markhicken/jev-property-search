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
from math import asin, cos, radians, sin, sqrt

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

# Craigslist's ~420 regions are a fixed list. This maps a curated set of US cities to a
# (region code, latitude, longitude) so a request can either match a city by name or, when
# it doesn't, fall back to the geographically nearest known region (see
# resolve_craigslist_region). "sfbay" covers the whole Bay Area, including Oakland, San Jose,
# and Berkeley, so those map to the same region. Coordinates are approximate city centroids;
# only their relative distance matters, since regions sit far apart.
CRAIGSLIST_REGIONS: dict[tuple[str, str], tuple[str, float, float]] = {
    ("san francisco", "CA"): ("sfbay", 37.77, -122.42), ("oakland", "CA"): ("sfbay", 37.80, -122.27),
    ("san jose", "CA"): ("sfbay", 37.34, -121.89), ("berkeley", "CA"): ("sfbay", 37.87, -122.27),
    ("los angeles", "CA"): ("losangeles", 34.05, -118.24), ("san diego", "CA"): ("sandiego", 32.72, -117.16),
    ("sacramento", "CA"): ("sacramento", 38.58, -121.49), ("fresno", "CA"): ("fresno", 36.74, -119.77),
    ("bakersfield", "CA"): ("bakersfield", 35.37, -119.02), ("santa barbara", "CA"): ("santabarbara", 34.42, -119.70),
    ("monterey", "CA"): ("monterey", 36.60, -121.89), ("palm springs", "CA"): ("palmsprings", 33.83, -116.54),
    ("redding", "CA"): ("redding", 40.59, -122.39), ("chico", "CA"): ("chico", 39.73, -121.84),
    ("seattle", "WA"): ("seattle", 47.61, -122.33), ("spokane", "WA"): ("spokane", 47.66, -117.43),
    ("olympia", "WA"): ("olympia", 47.04, -122.90), ("bellingham", "WA"): ("bellingham", 48.75, -122.48),
    ("portland", "OR"): ("portland", 45.52, -122.68), ("salem", "OR"): ("salem", 44.94, -123.04),
    ("eugene", "OR"): ("eugene", 44.05, -123.09), ("corvallis", "OR"): ("corvallis", 44.56, -123.26),
    ("medford", "OR"): ("medford", 42.33, -122.87), ("bend", "OR"): ("bend", 44.06, -121.31),
    ("lincoln city", "OR"): ("oregoncoast", 44.96, -124.02), ("newport", "OR"): ("oregoncoast", 44.64, -124.05),
    ("reno", "NV"): ("reno", 39.53, -119.81),
    ("new york", "NY"): ("newyork", 40.71, -74.01), ("brooklyn", "NY"): ("newyork", 40.65, -73.95),
    ("buffalo", "NY"): ("buffalo", 42.89, -78.88), ("rochester", "NY"): ("rochester", 43.16, -77.61),
    ("boston", "MA"): ("boston", 42.36, -71.06), ("chicago", "IL"): ("chicago", 41.88, -87.63),
    ("denver", "CO"): ("denver", 39.74, -104.99), ("austin", "TX"): ("austin", 30.27, -97.74),
    ("dallas", "TX"): ("dallas", 32.78, -96.80), ("houston", "TX"): ("houston", 29.76, -95.37),
    ("san antonio", "TX"): ("sanantonio", 29.42, -98.49), ("phoenix", "AZ"): ("phoenix", 33.45, -112.07),
    ("tucson", "AZ"): ("tucson", 32.22, -110.97), ("las vegas", "NV"): ("lasvegas", 36.17, -115.14),
    ("miami", "FL"): ("miami", 25.76, -80.19), ("orlando", "FL"): ("orlando", 28.54, -81.38),
    ("tampa", "FL"): ("tampa", 27.95, -82.46), ("jacksonville", "FL"): ("jacksonville", 30.33, -81.66),
    ("atlanta", "GA"): ("atlanta", 33.75, -84.39), ("nashville", "TN"): ("nashville", 36.16, -86.78),
    ("memphis", "TN"): ("memphis", 35.15, -90.05), ("philadelphia", "PA"): ("philadelphia", 39.95, -75.17),
    ("pittsburgh", "PA"): ("pittsburgh", 40.44, -79.996), ("washington", "DC"): ("washingtondc", 38.90, -77.04),
    ("baltimore", "MD"): ("baltimore", 39.29, -76.61), ("minneapolis", "MN"): ("minneapolis", 44.98, -93.27),
    ("detroit", "MI"): ("detroit", 42.33, -83.05), ("columbus", "OH"): ("columbus", 39.96, -83.00),
    ("cleveland", "OH"): ("cleveland", 41.50, -81.69), ("cincinnati", "OH"): ("cincinnati", 39.10, -84.51),
    ("charlotte", "NC"): ("charlotte", 35.23, -80.84), ("raleigh", "NC"): ("raleigh", 35.78, -78.64),
    ("new orleans", "LA"): ("neworleans", 29.95, -90.07), ("kansas city", "MO"): ("kansascity", 39.10, -94.58),
    ("st louis", "MO"): ("stlouis", 38.63, -90.20), ("saint louis", "MO"): ("stlouis", 38.63, -90.20),
    ("indianapolis", "IN"): ("indianapolis", 39.77, -86.16), ("milwaukee", "WI"): ("milwaukee", 43.04, -87.91),
    ("salt lake city", "UT"): ("saltlakecity", 40.76, -111.89), ("albuquerque", "NM"): ("albuquerque", 35.08, -106.65),
    ("oklahoma city", "OK"): ("oklahomacity", 35.47, -97.52), ("louisville", "KY"): ("louisville", 38.25, -85.76),
    ("richmond", "VA"): ("richmond", 37.54, -77.44), ("virginia beach", "VA"): ("hamptonroads", 36.85, -75.98),
    ("honolulu", "HI"): ("honolulu", 21.31, -157.86), ("boise", "ID"): ("boise", 43.62, -116.21),
    ("omaha", "NE"): ("omaha", 41.26, -95.93), ("providence", "RI"): ("providence", 41.82, -71.41),
    ("hartford", "CT"): ("hartford", 41.76, -72.67),
}

# Beyond this straight-line distance from every known region, a request is treated as having
# no reasonable Craigslist site rather than being forced onto a far-away metro.
MAX_CRAIGSLIST_KM = 500.0
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

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


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = (radians(v) for v in (a[0], a[1], b[0], b[1]))
    inner = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(inner))


def geocode_location(location: str, *, fetch=httpx.get) -> tuple[float, float] | None:
    """Resolve a US place name to (lat, lon) via OpenStreetMap's Nominatim. Returns None on
    any failure so callers can fall back. Nominatim asks for a descriptive User-Agent."""
    try:
        response = fetch(
            NOMINATIM_URL,
            params={"q": location, "format": "json", "limit": 1, "countrycodes": "us"},
            timeout=4.0,
            headers={"User-Agent": "jev-property-search/1.0 (personal rental search)"},
        )
        response.raise_for_status()
        data = response.json()
        return float(data[0]["lat"]), float(data[0]["lon"])
    except (httpx.HTTPError, OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def resolve_craigslist_region(city: str, state: str | None, *, geocode=None) -> tuple[str, bool]:
    """Return (region, matched). Matches a known city by name, else falls back to the nearest
    known region by geocoding the request. Only when geocoding fails or every region is beyond
    MAX_CRAIGSLIST_KM does it return Craigslist's geo-redirecting site, unmatched."""
    key_city = re.sub(r"[^a-z ]", "", city.strip().lower())
    if state and (entry := CRAIGSLIST_REGIONS.get((key_city, state))):
        return entry[0], True
    # A city name unique across the curated table is still a safe match without its state.
    matches = {entry[0] for (candidate_city, _), entry in CRAIGSLIST_REGIONS.items() if candidate_city == key_city}
    if len(matches) == 1:
        return next(iter(matches)), True
    # No name match: point the request at the geographically nearest known region.
    locate = geocode or geocode_location
    coords = locate(f"{city}, {state}" if state else city)
    if coords:
        region, distance = min(
            ((entry[0], haversine_km(coords, (entry[1], entry[2]))) for entry in CRAIGSLIST_REGIONS.values()),
            key=lambda pair: pair[1],
        )
        if distance <= MAX_CRAIGSLIST_KM:
            return region, True
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
