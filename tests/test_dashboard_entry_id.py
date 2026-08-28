"""The bundled dashboard forwards ``?entry_id=`` to the API.

One account per installation is the rule, and with one configured the API
ignores the parameter - so on a current install this changes nothing and a
stale value on an old card URL stays harmless.

It matters for the install that still holds a second entry from before
single-instance was enforced. Both entries stay loaded, the API selects on
``?entry_id=``, and a page that does not forward it gets the lowest entry id
for every card: one account's bottles priced in the other's currency, with no
error. The page copied into the config ``www`` folder before this release
forwards it; the bundled page now does too, so both behave alike.

These reuse the node harness that runs the page's real script.
"""

from __future__ import annotations

import shutil

import pytest
from test_dashboard_token import CELLAR_HTML, assert_js, run_scenario

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is required to exercise the dashboard",
)


def urls_after_load(checks: str) -> str:
    """Let the page's fetches fire, then assert on the URLs it built."""
    return (
        "(async () => {\n"
        "  await new Promise((r) => setTimeout(r, 20));\n"
        + assert_js("fetchUrls.length > 0", "no requests were made")
        + checks
        + "})();\n"
    )


def test_entry_id_is_forwarded_to_every_endpoint():
    run_scenario(
        search="?entry_id=bbb",
        parent_token="live",
        checks=urls_after_load(
            assert_js(
                'fetchUrls.every((u) => u.indexOf("entry_id=bbb") !== -1)',
                "a request went out without the entry_id it was given",
            )
            + assert_js(
                'fetchUrls.some((u) => u.indexOf("/inventory") !== -1)'
                ' && fetchUrls.some((u) => u.indexOf("/settings") !== -1)',
                "both endpoints must carry it, or they describe different accounts",
            )
        ),
    )


def test_no_entry_id_means_no_parameter():
    """The single-account install must not start sending one."""
    run_scenario(
        search="",
        parent_token="live",
        checks=urls_after_load(
            assert_js(
                'fetchUrls.every((u) => u.indexOf("entry_id") === -1)',
                "invented an entry_id that was never asked for",
            )
        ),
    )


@pytest.mark.parametrize("search", ["?entry_id=", "?entry_id=%20%20"])
def test_a_blank_entry_id_is_not_forwarded(search):
    run_scenario(
        search=search,
        parent_token="live",
        checks=urls_after_load(
            assert_js(
                'fetchUrls.every((u) => u.indexOf("entry_id") === -1)',
                "forwarded a blank entry_id",
            )
        ),
    )


def test_the_value_is_encoded():
    run_scenario(
        search="?entry_id=a%2Fb%26c",
        parent_token="live",
        checks=urls_after_load(
            assert_js(
                'fetchUrls.every((u) => u.indexOf("entry_id=a%2Fb%26c") !== -1)',
                "an unescaped id would forge a second query parameter",
            )
        ),
    )


def test_it_survives_the_legacy_token_strip():
    """?token= is deleted from the URL; the entry must not go with it."""
    run_scenario(
        search="?token=SECRET&entry_id=bbb",
        checks=urls_after_load(
            assert_js(
                'fetchUrls.every((u) => u.indexOf("entry_id=bbb") !== -1)',
                "the token strip took entry_id with it",
            )
            + assert_js(
                'fetchUrls.every((u) => u.indexOf("SECRET") === -1)',
                "token leaked into a request URL",
            )
        ),
    )


def test_the_page_documents_the_parameter():
    """It is the only way to reach a legacy second account; keep it findable."""
    assert "entry_id" in CELLAR_HTML.read_text()
