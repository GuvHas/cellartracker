"""F-10 and F-11: don't mutate the caller's rows, and mean it about "stable".

F-10: _process_inventory wrote unique_bottle_id into the dicts the library
returned and coerced their Valuation in place, so the caller's data changed
underneath it and a second pass over the same list saw different input.

F-11: the comment claimed "Stable Unique ID Generation", but duplicate suffixes
(_1, _2, ...) were handed out in arrival order. Reordering the upstream response
therefore moved a given id onto a different row.

The identity must be built from the fields that identify a *physical bottle*
and must exclude volatile columns such as Valuation - an id that changed every
time CellarTracker re-priced a wine would be useless to anything keying on it.
"""

from __future__ import annotations

import hashlib

import pytest

from cellar_tracker.cellar_data import WineCellarData
from conftest import ConfigEntry, FakeHass


def process(rows, previous=None):
    entry = ConfigEntry(data={"username": "alice", "password": "secret"})
    coordinator = WineCellarData(FakeHass(), entry)
    return coordinator._process_inventory(rows, previous=previous)


def ids_by(rows, key):
    """Map each row's `key` value to the id it was assigned."""
    result = process([dict(row) for row in rows])
    return {bottle[key]: bottle["unique_bottle_id"] for bottle in result["bottles"]}


# --------------------------------------------------------------------------
# F-10: the caller's dicts are not ours to write to
# --------------------------------------------------------------------------
def test_input_rows_are_left_untouched():
    rows = [{"iWine": "1", "Valuation": "12.50"}]
    original = [dict(row) for row in rows]
    process(rows)
    assert rows == original


def test_returned_rows_are_copies():
    rows = [{"iWine": "1", "Valuation": "12.50"}]
    result = process(rows)
    assert result["bottles"][0] is not rows[0]


def test_processing_is_repeatable_on_the_same_input():
    """The first pass used to corrupt the input for the second."""
    rows = [{"iWine": "1", "Valuation": "12.50"}, {"iWine": "1", "Valuation": "12.50"}]
    first = process(rows)
    second = process(rows)
    assert first == second


def test_returned_rows_still_carry_the_derived_fields():
    result = process([{"iWine": "1", "Valuation": "12.50"}])
    bottle = result["bottles"][0]
    assert bottle["Valuation"] == 12.5
    assert isinstance(bottle["Valuation"], float)
    assert bottle["unique_bottle_id"]


# --------------------------------------------------------------------------
# F-11: ids must not depend on the order rows arrive in
# --------------------------------------------------------------------------
def test_ids_are_independent_of_row_order():
    """Same identifying fields, distinguishable only by a non-identifying one."""
    rows = [
        {"iWine": "1", "Bin": "A", "Valuation": "10", "Note": "first"},
        {"iWine": "1", "Bin": "A", "Valuation": "10", "Note": "second"},
    ]
    assert ids_by(rows, "Note") == ids_by(list(reversed(rows)), "Note")


def test_ids_are_independent_of_order_for_a_larger_group():
    rows = [
        {"iWine": "7", "Bin": "B", "Valuation": "20", "Note": name}
        for name in ("a", "b", "c", "d")
    ]
    shuffled = [rows[2], rows[0], rows[3], rows[1]]
    assert ids_by(rows, "Note") == ids_by(shuffled, "Note")


# --------------------------------------------------------------------------
# F-11: ids must survive volatile data changing
# --------------------------------------------------------------------------
def test_ids_survive_a_re_pricing():
    """Valuation moves constantly; an id keyed on it would churn every poll."""
    cheap = process([{"iWine": "1", "Bin": "A", "Valuation": "10"}])
    dear = process([{"iWine": "1", "Bin": "A", "Valuation": "999"}])
    assert (
        cheap["bottles"][0]["unique_bottle_id"]
        == dear["bottles"][0]["unique_bottle_id"]
    )


@pytest.mark.parametrize("field", ["iWine", "PurchaseDate", "Barcode", "Location", "Bin"])
def test_a_different_identifying_field_yields_a_different_id(field):
    base = {"iWine": "1", "PurchaseDate": "2024-01-01", "Barcode": "b",
            "Location": "L", "Bin": "A"}
    changed = {**base, field: "CHANGED"}
    assert (
        process([base])["bottles"][0]["unique_bottle_id"]
        != process([changed])["bottles"][0]["unique_bottle_id"]
    )


# --------------------------------------------------------------------------
# Hash properties
# --------------------------------------------------------------------------
def test_ids_use_sha256_not_sha1():
    """SHA-1 is flagged by scanners; SHA-256 is a free swap for a non-secret id."""
    row = {"iWine": "1", "PurchaseDate": "", "Barcode": "", "Location": "", "Bin": ""}
    bottle_id = process([dict(row)])["bottles"][0]["unique_bottle_id"]

    legacy = hashlib.sha1(b"1____").hexdigest()[:16]
    assert bottle_id != legacy, "still using the old SHA-1 identity"


def test_ids_are_sixteen_hex_characters():
    bottle_id = process([{"iWine": "1"}])["bottles"][0]["unique_bottle_id"]
    assert len(bottle_id) == 16
    assert all(char in "0123456789abcdef" for char in bottle_id)


def test_identical_rows_get_dense_suffixes():
    rows = [{"iWine": "1", "Bin": "A", "Valuation": "5"} for _ in range(3)]
    ids = [b["unique_bottle_id"] for b in process(rows)["bottles"]]
    base = ids[0]
    assert ids == [base, f"{base}_1", f"{base}_2"]


def test_missing_optional_fields_are_handled():
    """Rows need only iWine; the rest of the identity may be absent."""
    ids = [b["unique_bottle_id"] for b in process([{"iWine": "1"}, {"iWine": "2"}])["bottles"]]
    assert len(set(ids)) == 2
