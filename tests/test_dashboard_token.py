"""F-12: the dashboard must not carry an access token in its URL.

cellar.html read ``?token=`` straight out of the query string. A Home Assistant
long-lived token is full-account and never expires, and a URL carrying one ends
up in browser history, in reverse-proxy and Home Assistant access logs, and in
any screenshot or link the user shares.

The page is normally embedded via an iframe card on the same origin, so it can
read the live session from the parent frame and needs no stored secret at all.
A ``?token=`` is no longer accepted at all: by the time the script runs, the
request carrying it has already reached the access logs, so honouring it even
once kept the leak alive. It is stripped from the address bar and ignored, and
a copy an older page stored in sessionStorage is dropped.

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
    / "custom_components"
    / "cellar_tracker"
    / "www"
    / "cellar.html"
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
const fetchAuth = [];
let refreshes = 0;
const store = Object.assign({}, scenario.session || {});

// One auth object per frame, kept so a refresh is seen by later lookups,
// as Home Assistant's own Auth object mutates its data in place.
const auths = {};
function hassElement(token) {
    if (!token) return null;
    if (!auths[token]) {
        const auth = {
            data: { access_token: token },
            expired: !!scenario.expired,
            async refreshAccessToken() {
                refreshes++;
                auth.data = { access_token: token + "-refreshed-" + refreshes };
                auth.expired = false;
            },
        };
        auths[token] = auth;
    }
    return { hass: { auth: auths[token] } };
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
    location: { search: scenario.search, pathname: "/cellartracker/cellar.html" },
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

globalThis.fetch = (url, options) => {
    fetchUrls.push(String(url));
    const header = (options && options.headers && options.headers.Authorization) || null;
    fetchAuth.push(header);
    // Home Assistant accepts only a refreshed token when the scenario says
    // the one at load has gone stale; otherwise every request is refused.
    const ok = scenario.acceptRefreshed && header && header.indexOf("-refreshed-") !== -1;
    return Promise.resolve({ ok, status: ok ? 200 : 401, json: async () => [] });
};

globalThis.console = { ...console, warn() {}, error() {} };
"""


