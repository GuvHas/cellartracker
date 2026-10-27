"""What the LED racks are showing, as far as the integration has asked.

The integration never talks to the boards, so this is what it last asked them
to show, not a reading from them. It is enough for the one question the rack
automations need answered: may a sync, a grid change or a board coming back
repaint the overview, or would that light a rack that is meant to be dark or
wipe a highlight someone is looking at?

``overview``  - every rack shows the cellar; background repaints are welcome.
``highlight`` - the dashboard asked for a filter or a search; leave it alone.
``off``       - the racks went dark after being left alone; keep them dark.

The racks start dark when they are set to turn off by themselves, and on the
overview otherwise, which is how they behaved before there was a choice.
"""

from __future__ import annotations

from typing import Literal

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN

Showing = Literal["overview", "highlight", "off"]

# Sent whenever `showing` changes, so the grid sensors can say so.
SIGNAL_RACK_LIGHTS = f"{DOMAIN}_rack_lights"

_SHOWING = f"{DOMAIN}_rack_lights_showing"


def showing(hass: HomeAssistant, idle_off: int) -> Showing:
    """What the racks were last asked to show."""
    current: Showing | None = hass.data.get(_SHOWING)
    if current is not None:
        return current
    return "off" if idle_off else "overview"


def set_showing(hass: HomeAssistant, value: Showing) -> None:
    if hass.data.get(_SHOWING) != value:
        hass.data[_SHOWING] = value
        async_dispatcher_send(hass, SIGNAL_RACK_LIGHTS)
