"""Review feedback on PR #12: the dashboard page HACS never installed.

The README told HACS users to copy ``custom_components/www/cellar.html`` into
``<config>/www``. That source path does not exist on their system: HACS's
``Integration`` category installs ``custom_components/cellar_tracker`` and
nothing else, so the page - a sibling of that directory - was never downloaded.
Anyone following the instructions hit a missing file, and the advertised bottle
table was unreachable without separately cloning the repository.

The page now ships *inside* the integration directory, so every install route
brings it along, and the integration serves it itself at ``DASHBOARD_URL``.
Nothing has to be copied anywhere. Installs predating v0.0.16 that already
copied it keep working: ``/local/`` is Home Assistant's own static mount and is
untouched by this.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

import cellar_tracker
from cellar_tracker import DASHBOARD_FILE, async_setup
from cellar_tracker.const import DASHBOARD_URL
from conftest import ViewHass

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPONENT = REPO_ROOT / "custom_components" / "cellar_tracker"


def setup(hass):
    return asyncio.run(async_setup(hass, {}))


# --------------------------------------------------------------------------
# Packaging: the page must travel with the integration
# --------------------------------------------------------------------------
def test_the_page_ships_inside_the_directory_hacs_installs():
    """HACS copies COMPONENT and nothing else, so the page must live under it."""
    assert DASHBOARD_FILE.is_file(), f"{DASHBOARD_FILE} is missing"
    assert COMPONENT in DASHBOARD_FILE.parents


def test_no_page_survives_outside_the_installed_directory():
    """A second copy would be a path the install instructions could regress to."""
    strays = [
        path
        for path in (REPO_ROOT / "custom_components").rglob("cellar.html")
        if COMPONENT not in path.parents
    ]
    assert strays == [], f"cellar.html outside the installed directory: {strays}"


# --------------------------------------------------------------------------
# Serving: no copy step, so the integration must serve the page itself
# --------------------------------------------------------------------------
def test_setup_serves_the_bundled_page():
    hass = ViewHass()
    assert setup(hass) is True

    served = {config.url_path: config for config in hass.http.static_paths}
    assert DASHBOARD_URL in served, "the dashboard page is not served"
    assert served[DASHBOARD_URL].path == str(DASHBOARD_FILE)


def test_the_served_page_is_not_cached():
    """An upgrade must not leave browsers rendering the previous page."""
    hass = ViewHass()
    setup(hass)

    assert hass.http.static_paths[0].cache_headers is False


def test_the_url_does_not_depend_on_the_local_mount():
    """/local/ is <config>/www - i.e. exactly the copy step this removed."""
    assert not DASHBOARD_URL.startswith("/local/")
    assert DASHBOARD_URL.endswith("/cellar.html")


def test_the_page_is_served_once_per_home_assistant_start():
    """async_setup runs once; a route registered twice raises in aiohttp."""
    hass = ViewHass()
    setup(hass)

    assert [config.url_path for config in hass.http.static_paths] == [DASHBOARD_URL]


# --------------------------------------------------------------------------
# A missing page must cost the dashboard, not the integration
# --------------------------------------------------------------------------
def test_a_missing_page_does_not_fail_setup(monkeypatch, caplog):
    monkeypatch.setattr(cellar_tracker, "DASHBOARD_FILE", pathlib.Path("/nonexistent/x.html"))
    hass = ViewHass()

    assert setup(hass) is True
    assert hass.http.static_paths == []
    assert "is missing" in caplog.text


def test_a_missing_page_still_leaves_the_api_usable(monkeypatch):
    monkeypatch.setattr(cellar_tracker, "DASHBOARD_FILE", pathlib.Path("/nonexistent/x.html"))
    hass = ViewHass()
    setup(hass)

    assert sorted(hass.http.registered) == [
        "CellarTrackerInventoryView",
        "CellarTrackerSettingsView",
    ]


# --------------------------------------------------------------------------
# The instructions are the thing that was wrong; keep them honest
# --------------------------------------------------------------------------
DOCS = {
    "README.md": (REPO_ROOT / "README.md").read_text(),
    "custom_components/card.yaml": (REPO_ROOT / "custom_components" / "card.yaml").read_text(),
}


@pytest.mark.parametrize("name", sorted(DOCS))
def test_docs_point_at_the_served_url(name):
    assert DASHBOARD_URL in DOCS[name], f"{name} never mentions {DASHBOARD_URL}"


@pytest.mark.parametrize("name", sorted(DOCS))
def test_docs_do_not_ask_users_to_copy_a_file_hacs_never_installed(name):
    assert "custom_components/www" not in DOCS[name], (
        f"{name} still points at a path that does not exist after an install"
    )


# --------------------------------------------------------------------------
# Claims that go stale silently
# --------------------------------------------------------------------------
def test_the_readme_counts_the_compact_columns_correctly():
    """It said nine for as long as there were nine, and then Barcode arrived."""
    from cellar_tracker.const import COMPACT_FIELDS

    words = {
        9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
        14: "fourteen", 15: "fifteen",
    }
    expected = words.get(len(COMPACT_FIELDS))
    assert expected, f"add {len(COMPACT_FIELDS)} to this table"
    assert f"the same bottles, {expected} columns" in DOCS["README.md"], (
        f"the README should say the compact view has {expected} columns"
    )


def test_the_readme_describes_the_states_the_page_actually_shows():
    """The colouring changed in 0.0.20 and the README described the old one.

    Read out of the page rather than restated here, so the two cannot drift:
    a label renamed in cellar.html has to be renamed in the README too.
    """
    import re

    page = (COMPONENT / "www" / "cellar.html").read_text()
    labels = re.search(r"const STATE_LABEL = \{(.*?)\};", page, re.S)
    assert labels, "cellar.html no longer declares STATE_LABEL"

    described = set(re.findall(r"'([^']+)'", labels.group(1)))
    described.add("Drink this year")  # the urgent label, set inline

    missing = sorted(label for label in described if label not in DOCS["README.md"])
    assert not missing, f"the README never mentions the state(s) {missing}"
