"""cellartracker_inventory_changed: a state-delta event for automations.

Fires when the set of bottles changes between two successful polls, carrying
what was added, what was removed and the new total.

Deliberate edges:

- No event without history. With nothing on disk to compare with - a fresh
  install, or a deleted cache - announcing the whole cellar as "added" would be
  noise, so the first poll is silent. A restart *with* a cache is history: see
  the last item below.
- No event for a revaluation alone. Prices drift constantly; an event for each
  would make it useless to automate on. Only the bottles themselves count.
- A bottle's identity includes its Location and Bin, so moving one shows as
  removed from the old place and added to the new. That is a shift in where
  things are, which is what an LED driver wants to hear about.
- The payload is capped. A large first sync from an empty cellar must not push
  hundreds of kilobytes through the event bus.
- A live poll after data restored from the disk cache does compare against it,
  so bottles changed while Home Assistant was offline are announced.
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from cellar_tracker.analytics import inventory_delta
from cellar_tracker.cellar_data import WineCellarData
from cellar_tracker.const import EVENT_BOTTLE_FIELDS, EVENT_INVENTORY_CHANGED, MAX_EVENT_BOTTLES
from conftest import ConfigEntry, FakeHass, FakeSession

HEADER = "iWine\tWine\tVintage\tLocation\tBin\tValuation\tBottleNote"


def cellar(*rows: str) -> str:
    return "\n".join([HEADER, *rows])


BAROLO = "1\tBarolo\t2016\tCellar\tA1\t50\tprivate tasting note"
RIOJA = "2\tRioja\t2018\tCellar\tB2\t20\t"
PORT = "3\tPort\t2015\tCellar\tC3\t30\t"


def build() -> WineCellarData:
    hass = FakeHass()
    hass.session = FakeSession(text=cellar(BAROLO))
    entry = ConfigEntry(data={"username": "alice", "password": "s3cret"})
    return WineCellarData(hass, entry)


def poll(coordinator: WineCellarData, text: str) -> None:
    """One successful poll, assigning .data the way Home Assistant does."""
    coordinator.hass.session = FakeSession(text=text)
    coordinator.data = asyncio.run(coordinator._async_update_data())


def events(coordinator: WineCellarData) -> list[dict]:
    return [data for name, data in coordinator.hass.bus.events if name == EVENT_INVENTORY_CHANGED]


# --------------------------------------------------------------------------
# The contract
# --------------------------------------------------------------------------
def test_the_event_has_the_documented_name():
    assert EVENT_INVENTORY_CHANGED == "cellartracker_inventory_changed"


# --------------------------------------------------------------------------
# When it does not fire
# --------------------------------------------------------------------------
def test_the_first_poll_fires_nothing():
    coordinator = build()
    poll(coordinator, cellar(BAROLO, RIOJA))
    assert events(coordinator) == []


def test_an_unchanged_inventory_fires_nothing():
    coordinator = build()
    poll(coordinator, cellar(BAROLO, RIOJA))
    poll(coordinator, cellar(BAROLO, RIOJA))
    assert events(coordinator) == []


def test_a_revaluation_alone_fires_nothing():
    coordinator = build()
    poll(coordinator, cellar(BAROLO))
    poll(coordinator, cellar(BAROLO.replace("\t50\t", "\t999\t")))
    assert events(coordinator) == []


def test_a_note_edit_alone_fires_nothing():
    coordinator = build()
    poll(coordinator, cellar(BAROLO))
    poll(coordinator, cellar(BAROLO.replace("private tasting note", "edited")))
    assert events(coordinator) == []


def test_a_failed_poll_fires_nothing():
    coordinator = build()
    poll(coordinator, cellar(BAROLO))
    coordinator.hass.session = FakeSession(error=aiohttp.ClientConnectionError("boom"))
    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())
    assert events(coordinator) == []


# --------------------------------------------------------------------------
# When it does
# --------------------------------------------------------------------------
def test_an_added_bottle_fires():
    coordinator = build()
    poll(coordinator, cellar(BAROLO))
    poll(coordinator, cellar(BAROLO, RIOJA))

    (event,) = events(coordinator)
    assert [b["Wine"] for b in event["added_bottles"]] == ["Rioja"]
    assert event["removed_bottles"] == []
    assert event["total_count"] == 2


def test_a_consumed_bottle_fires():
    coordinator = build()
    poll(coordinator, cellar(BAROLO, RIOJA))
    poll(coordinator, cellar(RIOJA))

    (event,) = events(coordinator)
    assert event["added_bottles"] == []
    assert [b["Wine"] for b in event["removed_bottles"]] == ["Barolo"]
    assert event["total_count"] == 1


def test_a_swap_reports_both_sides():
    coordinator = build()
    poll(coordinator, cellar(BAROLO))
    poll(coordinator, cellar(RIOJA))

    (event,) = events(coordinator)
    assert [b["Wine"] for b in event["added_bottles"]] == ["Rioja"]
    assert [b["Wine"] for b in event["removed_bottles"]] == ["Barolo"]
    assert event["total_count"] == 1


def test_moving_a_bottle_reports_it_as_removed_and_added():
    coordinator = build()
    poll(coordinator, cellar(BAROLO))
    poll(coordinator, cellar(BAROLO.replace("\tA1\t", "\tZ9\t")))

    (event,) = events(coordinator)
    assert event["removed_bottles"][0]["Bin"] == "A1"
    assert event["added_bottles"][0]["Bin"] == "Z9"


def test_a_second_identical_bottle_is_an_addition():
    coordinator = build()
    poll(coordinator, cellar(BAROLO))
    poll(coordinator, cellar(BAROLO, BAROLO))

    (event,) = events(coordinator)
    assert len(event["added_bottles"]) == 1
    assert event["total_count"] == 2


def test_filling_an_empty_cellar_fires():
    """An empty cellar is history too - it is not the same as no history."""
    coordinator = build()
    poll(coordinator, cellar())
    poll(coordinator, cellar(BAROLO))
    assert len(events(coordinator)) == 1


def test_each_change_fires_once():
    coordinator = build()
    poll(coordinator, cellar(BAROLO))
    poll(coordinator, cellar(BAROLO, RIOJA))
    poll(coordinator, cellar(BAROLO, RIOJA))
    poll(coordinator, cellar(BAROLO, RIOJA, PORT))
    assert len(events(coordinator)) == 2


# --------------------------------------------------------------------------
# The payload
# --------------------------------------------------------------------------
def test_total_count_matches_the_coordinator():
    coordinator = build()
    poll(coordinator, cellar(BAROLO))
    poll(coordinator, cellar(BAROLO, RIOJA, PORT))
    assert events(coordinator)[0]["total_count"] == coordinator.data["total_bottles"]


def test_event_bottles_carry_only_the_identifying_fields():
    """The event bus is not a place for tasting notes or what was paid."""
    coordinator = build()
    poll(coordinator, cellar(RIOJA))
    poll(coordinator, cellar(RIOJA, BAROLO))

    added = events(coordinator)[0]["added_bottles"][0]
    assert set(added) <= set(EVENT_BOTTLE_FIELDS)
    assert "BottleNote" not in added
    assert "Valuation" not in added
    assert added["unique_bottle_id"]


def test_the_payload_is_capped():
    coordinator = build()
    poll(coordinator, cellar(BAROLO))
    overflow = MAX_EVENT_BOTTLES + 70
    many = [f"{n}\tWine {n}\t2020\tCellar\tA{n}\t10\t" for n in range(100, 100 + overflow)]
    poll(coordinator, cellar(BAROLO, *many))

    (event,) = events(coordinator)
    assert len(event["added_bottles"]) == MAX_EVENT_BOTTLES
    assert event["added_count"] == MAX_EVENT_BOTTLES + 70
    assert event["truncated"] is True


def test_an_uncapped_payload_says_so():
    coordinator = build()
    poll(coordinator, cellar(BAROLO))
    poll(coordinator, cellar(BAROLO, RIOJA))
    event = events(coordinator)[0]
    assert event["truncated"] is False
    assert event["added_count"] == 1
    assert event["removed_count"] == 0


def test_the_payload_is_json_serialisable():
    import json

    coordinator = build()
    poll(coordinator, cellar(BAROLO))
    poll(coordinator, cellar(RIOJA))
    json.dumps(events(coordinator)[0])


# --------------------------------------------------------------------------
# The disk cache
# --------------------------------------------------------------------------
def test_serving_the_cache_fires_nothing():
    from cellar_tracker.cellar_data import cache_key

    coordinator = build()
    coordinator.hass.storage_backend[cache_key("test_entry")] = {
        "payload": cellar(BAROLO),
        "saved_at": "2026-01-01T00:00:00+00:00",
    }
    coordinator.hass.session = FakeSession(error=aiohttp.ClientConnectionError("boom"))
    coordinator.data = asyncio.run(coordinator._async_update_data())
    assert coordinator.serving_cached_data
    assert events(coordinator) == []


def test_a_live_poll_after_the_cache_announces_what_changed_while_offline():
    from cellar_tracker.cellar_data import cache_key

    coordinator = build()
    coordinator.hass.storage_backend[cache_key("test_entry")] = {
        "payload": cellar(BAROLO),
        "saved_at": "2026-01-01T00:00:00+00:00",
    }
    coordinator.hass.session = FakeSession(error=aiohttp.ClientConnectionError("boom"))
    coordinator.data = asyncio.run(coordinator._async_update_data())

    poll(coordinator, cellar(BAROLO, RIOJA))

    (event,) = events(coordinator)
    assert [b["Wine"] for b in event["added_bottles"]] == ["Rioja"]


# --------------------------------------------------------------------------
# The pure function
# --------------------------------------------------------------------------
def bottle(uid: str, **extra: object) -> dict:
    return {"unique_bottle_id": uid, "Wine": uid, **extra}


def test_delta_of_identical_lists_is_none():
    assert inventory_delta([bottle("a")], [bottle("a")]) is None


def test_delta_ignores_everything_but_identity():
    assert inventory_delta([bottle("a", Valuation=1)], [bottle("a", Valuation=99)]) is None


def test_delta_lists_additions_and_removals_in_cellar_order():
    delta = inventory_delta([bottle("a"), bottle("b")], [bottle("b"), bottle("c"), bottle("d")])
    assert delta is not None
    assert [b["unique_bottle_id"] for b in delta["added"]] == ["c", "d"]
    assert [b["unique_bottle_id"] for b in delta["removed"]] == ["a"]


# --------------------------------------------------------------------------
# Restarting: history comes from the disk cache even when the first poll works
#
# Reported by Codex on #23. After a normal restart coordinator.data is None, and
# the cache was only read on the failure path - so a *successful* first poll,
# the common case, had no history and silently missed bottles added, removed or
# moved while Home Assistant was offline. The documented promise held only when
# the cache had already been served.
# --------------------------------------------------------------------------
def with_cache(coordinator: WineCellarData, payload: str) -> WineCellarData:
    from cellar_tracker.cellar_data import cache_key

    coordinator.hass.storage_backend[cache_key("test_entry")] = {
        "payload": payload,
        "saved_at": "2026-01-01T00:00:00+00:00",
    }
    return coordinator


def first_live_poll(coordinator: WineCellarData, text: str) -> None:
    """The first refresh after a restart: no data yet, upstream answers."""
    assert coordinator.data is None
    poll(coordinator, text)


def test_a_live_first_poll_announces_what_changed_while_offline():
    coordinator = with_cache(build(), cellar(BAROLO))
    first_live_poll(coordinator, cellar(BAROLO, RIOJA))

    (event,) = events(coordinator)
    assert [b["Wine"] for b in event["added_bottles"]] == ["Rioja"]
    assert event["removed_bottles"] == []
    assert event["total_count"] == 2


def test_a_live_first_poll_announces_a_bottle_consumed_while_offline():
    coordinator = with_cache(build(), cellar(BAROLO, RIOJA))
    first_live_poll(coordinator, cellar(RIOJA))

    (event,) = events(coordinator)
    assert [b["Wine"] for b in event["removed_bottles"]] == ["Barolo"]


def test_a_live_first_poll_announces_a_bottle_moved_while_offline():
    coordinator = with_cache(build(), cellar(BAROLO))
    first_live_poll(coordinator, cellar(BAROLO.replace("\tA1\t", "\tZ9\t")))

    (event,) = events(coordinator)
    assert event["removed_bottles"][0]["Bin"] == "A1"
    assert event["added_bottles"][0]["Bin"] == "Z9"


def test_a_live_first_poll_matching_the_cache_fires_nothing():
    coordinator = with_cache(build(), cellar(BAROLO, RIOJA))
    first_live_poll(coordinator, cellar(BAROLO, RIOJA))
    assert events(coordinator) == []


def test_an_identical_cache_is_not_parsed_at_all():
    """Nothing to compare when the bytes match - so no second parse at startup."""
    coordinator = with_cache(build(), cellar(BAROLO))
    first_live_poll(coordinator, cellar(BAROLO))
    assert coordinator.hass.executor_jobs == ["_parse_and_process"]


def test_a_revaluation_while_offline_fires_nothing():
    coordinator = with_cache(build(), cellar(BAROLO))
    first_live_poll(coordinator, cellar(BAROLO.replace("\t50\t", "\t999\t")))
    assert events(coordinator) == []


def test_with_no_cache_the_first_live_poll_still_fires_nothing():
    coordinator = build()
    first_live_poll(coordinator, cellar(BAROLO, RIOJA))
    assert events(coordinator) == []


def test_the_comparison_does_not_disturb_what_the_views_serve():
    """Parsing the cache to compare must not overwrite the live pre-rendered bodies."""
    import json

    coordinator = with_cache(build(), cellar(BAROLO))
    first_live_poll(coordinator, cellar(BAROLO, RIOJA))

    served = {b["Wine"] for b in json.loads(coordinator.inventory_body)}
    assert served == {"Barolo", "Rioja"}


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param("<html>maintenance</html>\n<body>back soon</body>", id="error-page"),
        pytest.param("", id="empty"),
    ],
)
def test_an_unusable_cache_gives_no_history_but_does_not_break_the_poll(bad):
    coordinator = with_cache(build(), bad)
    first_live_poll(coordinator, cellar(BAROLO, RIOJA))
    assert coordinator.data["total_bottles"] == 2
    assert events(coordinator) == []


def test_an_unreadable_cache_gives_no_history_but_does_not_break_the_poll():
    coordinator = with_cache(build(), cellar(BAROLO))
    coordinator.hass.storage_load_error = OSError("disk unplugged")
    first_live_poll(coordinator, cellar(BAROLO, RIOJA))
    assert coordinator.data["total_bottles"] == 2
    assert events(coordinator) == []


def test_the_restart_event_fires_once_not_on_every_poll():
    coordinator = with_cache(build(), cellar(BAROLO))
    first_live_poll(coordinator, cellar(BAROLO, RIOJA))
    poll(coordinator, cellar(BAROLO, RIOJA))
    poll(coordinator, cellar(BAROLO, RIOJA))
    assert len(events(coordinator)) == 1
