"""P0-3: no exception this integration raises may carry the password.

CellarTracker's export API takes credentials as query parameters, so the
password is embedded in the request URL. That is the vendor's design and cannot
be changed from here. What can be changed is how far it travels.

aiohttp's ``ClientResponseError`` carries the full request URL in both ``str()``
and ``repr()``:

    429, message='Too Many Requests', url='https://www.cellartracker.com/
    xlquery.asp?User=bob&Password=hunter2&Table=Inventory'

Before this change nothing printed it, but only by accident: ``raise_for_status``
raised ``ClientResponseError``, which was caught as ``aiohttp.ClientError`` and
re-raised as a bare ``CannotConnect``, whose ``repr()`` is harmless. The secret
survived as ``__cause__``, where nothing happened to format it. One
``_LOGGER.exception`` in that branch, one ``diagnostics.py`` dumping the last
exception, or debug logging on ``aiohttp.client`` would have published it.

So: strip it at the source, and sever ``__cause__`` with ``from None`` so the
URL-bearing exception is unreachable rather than merely unformatted.
"""

from __future__ import annotations

import asyncio
import traceback

import aiohttp
import pytest
from cellartracker.errors import CannotConnect
from homeassistant.helpers.update_coordinator import UpdateFailed
from yarl import URL

from cellar_tracker.cellar_data import WineCellarData, async_fetch_inventory_payload
from conftest import ConfigEntry, FakeHass, FakeSession

PASSWORD = "hunter2-do-not-leak"
USERNAME = "alice"

REQUEST_URL = URL(
    "https://www.cellartracker.com/xlquery.asp"
    f"?User={USERNAME}&Password={PASSWORD}&Table=Inventory"
)


def response_error(status: int) -> aiohttp.ClientResponseError:
    """The error aiohttp's raise_for_status() produces - URL and all."""
    info = aiohttp.RequestInfo(REQUEST_URL, "GET", (), REQUEST_URL)
    return aiohttp.ClientResponseError(info, (), status=status, message="Boom")


def build(**session_kwargs) -> WineCellarData:
    hass = FakeHass()
    hass.session = FakeSession(**session_kwargs)
    entry = ConfigEntry(data={"username": USERNAME, "password": PASSWORD})
    return WineCellarData(hass, entry)


def leak_surface(err: BaseException) -> str:
    """Everything a logger, a traceback or a diagnostics dump could render."""
    parts = [str(err), repr(err)]
    parts.extend(traceback.format_exception(type(err), err, err.__traceback__))
    cause = err.__cause__
    while cause is not None:
        parts.extend([str(cause), repr(cause)])
        cause = cause.__cause__
    return "\n".join(parts)


# --------------------------------------------------------------------------
# The premise: the raw aiohttp error really does carry the secret
# --------------------------------------------------------------------------
def test_the_hazard_is_real():
    """If this ever fails, aiohttp changed and the rest of this file is moot."""
    err = response_error(429)
    assert PASSWORD in str(err)
    assert PASSWORD in repr(err)


# --------------------------------------------------------------------------
# The fetch must not re-raise anything that carries it
# --------------------------------------------------------------------------
@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
def test_an_http_error_is_reraised_without_the_url(status):
    hass = FakeHass()
    hass.session = FakeSession(raise_for_status=response_error(status))

    with pytest.raises(CannotConnect) as caught:
        asyncio.run(async_fetch_inventory_payload(hass, USERNAME, PASSWORD))

    assert PASSWORD not in leak_surface(caught.value)


def test_the_status_survives_even_though_the_url_does_not():
    """Redaction must not cost us the diagnostic value of the failure."""
    hass = FakeHass()
    hass.session = FakeSession(raise_for_status=response_error(429))

    with pytest.raises(CannotConnect) as caught:
        asyncio.run(async_fetch_inventory_payload(hass, USERNAME, PASSWORD))

    assert "429" in str(caught.value)


def test_the_cause_chain_is_severed():
    """`from None`, not `from err`: unreachable beats merely unformatted."""
    hass = FakeHass()
    hass.session = FakeSession(raise_for_status=response_error(500))

    with pytest.raises(CannotConnect) as caught:
        asyncio.run(async_fetch_inventory_payload(hass, USERNAME, PASSWORD))

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_a_transport_error_names_its_type_and_nothing_else():
    hass = FakeHass()
    hass.session = FakeSession(error=aiohttp.ClientConnectorError(None, OSError("refused")))

    with pytest.raises(CannotConnect) as caught:
        asyncio.run(async_fetch_inventory_payload(hass, USERNAME, PASSWORD))

    assert PASSWORD not in leak_surface(caught.value)


# --------------------------------------------------------------------------
# ...and nothing downstream reintroduces it
# --------------------------------------------------------------------------
def test_the_coordinator_update_failure_is_clean():
    coordinator = build(raise_for_status=response_error(429))

    with pytest.raises(UpdateFailed) as caught:
        asyncio.run(coordinator._async_update_data())

    assert PASSWORD not in leak_surface(caught.value)


def test_what_the_coordinator_logs_is_clean(caplog):
    coordinator = build(raise_for_status=response_error(503))

    with caplog.at_level("DEBUG"), pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())

    assert PASSWORD not in caplog.text


def test_the_config_flow_check_logs_nothing_sensitive(caplog):
    """Setup and reauth run the same fetch while a user watches a spinner."""
    from cellar_tracker.config_flow import CellarTrackerConfigFlow

    flow = CellarTrackerConfigFlow()
    flow.hass = FakeHass()
    flow.hass.session = FakeSession(raise_for_status=response_error(429))

    with caplog.at_level("DEBUG"):
        errors = asyncio.run(flow._async_check_credentials(USERNAME, PASSWORD))

    assert errors == {"base": "cannot_connect"}
    assert PASSWORD not in caplog.text
