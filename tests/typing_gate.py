"""Checked by mypy, never collected by pytest: proof the type gate has teeth.

A mypy job that reports "Success" says nothing on its own. If Home Assistant's
own types are not resolvable, ``DataUpdateCoordinator`` is ``Any``; subclassing
``Any`` makes every inherited member ``Any``; and ``coordinator.data`` - the
thing the generic parameter exists to type - is ``Any`` again at every call
site. The gate then passes a misspelled key, an invalid framework call and a
wrong return type without a word, which is worse than no gate at all, because
it reads as if those were checked.

So this file asserts what the gate is supposed to guarantee, in the checker's
own terms:

  * ``assert_type`` fails on ``Any``. Each one below is a claim that a real
    type reached that expression, not a shrug that passed silently.
  * The ``type: ignore`` comments are the negative half: with
    ``warn_unused_ignores`` on, an ignore that stops being necessary is itself
    an error. They therefore fail if a misspelled key ever stops being
    rejected.

Named ``typing_gate`` rather than ``test_*`` because pytest must not collect
it - the assertions are static, and the runtime import would pull in the stub
Home Assistant that conftest installs. ``mypy`` checks it by path instead; see
``files`` in pyproject.toml.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, assert_type

from cellar_tracker.cellar_data import (
    CellarData,
    CellarTrackerConfigEntry,
    WineCellarData,
)


def the_payload_keeps_its_type(coordinator: WineCellarData) -> None:
    """The whole point of DataUpdateCoordinator[CellarData].

    Optional because the coordinator says so: Home Assistant assigns None to
    ``data`` until the first refresh succeeds, and WineCellarData redeclares
    it honestly rather than letting the guards that handle it read as dead
    code. Any is neither of these, so this still fails if the base class goes
    unresolved.
    """
    assert_type(coordinator.data, CellarData | None)

    data = coordinator.data
    if data is None:
        return
    assert_type(data["total_bottles"], int)
    assert_type(data["total_value"], float)
    assert_type(data["bottles"], list[dict[str, Any]])


def the_inherited_members_keep_theirs(coordinator: WineCellarData) -> None:
    """Inherited, so these are Any the moment the base class is unresolved."""
    assert_type(coordinator.last_update_success, bool)
    assert_type(coordinator.update_interval, timedelta | None)
    assert_type(coordinator.last_success, datetime | None)


def a_misspelled_key_is_rejected(data: CellarData) -> None:
    """The error the gate was accepting in silence before this."""
    data["total_bottle"]  # type: ignore[typeddict-item]
    data["definitely_not_a_key"]  # type: ignore[typeddict-item]


def the_entry_carries_the_coordinator(entry: CellarTrackerConfigEntry) -> None:
    """Otherwise runtime_data is Any in __init__, sensor, views, diagnostics."""
    assert_type(entry.runtime_data, WineCellarData)
    assert_type(entry.runtime_data.currency, str)
    assert_type(entry.runtime_data.inventory_body, bytes)