def run_scenario(
    *,
    search="",
    parent_token=None,
    own_token=None,
    session=None,
    checks="",
    expired=False,
    accept_refreshed=False,
):
    scenario = json.dumps(
        {
            "search": search,
            "parentToken": parent_token,
            "ownToken": own_token,
            "session": session or {},
            "expired": expired,
            "acceptRefreshed": accept_refreshed,
        }
    )
    source = "\n".join([PRELUDE % scenario, page_script(), textwrap.dedent(checks)])
    result = subprocess.run(
        ["node", "--input-type=commonjs", "-e", source],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


def assert_js(expression, message):
    return f"if (!({expression})) {{ console.error({json.dumps(message)}); process.exit(1); }}\n"


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
# A ?token= in the URL is never used, and never stored
# --------------------------------------------------------------------------
def test_a_url_token_is_not_used():
    run_scenario(
        search="?token=SECRET",
        checks=assert_js("!token", "authenticated with a token from the URL"),
    )


def test_a_url_token_does_not_override_the_session():
    run_scenario(
        search="?token=SECRET",
        parent_token="live",
        checks=assert_js('token === "live"', "did not use the live session"),
    )


def test_a_url_token_is_stripped_from_the_address_bar():
    run_scenario(
        search="?token=SECRET",
        checks=assert_js("replaceStateCalls.length === 1", "URL was not rewritten")
        + assert_js(
            'replaceStateCalls[0].indexOf("SECRET") === -1',
            "token survived in the rewritten URL",
        )
        + assert_js(
            'window.location.search.indexOf("token") === -1',
            "token still present in location.search",
        ),
    )


def test_a_url_token_never_enters_storage():
    run_scenario(
        search="?token=SECRET",
        checks=assert_js("Object.keys(store).length === 0", "the token was stored"),
    )


def test_stripping_preserves_other_query_parameters():
    run_scenario(
        search="?token=SECRET&keep=me",
        checks=assert_js(
            'replaceStateCalls[0].indexOf("keep=me") !== -1',
            "an unrelated query parameter was lost when the token was stripped",
        ),
    )


def test_a_token_stored_by_an_older_page_is_dropped_not_used():
    run_scenario(
        session={"cellartracker_token": "STORED"},
        checks=assert_js("!token", "a stored token was reused")
        + assert_js('!("cellartracker_token" in store)', "the stored token was kept"),
    )


def test_no_session_fails_closed_without_an_authorization_header():
    run_scenario(
        checks="(async () => {\n"
        + "  await new Promise((r) => setTimeout(r, 20));\n"
        + assert_js("!token", "invented a token from nowhere")
        + assert_js("fetchAuth.length > 0", "no requests were made")
        + assert_js(
            "fetchAuth.every((h) => h === null)",
            "sent an Authorization header with no session",
        )
        + "})();\n",
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


# --------------------------------------------------------------------------
# Access tokens expire after 30 minutes; a page left open must not keep
# sending the one it saw at load (HA logs that as a failed login and counts
# it towards an IP ban).
# --------------------------------------------------------------------------
def test_requests_read_the_token_at_send_time():
    run_scenario(
        parent_token="first",
        checks="(async () => {\n"
        + "  await new Promise((r) => setTimeout(r, 20));\n"
        + "  auths.first.data = { access_token: 'rotated' };\n"
        + "  fetchAuth.length = 0;\n"
        + "  await callService('locate_bottle', { location: 'Rack 1', bin: 'A1' });\n"
        + assert_js("fetchAuth[0] === 'Bearer rotated'", "sent the token from page load")
        + "})();\n",
    )


def test_an_expired_token_is_refreshed_before_sending():
    run_scenario(
        parent_token="stale",
        expired=True,
        accept_refreshed=True,
        checks="(async () => {\n"
        + "  await new Promise((r) => setTimeout(r, 20));\n"
        + "  fetchAuth.length = 0;\n"
        + "  const ok = await callService('locate_bottle', { location: 'Rack 1', bin: 'A1' });\n"
        + assert_js("ok === true", "the action was not accepted")
        + assert_js("fetchAuth.length === 1", "sent more than one request")
        + assert_js(
            "fetchAuth[0].indexOf('-refreshed-') !== -1",
            "sent the expired token",
        )
        + "})();\n",
    )


def test_a_401_is_retried_once_with_a_refreshed_token():
    run_scenario(
        parent_token="revoked",
        accept_refreshed=True,
        checks="(async () => {\n"
        + "  await new Promise((r) => setTimeout(r, 20));\n"
        + "  auths.revoked.data = { access_token: 'revoked' };\n"
        + "  fetchAuth.length = 0;\n"
        + "  const ok = await callService('locate_bottle', { location: 'Rack 1', bin: 'A1' });\n"
        + assert_js("ok === true", "did not recover from the 401")
        + assert_js("fetchAuth.length === 2", "expected exactly one retry")
        + assert_js("fetchAuth[0] === 'Bearer revoked'", "first try used the wrong token")
        + assert_js("fetchAuth[1].indexOf('-refreshed-') !== -1", "retry was not refreshed")
        + "})();\n",
    )


def test_a_401_without_a_session_is_not_retried():
    run_scenario(
        checks="(async () => {\n"
        + "  await new Promise((r) => setTimeout(r, 20));\n"
        + "  fetchAuth.length = 0;\n"
        + "  const ok = await callService('locate_bottle', { location: 'Rack 1', bin: 'A1' });\n"
        + assert_js("ok === false", "reported success without a session")
        + assert_js("fetchAuth.length === 1", "retried with nothing to refresh")
        + "})();\n",
    )
