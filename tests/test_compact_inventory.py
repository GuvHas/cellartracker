"""P1-2: a compact inventory view, opt-in and pre-rendered.

The endpoint serves all 66 columns of every bottle - 1.56 MB at 1,000 bottles -
while the dashboard reads seven of them. It is also a public surface that users
consume from their own Lovelace cards, so narrowing it in place would break
them silently.

``?view=compact`` is therefore additive: the default response is unchanged, and
a caller that wants less asks for less.

A *named* projection rather than an arbitrary ``?fields=`` list, because the
body has to be rendered ahead of the request. Arbitrary field sets would mean
encoding per request, which is exactly the event-loop blocking P0-2 removed.
Both bodies are built in the executor that already runs the parse.

What this does not do: reduce what the coordinator retains. That would mean
discarding columns at parse time, which is destructive and would break both
diagnostics and any caller of the full endpoint. Response size is the half that
can be fixed without consent.
"""

from __future__ import annotations

import asyncio
import json

from cellar_tracker.cellar_data import WineCellarData
from cellar_tracker.const import COMPACT_FIELDS, DOMAIN
from cellar_tracker.views import CellarTrackerInventoryView
from conftest import ConfigEntry, FakeHass, FakeRequest, FakeSession, ViewHass

NAMED = ["iWine", "Wine", "Vintage", "Valuation", "Location", "Bin", "Barcode",
         "BeginConsume", "EndConsume", "Producer", "Country", "Region",
         "Varietal", "Size", "Notes"]
VALUES = ["1", "Barolo", "2016", "45.50", "Rack", "A", "7350012345678",
          "2022", "2035",
          "Giacosa", "Italy", "Piedmont", "Nebbiolo", "750ml",
          "a long tasting note that nobody reading a bottle table needs"]

# The real export carries 66 columns. A fixture with only the interesting ones
# would understate the saving and make the size assertion meaningless.
FILLER = [f"Extra{i}" for i in range(52)]

HEADER = "\t".join(NAMED + FILLER)
ROW = "\t".join(VALUES + [f"value {i}" for i in range(52)])
EXPORT = "\n".join([HEADER, ROW])


def coordinator() -> WineCellarData:
    hass = FakeHass()
    hass.session = FakeSession(text=EXPORT)
    coord = WineCellarData(hass, ConfigEntry(data={"username": "a", "password": "b"}))
    coord.data = asyncio.run(coord._async_update_data())
    return coord


def served(view_param=None):
    coord = coordinator()
    hass = ViewHass({DOMAIN: {"a": coord}})
    query = {"view": view_param} if view_param is not None else {}
    response = asyncio.run(CellarTrackerInventoryView(hass).get(FakeRequest(**query)))
    return coord, response


def test_the_default_response_is_unchanged():
    """Any existing card must keep getting everything it got before."""
    coord, response = served()
    assert json.loads(response.body) == coord.data["bottles"]
    assert "Producer" in json.loads(response.body)[0]


def test_the_compact_view_carries_only_the_named_fields():
    _, response = served("compact")
    bottle = json.loads(response.body)[0]
    assert set(bottle) == set(COMPACT_FIELDS)


def test_the_compact_view_keeps_what_the_dashboard_renders():
    _, response = served("compact")
    bottle = json.loads(response.body)[0]
    for field in ("Wine", "Vintage", "Valuation", "BeginConsume", "EndConsume"):
        assert field in bottle, f"the dashboard renders {field}"
    assert bottle["Wine"] == "Barolo"
    assert bottle["Valuation"] == 45.50


def test_the_compact_view_is_substantially_smaller():
    coord, compact = served("compact")
    assert len(compact.body) < len(coord.inventory_body) / 2


def test_the_compact_body_is_pre_rendered_too():
    """Identity: serving it must not re-encode on the event loop."""
    coord = coordinator()
    hass = ViewHass({DOMAIN: {"a": coord}})
    response = asyncio.run(
        CellarTrackerInventoryView(hass).get(FakeRequest(view="compact"))
    )
    assert response.body is coord.compact_body


def test_an_unknown_view_falls_back_to_the_full_payload():
    """A typo must not silently hand back fewer fields than were asked for."""
    coord, response = served("kompakt")
    assert response.body == coord.inventory_body


def test_a_missing_field_is_simply_absent_rather_than_an_error():
    """Not every export carries every column."""
    hass = FakeHass()
    hass.session = FakeSession(text="iWine\tWine\tValuation\n1\tBarolo\t45.50")
    coord = WineCellarData(hass, ConfigEntry(data={"username": "a", "password": "b"}))
    coord.data = asyncio.run(coord._async_update_data())

    bottle = json.loads(coord.compact_body)[0]
    assert bottle["Wine"] == "Barolo"
    assert "Vintage" not in bottle


def test_an_empty_cellar_compacts_to_an_empty_list():
    hass = ViewHass({})
    response = asyncio.run(
        CellarTrackerInventoryView(hass).get(FakeRequest(view="compact"))
    )
    assert json.loads(response.body) == []


def test_the_dashboard_asks_for_the_compact_view():
    """Otherwise the saving exists but nothing uses it."""
    import pathlib

    page = (
        pathlib.Path(__file__).resolve().parent.parent
        / "custom_components"
        / "cellar_tracker"
        / "www"
        / "cellar.html"
    ).read_text()
    assert "'view', 'compact'" in page, (
        "the page must request the compact projection"
    )


# --------------------------------------------------------------------------
# The page and the projection have to agree on which fields exist
# --------------------------------------------------------------------------
def test_every_field_the_page_searches_is_actually_served():
    """Otherwise a search field is dead code that tests can still satisfy.

    The dashboard's own tests hand it whatever row they like, so a field the
    compact projection never sends looks searchable in the suite and is always
    blank in a real cellar. This reads the field list out of the page itself.
    """
    import pathlib
    import re

    page = (
        pathlib.Path(__file__).resolve().parent.parent
        / "custom_components"
        / "cellar_tracker"
        / "www"
        / "cellar.html"
    ).read_text()

    declared = re.search(r"const SEARCH_FIELDS = \[(.*?)\];", page, re.S)
    assert declared, "cellar.html no longer declares SEARCH_FIELDS"
    fields = re.findall(r"'([^']+)'", declared.group(1))
    assert fields, "SEARCH_FIELDS parsed as empty"

    missing = [field for field in fields if field not in COMPACT_FIELDS]
    assert not missing, (
        f"the page searches {missing}, which the compact view never sends"
    )
