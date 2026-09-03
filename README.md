[![CI](https://github.com/GuvHas/cellartracker/actions/workflows/ci.yml/badge.svg)](https://github.com/GuvHas/cellartracker/actions/workflows/ci.yml)
[![hacs](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

# CellarTracker for Home Assistant

Brings your [CellarTracker](https://cellartracker.com) wine cellar into Home Assistant: summary
sensors for bottle count, cellar value and drinking windows, plus a dashboard that filters every
bottle down to the ones you can drink tonight.

> **Disclaimer**
> This is a personal project. It is not affiliated with, connected to, or endorsed by
> CellarTracker! LLC. "CellarTracker!" is a trademark of CellarTracker! LLC.

---

## Contents

- [Overview](#overview)
- [What gets created](#what-gets-created)
- [Bottle-level data](#bottle-level-data)
- [Installation via HACS](#installation-via-hacs)
- [Manual installation](#manual-installation)
- [Configuration](#configuration)
- [The dashboard](#the-dashboard)
- [Lovelace and automation examples](#lovelace-and-automation-examples)
- [Lighting the rack](#lighting-the-rack)
- [Troubleshooting and FAQ](#troubleshooting-and-faq)
- [Development](#development)
- [License](#license)

---

## Overview

The integration is a standard modern custom component: UI config flow, a
`DataUpdateCoordinator` for polling, and entities grouped under a device per account.

**How it fetches data.** One request per refresh to CellarTracker's `xlquery.asp` export
endpoint for the **`Inventory` table in tab-separated format**, returning every bottle you own
with 66 columns each. The request uses Home Assistant's shared `aiohttp` session under a
60-second `asyncio.timeout`, so a hung server is cancelled cleanly rather than parking a
worker thread. Parsing runs in an executor, so the event loop is never blocked. The
[`cellartracker`](https://pypi.org/project/cellartracker/) library supplies the endpoint URL
and error semantics; its own `requests`-based transport sets no timeout and is not used.

**Features**

- Two summary sensors — total bottle count and total cellar value — with proper device classes,
  units and state classes, so both feed Home Assistant's long-term statistics.
- Two drink-window sensors — how many bottles are ready to drink, and how many are past their
  window — derived at poll time, so they cost nothing and add no entity per bottle.
- A selectable currency, so the value sensor is denominated correctly.
- A diagnostic sensor reporting when the cellar last synchronised.
- A REST endpoint exposing full per-bottle detail, and a self-contained dashboard page that
  filters it by drinking window, searches it across five fields and shows each bottle's position
  in its window. The page ships with the integration and is served from it, so there is nothing
  to copy into `<config>/www`.
- Reauthentication: if your password changes, Home Assistant prompts you to re-enter it rather
  than silently failing.
- One account per installation, enforced by the config flow, so there is no ambiguity
  about which cellar an entity or endpoint refers to.
- Upstream error pages are rejected rather than being recorded as a genuine zero, so an outage
  cannot punch a hole in your cellar-value history.

---

## What gets created

Adding the integration creates **one device per account** with **five entities**. It does not
create an entity per bottle — see [Bottle-level data](#bottle-level-data) for why, and for how to
reach that data.

| Entity | Example | Unit | Device class | State class |
|---|---|---|---|---|
| Total bottles | `142` | `bottles` | — | `measurement` |
| Total value | `9812.50` | your chosen currency | `monetary` | `total` |
| Ready to drink | `37` | `bottles` | — | `measurement` |
| Past drinking window | `4` | `bottles` | — | `measurement` |
| Last synchronised | `2026-08-28 09:30:00` | — | `timestamp` | diagnostic |

Upgrading from 0.0.17 or earlier: the diagnostic entity that reported `Connected` now reports
when the cellar last synchronised. It keeps its entity ID, so nothing has to be repointed. Its old
value never changed once the integration was running, so nothing could have been triggering on it.

### Entity IDs

The device is named after the account, so entity IDs follow the account name:

```
sensor.<account>_total_bottles
sensor.<account>_total_value
sensor.<account>_ready_to_drink
sensor.<account>_past_drinking_window
sensor.<account>_last_synchronised
```

That third ID is what a **fresh install** gets. An install that predates 0.0.18 keeps
`sensor.<account>_status`, because Home Assistant assigns an entity ID once, at first
registration, and never rewrites it. Both point at the same entity; only the name differs.

**If you installed before v0.0.15**, your entity IDs were generated when the entities were first
registered and Home Assistant keeps them — they will still be `sensor.cellartracker_total_bottles`
and friends. Existing dashboards and automations keep working; only the display names change.
Check **Settings → Devices & Services → CellarTracker → entities** for the exact IDs on your
system, and use those in the examples below.

---

## Bottle-level data

Per-bottle detail is exposed through an authenticated REST endpoint rather than as entities or
state attributes:

```
GET /api/cellartracker/inventory                # every bottle, as JSON
GET /api/cellartracker/inventory?view=compact   # the same bottles, ten columns
GET /api/cellartracker/settings      # the configured currency and its symbol
```

**Why not one entity per bottle?** Home Assistant's recorder writes a row for every state and
attribute change of every entity. A 500-bottle cellar would mean 500 entities whose valuations
drift constantly, which bloats the database for data that is reference material rather than
something you automate on. Putting the full list in a state attribute has the same problem, only
worse — attributes are recorded with every state write.

Each bottle in the response carries CellarTracker's own column names. The ones the dashboard uses:

| Field | Meaning |
|---|---|
| `iWine` | CellarTracker's wine ID — links to the wine's page |
| `Wine` | Wine name |
| `Vintage` | Vintage year, `0` for non-vintage |
| `Producer` | Producer name |
| `Location` / `Bin` | Where the bottle is stored |
| `Barcode` | The bottle's barcode, if you have scanned one |
| `Size` | Bottle size, e.g. `750ml` |
| `Valuation` | Current value, coerced to a float (`0.0` if unparseable) |
| `Price` | What you paid |
| `PurchaseDate` | Purchase date |
| `BeginConsume` / `EndConsume` | **Drink window** — the first and last recommended year |
| `Country` / `Region` / `SubRegion` / `Appellation` | Origin |
| `Type` / `Color` / `Varietal` / `MasterVarietal` | Style |
| `BottleNote`, `CNotes`, `PNotes` | Notes |
| `WA`, `WS`, `IWC`, `JR`, … | Critic scores |
| `unique_bottle_id` | Added by this integration: a stable per-bottle identifier |

The response contains all 66 columns CellarTracker returns; the table above is the useful subset.

> The drink-window columns are named `BeginConsume` and `EndConsume`, not `begin_drink` /
> `end_drink`. They hold years as strings, e.g. `"2018"`, and are empty when CellarTracker has no
> recommendation.

---

## Installation via HACS

**Requires Home Assistant 2024.11 or newer** — 2024.7 added the static-path API the integration
uses to serve its dashboard page, and 2024.11 added the `config_entry` argument its data
coordinator now passes.

1. Open **HACS** in Home Assistant.
2. Click the **⋮** menu (top right) → **Custom repositories**.
3. Add:
   - **Repository:** `https://github.com/GuvHas/cellartracker`
   - **Type:** `Integration`
4. Click **Add**, then close the dialog.
5. Search HACS for **CellarTracker** and click **Download**.
6. **Restart Home Assistant.**

That is the whole installation. There is no file to copy: the dashboard page ships inside the
integration and Home Assistant serves it at `/cellartracker/cellar.html` as soon as the
integration loads.

Then continue to [Configuration](#configuration).

---

## Manual installation

1. Download or clone this repository.
2. Copy the integration folder into your Home Assistant config directory:

   ```
   custom_components/cellar_tracker/  →  <config>/custom_components/cellar_tracker/
   ```

   Note the directory is `cellar_tracker`, with an underscore — it must match the integration's
   domain exactly.

3. Your config directory should now contain:

   ```
   <config>/
   └── custom_components/
       └── cellar_tracker/
           ├── __init__.py
           ├── cellar_data.py
           ├── config_flow.py
           ├── const.py
           ├── manifest.json
           ├── sensor.py
           ├── strings.json
           ├── views.py
           ├── translations/
           │   └── en.json
           └── www/
               └── cellar.html
   ```

   Copy the folder whole — `www/cellar.html` is the dashboard page, and the integration serves it
   from there. Nothing goes into `<config>/www`.

4. **Restart Home Assistant.**

---

## Configuration

All configuration is through the UI. There is nothing to put in `configuration.yaml`.

1. Go to **Settings → Devices & Services**.
2. Click **+ Add Integration** (bottom right).
3. Search for **CellarTracker** and select it.
4. Fill in the form:

   | Field | Notes |
   |---|---|
   | **Username** | Your CellarTracker username |
   | **Password** | Your CellarTracker password |
   | **Seconds between refreshes** | Default `21600` (6 hours). Minimum `900` (15 minutes). |
   | **Currency** | The currency your cellar value is reported in |

5. Click **Submit**. Credentials are verified against CellarTracker before the entry is created,
   so a mistake is reported immediately rather than after the first failed poll.

### Changing settings later

**Settings → Devices & Services → CellarTracker → Configure** lets you change the refresh
interval and currency. The integration reloads automatically.

**Changing your password** is handled by re-authentication rather than by an editable form: once
CellarTracker starts rejecting the stored password, the integration flags it and Home Assistant
surfaces a **Re-authenticate** prompt on the CellarTracker card in Devices & Services. Enter the
new password there and only the password is replaced — the refresh interval, currency, entity IDs
and history all stay as they were.

There is no proactive "change my password now" form. If you would rather not wait for the next
refresh to notice, use **⋮ → Reload** on the integration to trigger one immediately.

### One account per installation

The config flow allows a single CellarTracker account. Adding it a second time aborts rather
than creating a duplicate. To switch accounts, delete the existing entry and add it again.

### A note on the refresh interval

The default is deliberately conservative. A cellar changes slowly, the export endpoint returns
your entire inventory in one request, and CellarTracker is a small service run for enthusiasts —
polling it every minute is neither useful nor neighbourly. Fifteen minutes is the enforced floor.

---

## The dashboard

The page is served by the integration itself, from wherever the integration was installed. Add an
**iframe card** pointing at it:

```yaml
type: iframe
url: /cellartracker/cellar.html
aspect_ratio: 100%
title: My Wine Collection
```

The page reads your live Home Assistant session from the parent frame, so it needs no token or
credential of its own. Open it embedded in a dashboard, not as a standalone browser tab.

### What it gives you

**Four filter chips**, each carrying its count, so a 150-bottle cellar becomes a short list:

| Chip | Shows |
|---|---|
| **All wines** | Everything, including bottles with no recorded window |
| **Ready to drink** | The current year falls inside the drinking window |
| **Past window** | The window ended before this year |
| **Needs aging** | The window has not opened yet |

The Ready and Past counts are the same numbers the sensors report — they are checked against each
other by the test suite, so the chip and the sensor card beside it cannot disagree.

**Search** across wine name, vintage, location, bin and barcode. Every word has to match, so
`chianti 2023` narrows rather than finding nothing.

**Sort** by wine, vintage, value, drink-by year, bin or location, in either direction. Bottles
with nothing recorded for the chosen column sort last rather than heading the list.

**Each bottle** shows its name, vintage, location and bin, its value in your configured currency,
and a bar showing where this year sits inside its drinking window:

| Label | Meaning |
|---|---|
| **Ready** (green) | Inside the drinking window |
| **Drink this year** (amber) | The final year of the window — urgent, not expired |
| **Past window** (red) | The window ended before this year |
| **Needs aging** (blue) | Not open yet |
| **No window** (grey) | CellarTracker has no recommendation for this bottle |

Tapping a bottle opens a drawer with its barcode, full window, value, a **Copy bin** button and a
link to the wine on CellarTracker.

The page follows your Home Assistant light/dark theme, and every control is sized for a thumb.

The card needs no account parameter — one account is supported per installation, so the
endpoints have nothing to disambiguate. A stale `?entry_id=...` left over from a card configured
against v0.0.16 is accepted and ignored, so those cards keep working unchanged.

**Upgrading from before v0.0.16?** You once had to copy the page into `<config>/www` yourself.
That copy still works — `/local/cellar.html` is Home Assistant's own static mount and this change
does not touch it — so existing cards keep rendering. It is a stale copy, though: it will not pick
up fixes to the page. Point your card at `/cellartracker/cellar.html` and delete
`<config>/www/cellar.html` when convenient.

---

## Lovelace and automation examples

Replace `<account>` with your device name — or with `cellartracker` if you installed before
v0.0.15. Check the exact entity IDs under **Settings → Devices & Services → CellarTracker**.

### Summary card

```yaml
type: entities
title: Wine Cellar
entities:
  - entity: sensor.<account>_total_bottles
    name: Bottles
  - entity: sensor.<account>_total_value
    name: Cellar value
  - entity: sensor.<account>_ready_to_drink
    name: Ready to drink
  - entity: sensor.<account>_last_synchronised
    name: Last synchronised
```

### Markdown card with an average

```yaml
type: markdown
content: >
  ## 🍷 The Cellar

  **{{ states('sensor.<account>_total_bottles') }}** bottles worth
  **{{ states('sensor.<account>_total_value') }}
  {{ state_attr('sensor.<account>_total_value', 'unit_of_measurement') }}**

  {% set bottles = states('sensor.<account>_total_bottles') | int(0) %}
  {% set value = states('sensor.<account>_total_value') | float(0) %}
  {% if bottles > 0 %}
  Average bottle value: **{{ (value / bottles) | round(2) }}**
  {% else %}
  The cellar is empty.
  {% endif %}
```

### Cellar value over time

The value sensor is `device_class: monetary` with `state_class: total`, so Home Assistant records
long-term statistics for it:

```yaml
type: statistics-graph
title: Cellar value
entities:
  - sensor.<account>_total_value
stat_types:
  - mean
days_to_show: 365
period: day
```

### Automation: the bottle count changed

```yaml
automation:
  - alias: "Cellar inventory changed"
    triggers:
      - trigger: state
        entity_id: sensor.<account>_total_bottles
    conditions:
      # Ignore startup and unavailability, and only fire on a real change.
      - condition: template
        value_template: >
          {{ trigger.from_state.state not in ['unknown', 'unavailable', none]
             and trigger.to_state.state not in ['unknown', 'unavailable', none]
             and trigger.from_state.state != trigger.to_state.state }}
    actions:
      - action: notify.persistent_notification
        data:
          title: "Wine cellar updated"
          message: >
            {% set before = trigger.from_state.state | int(0) %}
            {% set after = trigger.to_state.state | int(0) %}
            {% if after > before %}
              {{ after - before }} bottle(s) added — {{ after }} in the cellar.
            {% else %}
              {{ before - after }} bottle(s) consumed — {{ after }} remaining.
            {% endif %}
    mode: single
```

### Automation: the cellar value moved sharply

```yaml
automation:
  - alias: "Cellar value moved more than 10%"
    triggers:
      - trigger: state
        entity_id: sensor.<account>_total_value
    conditions:
      - condition: template
        value_template: >
          {% set before = trigger.from_state.state | float(0) %}
          {% set after = trigger.to_state.state | float(0) %}
          {{ before > 0 and (after - before) | abs / before > 0.1 }}
    actions:
      - action: notify.persistent_notification
        data:
          title: "Cellar revaluation"
          message: >
            Value moved from {{ trigger.from_state.state }} to
            {{ trigger.to_state.state }}.
    mode: single
```

### Automation: alert if the integration stops updating

```yaml
automation:
  - alias: "CellarTracker is not responding"
    triggers:
      - trigger: state
        entity_id: sensor.<account>_total_bottles
        to: "unavailable"
        for: "12:00:00"
    actions:
      - action: notify.persistent_notification
        data:
          title: "CellarTracker unavailable"
          message: "No successful refresh for 12 hours. Check the logs."
    mode: single
```

### About drink-window cards

A common request is an `auto-entities` or Markdown card listing wines currently in their drink
window. **That is not possible with the entities this integration creates**, because there are no
per-bottle entities to filter — `auto-entities` works over the entity registry, and bottles are
not in it.

There are two answers that do not need per-bottle entities.

**For a count**, use the sensors: `sensor.<account>_ready_to_drink` and
`sensor.<account>_past_drinking_window` are ordinary numeric entities, so they work in any card,
template or automation.

**For the actual list**, use the dashboard page and its **Ready to drink** chip. That is what the
chips are for, and the counts match the sensors exactly.

If you want the bottles themselves in Lovelace proper, the missing piece is per-bottle entities —
see [Bottle-level data](#bottle-level-data) for why they are not created by default. Please open
an issue if this matters to you; it is a reasonable feature to add behind an opt-in, given the
recorder cost is the user's to accept.

---

## Lighting the rack

If your bottles live in a rack you can put LEDs behind, the cellar can answer "what should I open"
in the room rather than on a screen. `examples/` holds a working pair of configurations for that:

| File | What it is |
|---|---|
| `examples/esphome/winerack1led.yaml` | An ESPHome node driving one WS2812 strand per rack row, with a block of LEDs behind each bin |
| `examples/home_assistant/wine_rack_leds.yaml` | The Home Assistant package that turns this integration's inventory into what the node paints |

The rack is a 13 x 13 grid: rows **A**-**M**, bins **1**-**13**, addressed the way CellarTracker
addresses them — `Location` is the rack, `Bin` is the slot, so bin `A7` is row A, column 7. Both
files are written for that shape and say where to change it.

### What it shows

Every lit bin carries the same drinking-window state the dashboard paints, so the rack and
`/cellartracker/cellar.html` cannot tell you different things about the same bottle:

| Bin | Meaning |
|---|---|
| Green | **Ready** — this year is inside the drinking window |
| Amber | **Drink this year** — the final year of the window |
| Red | **Past window** — the window closed before this year |
| Blue | **Needs aging** — the window has not opened yet |
| Dim white | **No window** — CellarTracker has no recommendation for that bottle |
| Dark | No bottle in that bin |

A bin usually holds several bottles. It shows the one that most wants dealing with: past, then
drink-this-year, then ready, then aging, then a bottle with no window at all.

There is also a **locator** — one bin lit on its own with the rest of the rack dark, for finding a
particular bottle. Copy a bin from the dashboard's bottle drawer, run the `wine_rack_1_locate`
script, and walk to the rack. The overview comes back when the hold expires, and a poll that lands
while you are looking does not steal the answer from you.

### How the two halves talk

The node exposes four actions, and knows nothing about wine:

| Action | Takes |
|---|---|
| `esphome.winerack1led_light_rack` | `grid`: 169 state characters, row-major — the whole rack in one call |
| `esphome.winerack1led_light_row` | `row`: `A`-`M`, `states`: 13 characters |
| `esphome.winerack1led_light_bin` | `bin_id`: `A7`, `r`/`g`/`b`, `seconds` to hold it |
| `esphome.winerack1led_clear_all` | nothing |

A state character per bin — `R` ready, `U` urgent, `P` past, `A` aging, `N` no window, `.` empty —
means the whole rack fits in one 169-character string, which is both a single action call and
small enough to be an ordinary sensor state. The package builds that string from
`/api/cellartracker/inventory?view=compact` with the same rule
[`_drink_window_counts`](custom_components/cellar_tracker/cellar_data.py) and the dashboard use,
and pushes it when the cellar syncs rather than on a timer.

### Before you build it

Three things are worth knowing before you cut LED strip:

- **The endpoint is authenticated**, so Home Assistant needs a long-lived access token to read its
  own API. The package expects it in `secrets.yaml`.
- **Thirteen strands is more than a classic ESP32 has timing hardware for** — eight RMT channels
  and two I2S buses is ten. That bounds how many strands can transmit at once, not how many you
  can have, so the config drives them with FastLED, which takes a channel per strand and hands it
  back for the next one. `neopixelbus` cannot: it holds a channel per strand for the life of the
  node and runs out at ten.
- **Power.** 1014 LEDs at the palette in the file is a few amps, and considerably more if you
  brighten it. The file shows the arithmetic.

---

## Troubleshooting and FAQ

### "Invalid username or password" when adding the integration

Credentials are checked against CellarTracker before the entry is created. Confirm you can log in
at [cellartracker.com](https://cellartracker.com) with the same details. The username is your
CellarTracker **username**, not the email address you sign in with, if those differ.

### Home Assistant is asking me to re-authenticate

CellarTracker rejected the stored credentials — usually a password change. Enter the new password
in the prompt. Nothing else needs updating; only the password is replaced.

### The sensors show "unavailable"

A refresh failed. The integration keeps the last good values and marks the entities unavailable
rather than publishing a wrong number. Check **Settings → System → Logs** for `cellar_tracker`:

- *"Cannot reach CellarTracker"* — network or an outage upstream. It retries on the next cycle.
- *"unrecognised row(s) with no 'iWine' column"* — CellarTracker returned something that was not
  inventory data, typically a maintenance or error page. It recovers on its own.
- *"returned no inventory rows but the cellar previously held N bottles"* — a zero reading right
  after a stocked cellar is treated as an error the first time. **If you genuinely emptied your
  cellar, the next refresh accepts it** and the sensors go to zero.

### Can I poll more often than every 15 minutes?

No — 900 seconds is enforced. Each refresh downloads your entire inventory, and CellarTracker is
a small service. If you need a value right now, use **⋮ → Reload** on the integration.

### The dashboard page 404s

Check the URL: it is `/cellartracker/cellar.html`, served by the integration. If Home Assistant
returns 404 there, the integration has not finished loading — look under **Settings → Devices &
Services** — or the page is missing from the install, which the log reports as
`Dashboard page ... is missing`. Re-download the integration in HACS, or re-copy the
`cellar_tracker` folder whole if you installed manually.

`/local/cellar.html` is the pre-v0.0.16 location and only works if you copied the page into
`<config>/www` yourself. It is not created for you.

### The dashboard says "Not authorised"

The page could not read your Home Assistant session. Almost always this means it was opened as a
standalone browser tab rather than embedded in an iframe card. Use the card described in
[The dashboard](#the-dashboard). The page is deliberately unauthenticated static content; the data
behind it is not, so the API calls it makes need your session.

### Can I add a second CellarTracker account?

No. One account per installation is enforced: a second attempt aborts with "CellarTracker
is already configured". Remove the existing entry under **Settings → Devices & Services**
first if you want to switch accounts.

### Passing `?token=` in the dashboard URL

Deprecated. It still works, but a Home Assistant long-lived token grants full account access and
never expires, so a URL carrying one leaks it into browser history, server logs and screenshots.
The page now moves any token it finds into session storage and strips it from the address bar.
Embedded as an iframe card, no token is needed at all.

### My cellar value looks wrong

The currency is a display setting — it labels the number CellarTracker reports, it does not
convert it. Set it to match the currency your CellarTracker account values bottles in, under
**Configure**. Bottles whose `Valuation` cannot be parsed count as `0`, so a wine CellarTracker
has no valuation for contributes nothing rather than breaking the total.

### Where is the bottle list in the entity attributes?

Deliberately not there — see [Bottle-level data](#bottle-level-data). Use
`/api/cellartracker/inventory`.

### Enabling debug logging

```yaml
logger:
  default: warning
  logs:
    custom_components.cellar_tracker: debug
    cellartracker: debug
```

---

## Development

```bash
pip install -r requirements_test.txt
python -m pytest
ruff check .
```

The test suite stubs the handful of `homeassistant` symbols the integration imports rather than
depending on `pytest-homeassistant-custom-component`, so it installs in seconds and runs in a few.
The dashboard tests execute `cellar.html`'s real script under Node, so install Node to run them —
they skip if it is absent.

Type checking needs Home Assistant itself, which the test suite deliberately does not install:

```bash
python3.13 -m venv .typecheck
.typecheck/bin/pip install -r requirements_mypy.txt
.typecheck/bin/python -m mypy
```

Running `mypy` against an interpreter without Home Assistant is worse than not running it: every
`homeassistant.*` import resolves to `Any`, and the check passes over code it never looked at.
The configuration refuses to do that, so it will fail loudly rather than mislead you.

CI runs the suite on Python 3.12 and 3.13, plus `ruff`, `mypy`, `hassfest` and HACS validation.

### Cutting a release

Releases are published by `.github/workflows/release.yml`, which refuses to tag a commit whose
`manifest.json` version disagrees with the release, or whose tests and lint do not pass.

1. Bump `version` in `custom_components/cellar_tracker/manifest.json`.
2. Optionally write `release_notes/<version>.md`. If it exists the workflow uses it verbatim;
   otherwise GitHub generates notes from the commit history. Write them by hand whenever a
   version changes how the integration is installed or configured — 0.0.16 moved the dashboard
   URL, which no generated changelog would have made obvious.
3. Merge to `main`, then either push the tag (`git tag 0.0.17 && git push origin 0.0.17`) or run
   **Actions → Release → Run workflow** and enter the version. The second path creates the tag
   for you, which is what to use when your client cannot push tag refs.

Tags are bare version numbers with no `v` prefix, optionally with a single-letter suffix
(`0.0.13b`), matching every release since 0.0.10. Re-running a dispatch for a version whose tag
already exists is safe: the workflow checks that tag out and validates it, rather than validating
the branch and publishing the tag.

### Why the library's transport is not used

The `cellartracker` library calls `requests.get(url, params)` with no `timeout=`
([`api.py`](https://github.com/mathroule/cellartracker/blob/master/cellartracker/api.py)), so the
socket has no deadline. Running that on an executor thread means an application-level timeout can
stop Home Assistant *waiting*, but cannot interrupt the worker: `concurrent.futures` has no way to
cancel a thread that is already running, so it stays in `recv()` until the OS gives up. For a
server that accepts a connection and then never replies, that is the TCP keepalive interval —
7200 seconds by default — with the account password sitting in the thread's stack frame.

So the integration does its own HTTP with Home Assistant's shared `aiohttp` session, where
cancellation genuinely cancels and no thread is involved. The library still supplies the endpoint
URL, the not-logged-in marker, the table and format enums, and the exception types: it owns the
contract, just not the transport.

**Possible future contribution.** Adding `timeout=` to `cellartracker`'s `api.py` would fix this
at the root for every consumer — roughly:

```python
DEFAULT_TIMEOUT = 60

def execute(self, url=BASE_URL, params={}, timeout=DEFAULT_TIMEOUT):
    ...
    reponse = requests.get(url, params, timeout=timeout)
```

That is worth submitting upstream if anyone feels like it, but **this integration does not depend
on it** — it no longer calls that code path at all. Noted here so the reasoning is not lost.

---

## License

[MIT](LICENSE). "CellarTracker!" is a trademark of CellarTracker! LLC; this project is not
affiliated with them.

---

## Example

<img width="1147" height="922" alt="wine" src="https://github.com/user-attachments/assets/ab25a12b-4cb7-493b-999b-f062be6ebfd2" />

