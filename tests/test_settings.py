"""UI settings persist to a host file so a fresh Chrome profile can restore them."""

import pytest

import jev_ultrafast.demo as demo


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_missing_file_reads_as_empty(cwd):
    assert demo.load_settings() == {}


def test_settings_round_trip(cwd):
    settings = {
        "location": "Oakland, CA",
        "mode": "rent",
        "minPrice": 0,
        "maxPrice": 3000,
        "requestedType": "studio",
        "daysListed": 7,
        "preference": "near BART",
        "sources": ["craigslist", "zillow"],
        "sort": "default",
        "developer": True,
        "overlays": False,
    }
    demo.save_settings(settings)
    assert demo.load_settings() == settings
    assert (cwd / ".hearth-settings.json").is_file()


def test_corrupt_file_reads_as_empty(cwd):
    (cwd / ".hearth-settings.json").write_text("{not json")
    assert demo.load_settings() == {}


def test_non_object_file_reads_as_empty(cwd):
    (cwd / ".hearth-settings.json").write_text("[1, 2, 3]")
    assert demo.load_settings() == {}


@pytest.mark.parametrize(
    "bad",
    [
        [],  # not a dict
        {"k" * 65: 1},  # key too long
        {"bad key": 1},  # non-alphanumeric key
        {"k": "x" * 2001},  # string too long
        {"k": ["x" * 201]},  # list item too long
        {"k": list("x" * 17)},  # list too long
        {"k": {"nested": 1}},  # unsupported value type
        {str(index): 1 for index in range(33)},  # too many keys
    ],
)
def test_invalid_settings_rejected(cwd, bad):
    with pytest.raises(ValueError):
        demo.save_settings(bad)
    assert demo.load_settings() == {}
