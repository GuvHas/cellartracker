"""P0-2: the inventory endpoint must not serialise JSON on the event loop.

``web.json_response(bottles)`` calls ``json.dumps`` synchronously inside the
request handler, so every millisecond it spends is a millisecond nothing else
in Home Assistant runs. The cost scales with the cellar, and the dashboard hits
this endpoint on every page load. Measured on a developer-class x86 core:
3.3 ms at 200 bottles, 13.8 ms at 1,000, 43.9 ms at 2,500 - and a Raspberry Pi,
which is what a large share of installations run on, is several times slower.

The parse already runs in an executor. Rendering the body there too costs
nothing extra and leaves the view handing over bytes it never has to touch.

The response must stay byte-identical to what json_response produced, because
the dashboard and any user-built Lovelace card are consuming it.
"""

from __future__ import annotations

import asyncio
import json

from cellar_tracker.cellar_data import WineCellarData
from cellar_tracker.const import DOMAIN
from cellar_tracker.views import CellarTrackerInventoryView
from conftest import ConfigEntry, FakeHass, FakeRequest, FakeSession, ViewHass

HEADER = "iWine\tWine\tVintage\tValuation\tLocation\tBin"
EXPORT = "\n".join(
    [
        HEADER,
        "1\tBarolo\t2016\t45.50\tRack\tA",
        "2\tRioja\t2018\t22.00\tRack\tB",
    ]
)


def refreshed_coordinator(export: str = EXPORT) -> WineCellarData:
    """A coordinator that has completed one real parse of `export`."""
    hass = FakeHass()
    hass.session = FakeSession(text=export)
    entry = ConfigEntry(data={"username": "alice", "password": "s3cret"})
    coordinator = WineCellarData(hass, entry)
    coordinator.data = asyncio.run(coordinator._async_update_data())
    return coordinator


def get(view, **query):
    return asyncio.run(view.get(FakeRequest(**query)))


def test_the_coordinator_pre_renders_the_inventory_body():
    coordinator = refreshed_coordinator()
    body = coordinator.inventory_body
    assert isinstance(body, bytes), "the body must be rendered ahead of the request"
    assert json.loads(body) == coordinator.data["bottles"]


def test_the_view_serves_the_pre_rendered_body():
    coordinator = refreshed_coordinator()
    hass = ViewHass({DOMAIN: {"a": coordinator}})
    response = get(CellarTrackerInventoryView(hass))

    assert response.status == 200
    assert response.content_type == "application/json"
    assert response.body == coordinator.inventory_body


def test_the_view_does_no_encoding_of_its_own():
    """The whole point: nothing is serialised while handling the request.

    Asserted by object identity rather than by patching ``json.dumps``, which
    would prove nothing: ``web.json_response`` binds its encoder as a default
    argument at definition time, so patching the module attribute afterwards
    never intercepts it. Handing back the very same bytes object cannot be
    faked by re-encoding - an equal value would be a different object.
    """
    coordinator = refreshed_coordinator()
    hass = ViewHass({DOMAIN: {"a": coordinator}})
    response = get(CellarTrackerInventoryView(hass))

    assert response.body is coordinator.inventory_body, (
        "the view built its own body instead of serving the pre-rendered one"
    )


def test_the_payload_is_unchanged_from_the_previous_release():
    """A dashboard or user card consuming this endpoint must not break."""
    coordinator = refreshed_coordinator()
    hass = ViewHass({DOMAIN: {"a": coordinator}})
    served = json.loads(get(CellarTrackerInventoryView(hass)).body)

    assert [b["Wine"] for b in served] == ["Barolo", "Rioja"]
    assert served[0]["Valuation"] == 45.50
    assert all("unique_bottle_id" in b for b in served)


def test_an_empty_cellar_still_answers_with_an_empty_list():
    coordinator = refreshed_coordinator()
    coordinator.data = {"total_bottles": 0, "total_value": 0.0, "bottles": []}
    coordinator._inventory_body = b"[]"
    hass = ViewHass({DOMAIN: {"a": coordinator}})

    assert json.loads(get(CellarTrackerInventoryView(hass)).body) == []


def test_nothing_configured_still_answers_with_an_empty_list():
    """No coordinator at all: the view must not reach for a rendered body."""
    hass = ViewHass({})
    assert json.loads(get(CellarTrackerInventoryView(hass)).body) == []
