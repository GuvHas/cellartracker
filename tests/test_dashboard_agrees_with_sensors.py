"""The dashboard's chips and the integration's sensors must count alike.

Both live on the same Home Assistant page. A sensor card reading "12 ready to
drink" beside a dashboard chip reading "Ready to drink (9)" is not a cosmetic
difference - it is the integration contradicting itself, and the user has no
way to tell which number is wrong.

They are computed twice because they have to be: the coordinator counts in
Python at poll time so the sensors are cheap, and the page counts in JavaScript
so a chip can filter without a round trip. Two implementations of one rule is
exactly the situation that drifts, so this runs both over the same cellar and
compares.

``_drink_window_counts`` in cellar_data.py is the definition; the page follows
it. Note in particular that the last year of a window counts as *ready* in both
- the page used to paint that year red, which read as expired.
"""

from __future__ import annotations

import asyncio
import json

from dashboard_js import requires_node, run_js

from cellar_tracker.cellar_data import WineCellarData
from conftest import ConfigEntry, FakeHass, FakeSession

pytestmark = requires_node

YEAR = 2026
HEADER = "iWine\tWine\tValuation\tBeginConsume\tEndConsume"

# Deliberately awkward: both bounds, one bound, neither, the boundary years on
# each side, and a row whose window is inverted.
CELLAR = [
    ("2020", "2030"),
    ("2010", "2015"),
    ("2030", "2040"),
    ("", ""),
    (str(YEAR), "2030"),
    ("2010", str(YEAR)),
    ("2010", str(YEAR - 1)),
    ("2020", ""),
    ("", "2030"),
    ("", "2010"),
    ("2030", "2020"),
    ("not a year", "2030"),
]


def python_counts() -> tuple[int, int]:
    """What the sensors will report for this cellar."""
    rows = "\n".join(
        f"{i}\tWine {i}\t10.00\t{begin}\t{end}"
        for i, (begin, end) in enumerate(CELLAR, start=1)
    )
    hass = FakeHass()
    hass.session = FakeSession(text="\n".join([HEADER, rows]))
    coordinator = WineCellarData(hass, ConfigEntry(data={"username": "a", "password": "b"}))
    coordinator._current_year = lambda: YEAR
    data = asyncio.run(coordinator._async_update_data())
    return data["ready_to_drink"], data["past_drink_window"]


def javascript_counts() -> dict:
    """What the chips will show for the same cellar."""
    wines = json.dumps(
        [
            {
                "iWine": str(i), "Wine": f"Wine {i}", "Vintage": "2020",
                "Valuation": "10.00", "BeginConsume": begin, "EndConsume": end,
            }
            for i, (begin, end) in enumerate(CELLAR, start=1)
        ]
    )
    output = run_js(
        f"const rows = {wines}.map(normaliseWine);\n"
        f"console.log(JSON.stringify(filterCounts(rows, {YEAR})));"
    )
    return json.loads(output.strip())


def test_ready_to_drink_agrees():
    ready, _ = python_counts()
    assert javascript_counts()["ready"] == ready


def test_past_the_window_agrees():
    _, past = python_counts()
    assert javascript_counts()["past"] == past


def test_the_cellar_used_here_actually_exercises_both_states():
    """A fixture where both counts are zero would agree about nothing."""
    ready, past = python_counts()
    assert ready > 0 and past > 0


def test_every_bottle_lands_in_exactly_one_chip():
    """all == ready + past + aging + the ones with no window at all."""
    counts = javascript_counts()
    assert counts["all"] == len(CELLAR)
    assert counts["ready"] + counts["past"] + counts["aging"] <= counts["all"]


def test_the_chips_that_the_sensors_do_not_count_are_the_ones_without_a_window():
    """The coordinator counts a bottle with no window in neither sensor.

    The page still has to show it under "All wines", and must not quietly file
    it as ready or past to make the arithmetic tidy.
    """
    ready, past = python_counts()
    counts = javascript_counts()
    unplaced = counts["all"] - counts["ready"] - counts["past"] - counts["aging"]
    assert unplaced == len(CELLAR) - ready - past - counts["aging"]
    assert unplaced > 0, "the fixture should include a bottle with no window"
