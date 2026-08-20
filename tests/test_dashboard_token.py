"""F-12: the dashboard must not carry an access token in its URL.

cellar.html read ``?token=`` straight out of the query string. A Home Assistant
long-lived token is full-account and never expires, and a URL carrying one ends
up in browser history, in reverse-proxy and Home Assistant access logs, and in
any screenshot or link the user shares.

The page is normally embedded via an iframe card on the same origin, so it can
read the live session from the parent frame and needs no stored secret at all.
A ``?token=`` is still honoured once so existing bookmarks keep working, but it
is moved into sessionStorage and stripped from the address bar immediately.

These tests run the page's real script under node with stubbed browser globals.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import textwrap

import pytest

CELLAR_HTML = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components" / "www" / "cellar.html"
)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to exercise the dashboard"
)


def page_script() -> str:
    html = CELLAR_HTML.read_text()
    return re.search(r"<script>(.*)</script>", html, re.S).group(1)


PRELUDE = """
const scenario = %s;

const replaceStateCalls = [];
const fetchUrls = [];
const store = Object.assign({}, scenario.session || {});

function hassElement(token) {
    return token ? { hass: { auth: { data: { access_token: token } } } } : null;
}

const stubElement = {
    addEventListener() {}, appendChild() {}, removeAttribute() {},
    setAttribute() {}, getAttribute() { return "sortTable('Wine')"; },
    classList: { add() {}, remove() {} }, style: {}, value: "",
    textContent: "", innerHTML: "",
};

globalThis.sessionStorage = {
    getItem: (key) => (key in store ? store[key] : null),
    setItem: (key, value) => { store[key] = String(value); },
    removeItem: (key) => { delete store[key]; },
};

globalThis.window = {
    location: { search: scenario.search, pathname: "/local/cellar.html" },
    history: {
        replaceState(state, title, url) {
            replaceStateCalls.push(url);
            const q = String(url).indexOf("?");
            globalThis.window.location.search = q === -1 ? "" : String(url).slice(q);
        },
    },
    parent: { document: { querySelector: () => hassElement(scenario.parentToken) } },
};
globalThis.sessionStorage = globalThis.sessionStorage;

globalThis.document = {
    getElementById: () => Object.assign({}, stubElement),
    querySelector: () => hassElement(scenario.ownToken),
    querySelectorAll: () => [],
    createElement: () => Object.assign({}, stubElement),
};

globalThis.fetch = (url) => {
    fetchUrls.push(String(url));
    return Promise.resolve({ ok: false, status: 401, json: async () => ({}) });
};

globalThis.console = { ...console, warn() {}, error() {} };
"""


def run_scenario(*, search="", parent_token=None, own_token=None, session=None, checks=""):
    scenario = json.dumps(
        {
            "search": search,
            "parentToken": parent_token,
            "ownToken": own_token,
            "session": session or {},
        }
    )
    source = "\n".join(
        [PRELUDE % scenario, page_script(), textwrap.dedent(checks)]
    )
    result = subprocess.run(
        ["node", "--input-type=commonjs", "-e", source],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


def assert_js(expression, message):
    return f'if (!({expression})) {{ console.error({json.dumps(message)}); process.exit(1); }}\n'


# --------------------------------------------------------------------------
# The supported path: read the live session from the parent frame
# --------------------------------------------------------------------------
def test_token_comes_from_the_parent_frame():
    run_scenario(
        parent_token="from-parent",
        checks=assert_js('token === "from-parent"', "did not read the parent session")
        + assert_js("replaceStateCalls.length === 0", "rewrote the URL unnecessarily"),
    )


def test_token_falls_back_to_the_own_document():
    run_scenario(
        own_token="from-own-doc",
        checks=assert_js('token === "from-own-doc"', "did not read own document"),
    )


def test_no_token_anywhere_yields_none():
    run_scenario(checks=assert_js("!token", "invented a token from nowhere"))


# --------------------------------------------------------------------------
# F-12: a legacy ?token= must be honoured once, then removed from the URL
# --------------------------------------------------------------------------
def test_legacy_url_token_is_stripped_from_the_address_bar():
    run_scenario(
        search="?token=SECRET",
        checks=assert_js('token === "SECRET"', "legacy bookmark stopped working")
        + assert_js("replaceStateCalls.length === 1", "URL was not rewritten")
        + assert_js(
            'replaceStateCalls[0].indexOf("SECRET") === -1',
            "token survived in the rewritten URL",
        )
        + assert_js(
            'window.location.search.indexOf("token") === -1',
            "token still present in location.search",
        ),
    )


def test_legacy_token_is_kept_for_the_session():
    run_scenario(
        search="?token=SECRET",
        checks=assert_js(
            'sessionStorage.getItem("cellartracker_token") === "SECRET"',
            "token was not preserved for reloads",
        ),
    )


def test_stripping_preserves_other_query_parameters():
    run_scenario(
        search="?token=SECRET&entry_id=abc123",
        checks=assert_js(
            'replaceStateCalls[0].indexOf("entry_id=abc123") !== -1',
            "entry_id was lost when the token was stripped",
        )
        + assert_js("entryId === 'abc123'", "entry_id no longer reaches the API"),
    )


def test_a_stored_token_survives_a_reload():
    run_scenario(
        session={"cellartracker_token": "STORED"},
        checks=assert_js('token === "STORED"', "stored token was not reused"),
    )


def test_a_live_session_is_preferred_over_a_stored_token():
    run_scenario(
        parent_token="live",
        session={"cellartracker_token": "STORED"},
        checks=assert_js('token === "live"', "preferred a stored secret over the session"),
    )


# --------------------------------------------------------------------------
# The token must never travel in a URL we construct
# --------------------------------------------------------------------------
def test_the_token_never_appears_in_a_request_url():
    run_scenario(
        search="?token=SECRET",
        checks="(async () => {\n"
        + "  await new Promise((r) => setTimeout(r, 20));\n"
        + assert_js("fetchUrls.length > 0", "no requests were made")
        + assert_js(
            'fetchUrls.every((u) => u.indexOf("SECRET") === -1)',
            "token leaked into a request URL",
        )
        + "})();\n",
    )


def test_the_page_no_longer_advertises_url_tokens():
    """The old error text told users to put a token in the URL."""
    html = CELLAR_HTML.read_text()
    assert "LONG_LIVED_ACCESS_TOKEN" not in html
