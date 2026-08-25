[![CI](https://github.com/GuvHas/cellartracker/actions/workflows/ci.yml/badge.svg)](https://github.com/GuvHas/cellartracker/actions/workflows/ci.yml)
[![hacs](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

# CellarTracker for Home Assistant

Brings your [CellarTracker](https://cellartracker.com) wine cellar into Home Assistant: summary
sensors for bottle count and cellar value, plus a searchable, sortable dashboard of every bottle.

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
- [Troubleshooting and FAQ](#troubleshooting-and-faq)
- [Development](#development)

---

## Overview

The integration is a standard modern custom component: UI config flow, a
`DataUpdateCoordinator` for polling, and entities grouped under a device per account.

**How it fetches data.** It uses the [`cellartracker`](https://pypi.org/project/cellartracker/)
library, which calls CellarTracker's `xlquery.asp` export endpoint and requests the **`Inventory`
table in tab-separated format**. One HTTP request per refresh returns every bottle you own, with
66 columns each. The blocking call runs in an executor with a 60-second bound, and parsing runs
in an executor too, so neither touches Home Assistant's event loop.

**Features**

- Two summary sensors — total bottle count and total cellar value — with proper device classes,
  units and state classes, so both feed Home Assistant's long-term statistics.
- A selectable currency, so the value sensor is denominated correctly.
- A diagnostic status sensor.
- A REST endpoint exposing full per-bottle detail, and a self-contained dashboard page that
  renders it as a searchable, sortable table with drink-window highlighting.
- Reauthentication: if your password changes, Home Assistant prompts you to re-enter it rather
  than silently failing.
- Multiple CellarTracker accounts, each as its own device.
- Upstream error pages are rejected rather than being recorded as a genuine zero, so an outage
  cannot punch a hole in your cellar-value history.

---

## What gets created

Adding the integration creates **one device per account** with **three entities**. It does not
create an entity per bottle — see [Bottle-level data](#bottle-level-data) for why, and for how to
reach that data.

| Entity | Example | Unit | Device class | State class |
|---|---|---|---|---|
| Total bottles | `142` | `bottles` | — | `measurement` |
| Total value | `9812.50` | your chosen currency | `monetary` | `total` |
| Status | `Connected` | — | — | diagnostic |

### Entity IDs

The device is named after the account, so entity IDs follow the account name:

```
sensor.<account>_total_bottles
sensor.<account>_total_value
sensor.<account>_status
```

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
GET /api/cellartracker/inventory     # every bottle, as JSON
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

1. Open **HACS** in Home Assistant.
2. Click the **⋮** menu (top right) → **Custom repositories**.
3. Add:
   - **Repository:** `https://github.com/GuvHas/cellartracker`
   - **Type:** `Integration`
4. Click **Add**, then close the dialog.
5. Search HACS for **CellarTracker** and click **Download**.
6. **Restart Home Assistant.**
7. Copy the dashboard page into place (optional, needed for the bottle table):

   ```
   custom_components/www/cellar.html  →  <config>/www/cellar.html
   ```

   Create `<config>/www/` if it does not exist. Files there are served at `/local/`, so the page
   ends up at `/local/cellar.html`.

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

3. Copy the dashboard page (optional):

   ```
   custom_components/www/cellar.html  →  <config>/www/cellar.html
   ```

4. Your config directory should now contain:

   ```
   <config>/
   ├── custom_components/
   │   └── cellar_tracker/
   │       ├── __init__.py
   │       ├── cellar_data.py
   │       ├── config_flow.py
   │       ├── const.py
   │       ├── manifest.json
   │       ├── sensor.py
   │       ├── strings.json
   │       ├── views.py
   │       └── translations/
   │           └── en.json
   └── www/
       └── cellar.html
   ```

5. **Restart Home Assistant.**

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

### Multiple accounts

Add the integration more than once. Each account becomes its own device, named after that
account. When more than one is configured, the REST endpoints require you to say which one you
mean (see below); with a single account nothing changes.

### A note on the refresh interval

The default is deliberately conservative. A cellar changes slowly, the export endpoint returns
your entire inventory in one request, and CellarTracker is a small service run for enthusiasts —
polling it every minute is neither useful nor neighbourly. Fifteen minutes is the enforced floor.

---

## The dashboard

Add an **iframe card** pointing at the page you copied to `www/`:

```yaml
type: iframe
url: /local/cellar.html
aspect_ratio: 100%
title: My Wine Collection
```

The page reads your live Home Assistant session from the parent frame, so it needs no token or
credential of its own. Open it embedded in a dashboard, not as a standalone browser tab.

It gives you search across wine name, location and bin; sortable columns; bottle values formatted
in your configured currency; links to each wine on CellarTracker; drink-window colouring (green =
ready, red = too early or past); and light/dark theme following your Home Assistant theme.

**With more than one account configured**, name the one you want:

```yaml
type: iframe
url: /local/cellar.html?entry_id=YOUR_ENTRY_ID
aspect_ratio: 100%
title: Alice's Cellar
```

The entry ID is the last path segment of the URL when you open the integration under
**Settings → Devices & Services**. If you omit it with several accounts configured, the page
tells you which IDs exist rather than guessing.

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
  - entity: sensor.<account>_status
    name: Connection
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

Drink-window filtering happens in the dashboard page instead, which colours `BeginConsume` and
`EndConsume` per bottle: green when the year is in range, red when the bottle is too young or
past its window. Sort by either column to bring the relevant bottles together.

If you want drink-window data in Lovelace proper, the missing piece is per-bottle entities — see
[Bottle-level data](#bottle-level-data) for why they are not created by default. Please open an
issue if this matters to you; it is a reasonable feature to add behind an opt-in, given the
recorder cost is the user's to accept.

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

### The dashboard says "Not authorised"

The page could not read your Home Assistant session. Almost always this means it was opened as a
standalone browser tab rather than embedded in an iframe card. Use the card described in
[The dashboard](#the-dashboard).

### The dashboard says several accounts are configured

Expected with more than one account. Add `?entry_id=...` to the iframe URL. The error message
lists the available IDs.

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
python -m pytest          # 134 tests
ruff check .
```

The test suite stubs the handful of `homeassistant` symbols the integration imports rather than
depending on `pytest-homeassistant-custom-component`, so it installs in seconds and runs in under
a second. The dashboard tests execute `cellar.html`'s real script under Node, so install Node to
run them — they skip if it is absent.

CI runs the suite on Python 3.12 and 3.13, plus `ruff`, `hassfest` and HACS validation.

### Known limitation

The upstream `cellartracker` library calls `requests.get()` without a `timeout`. This integration
bounds how long Home Assistant waits, so a hung request fails cleanly and retries on schedule, but
it cannot cancel a worker thread already blocked in the library. A fully robust fix needs
`timeout=` upstream.

---

## Example

<img width="760" height="436" alt="cellar_image" src="https://github.com/user-attachments/assets/fa262a19-2725-4f64-bc7b-1f7c7535b510" />
