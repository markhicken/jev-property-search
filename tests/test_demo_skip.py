"""A source whose start URL can't be pointed at the requested location is skipped, not
opened at its default region. Craigslist and Redfin encode the area in the URL, so an
unresolved location must raise SourceLocationUnavailable instead of silently searching
the site's home region (the reported "searched Boise for a Lincoln City request" bug).

No browser or network: Agent is replaced with a stub and Redfin's lookup is monkeypatched.
"""

import pytest

import jev_ultrafast.demo as demo


class StubAgent:
    """Stands in for the real browser agent so a non-skipped source can be constructed
    without launching Chrome. Its existence in a test asserts the source was NOT skipped."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.state = {}

    def snapshot(self):
        return {"page": None, "status": "idle", "history": [], "decision": None}

    def close(self):
        pass


@pytest.fixture(autouse=True)
def stub_environment(monkeypatch):
    monkeypatch.setattr(demo, "Agent", StubAgent)
    monkeypatch.setattr(demo, "AGENT", None, raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")


def reset_body(scenario, location):
    return {
        "scenario": scenario,
        "location": location,
        "goal": "Search for a house.",
        "mode": "buy",
        "scope": "nearby",
        # A non-empty text_values dict removes the TEXT_MODEL_API_KEY requirement.
        "text_values": {"location": {"value": location, "description": "The requested city."}},
    }


def test_craigslist_skips_when_region_is_unresolved(monkeypatch):
    # An unlisted place that also can't be geocoded has no reasonable region, so it is skipped.
    monkeypatch.setattr("jev_ultrafast.urls.geocode_location", lambda location, **kwargs: None)
    with pytest.raises(demo.SourceLocationUnavailable) as excinfo:
        demo.command("reset", reset_body("craigslist", "Nowheresville, ZZ"))
    assert "Nowheresville, ZZ" in str(excinfo.value)
    assert "Craigslist" in str(excinfo.value)


def test_craigslist_proceeds_via_nearest_region_when_unlisted(monkeypatch):
    # An unlisted coastal Oregon town geocodes near the oregoncoast site, so it opens there
    # instead of being skipped — the "use the closest match" behavior.
    monkeypatch.setattr("jev_ultrafast.urls.geocode_location", lambda location, **kwargs: (44.81, -124.06))
    demo.command("reset", reset_body("craigslist", "Depoe Bay, OR"))
    assert isinstance(demo.AGENT, StubAgent)
    assert "craigslist.org/search/area/oregoncoast" in demo.AGENT.args[0]


def test_redfin_skips_when_lookup_fails(monkeypatch):
    monkeypatch.setattr("jev_ultrafast.urls.resolve_redfin_city_path", lambda location, **kwargs: None)
    with pytest.raises(demo.SourceLocationUnavailable):
        demo.command("reset", reset_body("redfin", "Lincoln City, OR"))


def test_craigslist_proceeds_for_a_known_region():
    # A resolvable region opens normally: no skip, and the real start URL is handed to the agent.
    demo.command("reset", reset_body("craigslist", "Austin, TX"))
    assert isinstance(demo.AGENT, StubAgent)
    assert "craigslist.org/search/area/austin" in demo.AGENT.args[0]


def test_marketplace_is_never_pre_skipped():
    # Facebook Marketplace can't encode a location in its URL and is steered by the agent,
    # so it always opens rather than being skipped for an unresolved area.
    demo.command("reset", reset_body("marketplace", "Lincoln City, OR"))
    assert isinstance(demo.AGENT, StubAgent)


def test_zillow_is_never_pre_skipped():
    # Zillow embeds the location in its slug, so it always targets the requested place.
    demo.command("reset", reset_body("zillow", "Lincoln City, OR"))
    assert isinstance(demo.AGENT, StubAgent)
    assert "lincoln-city-or" in demo.AGENT.args[0]
