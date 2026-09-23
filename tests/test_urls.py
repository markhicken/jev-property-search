"""Offline contracts for building marketplace start URLs from a user's location and mode.

No network calls: Redfin's autocomplete lookup is always exercised through an injected
fake `fetch`, never live HTTP.
"""

import pytest

from jev_ultrafast.urls import (
    build_start_url,
    resolve_craigslist_region,
    resolve_redfin_city_path,
    slugify,
    split_location,
)

# Facebook Marketplace has no public location-slug URL (see build_start_url); it always
# follows the signed-in account's own location, so it is excluded from location-varies checks.
LOCATION_AWARE_SOURCES = ["craigslist", "redfin", "zillow"]


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("unexpected error response")


def fake_redfin_fetch(url, *, params, timeout, headers=None, city_path="/city/30749/TX/Austin"):
    body = f'{{}}&&{{"payload": {{"sections": [{{"rows": [{{"url": "{city_path}"}}]}}]}}}}'
    return FakeResponse(body)


def failing_fetch(url, *, params, timeout, headers=None):
    raise AssertionError("network should never be reached in offline tests without an explicit fake")


def test_slugify_normalizes_punctuation_and_case():
    assert slugify("San Francisco, CA") == "san-francisco-ca"
    assert slugify("  Austin,   TX  ") == "austin-tx"


def test_split_location_parses_city_and_state():
    assert split_location("San Francisco, CA") == ("San Francisco", "CA")
    assert split_location("Austin, Texas") == ("Austin", "TX")
    assert split_location("Chicago") == ("Chicago", None)
    assert split_location("") == ("", None)


def test_resolve_craigslist_region_matches_known_metro():
    assert resolve_craigslist_region("Austin", "TX") == ("austin", True)
    assert resolve_craigslist_region("San Francisco", "CA") == ("sfbay", True)


def test_resolve_craigslist_region_falls_back_for_unknown_city():
    region, matched = resolve_craigslist_region("Nowheresville", "ZZ")
    assert matched is False
    assert region == "www"


def test_resolve_redfin_city_path_uses_injected_fetch_only():
    path = resolve_redfin_city_path("Austin, TX", fetch=lambda *a, **k: fake_redfin_fetch(*a, **k))
    assert path == "/city/30749/TX/Austin"


def test_resolve_redfin_city_path_returns_none_on_failure():
    def broken_fetch(*args, **kwargs):
        raise OSError("network unreachable")

    assert resolve_redfin_city_path("Austin, TX", fetch=broken_fetch) is None


@pytest.mark.parametrize("source", LOCATION_AWARE_SOURCES)
@pytest.mark.parametrize("mode", ["rent", "buy"])
def test_build_start_url_uses_the_requested_location(source, mode, monkeypatch):
    if source == "redfin":
        monkeypatch.setattr(
            "jev_ultrafast.urls.resolve_redfin_city_path",
            lambda location, **kwargs: "/city/17151/CA/San-Francisco" if "San Francisco" in location
            else "/city/30749/TX/Austin",
        )
    sf_url = build_start_url(source, "San Francisco, CA", mode).url
    austin_url = build_start_url(source, "Austin, TX", mode).url
    assert sf_url != austin_url, f"{source}/{mode} did not vary with location"


def test_build_start_url_zillow_distinguishes_rent_and_buy():
    rent = build_start_url("zillow", "Austin, TX", "rent").url
    buy = build_start_url("zillow", "Austin, TX", "buy").url
    assert rent != buy
    assert "rentals" in rent
    assert "rentals" not in buy


def test_build_start_url_craigslist_distinguishes_rent_and_buy():
    rent = build_start_url("craigslist", "Austin, TX", "rent").url
    buy = build_start_url("craigslist", "Austin, TX", "buy").url
    assert "cat=apa" in rent
    assert "cat=rea" in buy


def test_build_start_url_craigslist_no_lat_lon_radius_leftovers():
    url = build_start_url("craigslist", "San Francisco, CA", "rent").url
    assert "lat=" not in url
    assert "lon=" not in url
    assert "radius=" not in url


def test_build_start_url_redfin_falls_back_when_lookup_fails(monkeypatch):
    monkeypatch.setattr("jev_ultrafast.urls.resolve_redfin_city_path", lambda location, **kwargs: None)
    result = build_start_url("redfin", "Somewhere Obscure", "rent")
    assert result.needs_manual_region is True
    assert result.url == "https://www.redfin.com/"


def test_build_start_url_marketplace_switches_category_but_not_location():
    # Documented limitation: Facebook has no public location-slug URL, so it always relies
    # on the signed-in account's own location; only the rent/buy category can be controlled.
    rent = build_start_url("marketplace", "Austin, TX", "rent")
    buy = build_start_url("marketplace", "Austin, TX", "buy")
    assert "propertyrentals" in rent.url
    assert "propertyforsale" in buy.url
    assert rent.needs_manual_region is True
    assert build_start_url("marketplace", "San Francisco, CA", "rent").url == rent.url


def test_build_start_url_craigslist_nearby_scope_adds_flag():
    metro = build_start_url("craigslist", "Austin, TX", "rent", "metro").url
    nearby = build_start_url("craigslist", "Austin, TX", "rent", "nearby").url
    # A Craigslist region is already metro-wide, so city and metro produce the same URL.
    city = build_start_url("craigslist", "Austin, TX", "rent", "city").url
    assert "searchNearby=1" not in metro
    assert "searchNearby=1" not in city
    assert metro == city
    assert "searchNearby=1" in nearby


def test_build_start_url_scope_defaults_to_metro_when_missing_or_unknown():
    default = build_start_url("craigslist", "Austin, TX", "rent").url
    metro = build_start_url("craigslist", "Austin, TX", "rent", "metro").url
    bogus = build_start_url("craigslist", "Austin, TX", "rent", "galaxy").url
    assert default == metro == bogus


def test_build_start_url_rejects_unknown_source():
    with pytest.raises(ValueError):
        build_start_url("bogus", "Austin, TX", "rent")
