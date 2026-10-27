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
- [Resilience](#resilience)
- [Actions and events](#actions-and-events)
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
- **Survives an outage across a restart.** The last inventory that parsed is kept on disk and
  shown if Home Assistant restarts while CellarTracker is unreachable, instead of every sensor
  reading unavailable. See [Resilience](#resilience).
- **Backs off politely.** HTTP 429 and 5xx slow the poll down exponentially, with jitter, and the
  configured schedule returns by itself once CellarTracker answers.
- **Two actions** — `cellar_tracker.refresh` and `cellar_tracker.get_wine_by_bin` — and an
  **event**, `cellartracker_inventory_changed`. See [Actions and events](#actions-and-events).
- Diagnostics you can attach to a bug report: credentials, account name and rack names are kept
  out of it.
- **Optional LED racks.** Describe your physical wine racks in the options and each one gets a
  grid sensor an ESPHome LED node can paint, so every bin lights in its drinking-window colour.
  The ESPHome configurations, the Home Assistant package, the hardware build and a printable
  controller enclosure are in [`examples/`](examples/). See [Lighting the rack](#lighting-the-rack).

---

## What gets created

Adding the integration creates **one device per account** with **five entities**, plus two more
for each rack you list under [LED racks](#lighting-the-rack). It does not
create an entity per bottle — see [Bottle-level data](#bottle-level-data) for why, and for how to
reach that data.

| Entity | Example | Unit | Device class | State class |
|---|---|---|---|---|
| Total bottles | `142` | `bottles` | — | `measurement` |
| Total value | `9812.50` | your chosen currency | `monetary` | `total` |
| Ready to drink | `37` | `bottles` | — | `measurement` |
| Past drinking window | `4` | `bottles` | — | `measurement` |
| Last synchronised | `2026-08-28 09:30:00` | — | `timestamp` | diagnostic |
| *&lt;rack&gt;* grid | `..RRA.N…` | — | — | — |
| *&lt;rack&gt;* bottles off the rack | `0` | `bottles` | — | `measurement` |

The two rack sensors exist only for racks configured under **LED racks**, so a cellar without LEDs
gets exactly the first five. The grid sensor also carries the rack's `location`, `rows` and
`columns` as attributes.

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
sensor.<account>_<rack>_grid                  # one pair per configured LED rack
sensor.<account>_<rack>_bottles_off_the_rack
```

For a rack whose CellarTracker location is `Wine Rack 1`, the grid is
`sensor.<account>_wine_rack_1_grid`.

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
           ├── analytics.py
           ├── cellar_data.py
           ├── config_flow.py
           ├── const.py
           ├── diagnostics.py
           ├── manifest.json
           ├── racks.py
           ├── sensor.py
           ├── services.py
           ├── services.yaml
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
interval and currency, and list the **LED racks** described in
[Lighting the rack](#lighting-the-rack). Leave that field empty if you have no LED strips. A line
the integration cannot read is rejected with a message naming it, rather than saved and ignored.
The integration reloads automatically.

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

## Resilience

### The disk cache

The inventory is kept in Home Assistant's `.storage/` directory
(`cellar_tracker.inventory_cache_<entry id>`): rewritten whenever it changes, and — so that its
timestamp stays true for a cellar that does not — at least once an hour for an unchanged one. If
Home Assistant **restarts while CellarTracker is unreachable**, the integration starts from that
copy instead of leaving every sensor unavailable until the outage ends.

- **Only ever a stand-in for the first refresh.** Once there is data, a failing poll behaves as it
  always did: the entities go unavailable rather than quietly showing something older than what
  they already had.
- **Never used for a login failure.** Bad credentials need you, and old data would hide the
  re-authenticate prompt.
- **It says it is stale.** *Last synchronised* shows when the cache was written, not now, so you
  can see how old the numbers are. While serving it the next poll comes sooner — the smaller of
  your interval and 15 minutes — and a live poll restores your schedule.
- **It also guards the first poll after a restart.** The cache counts as history, so an empty or
  drastically smaller first response is treated as suspect against the cached stock, exactly as it
  would be mid-run: it is refused once (and the cache is kept, not overwritten) and believed if it
  repeats. Without that, a transient blip right after a restart would have been recorded as an
  empty cellar.
- **Only a response that parsed is ever cached.** An error page cannot become the "last known"
  cellar.
- **It is private and it is removed with the integration.** It holds your purchase history and
  notes, so the file is created private, contains no credentials, and is deleted when you remove
  the integration.

### Backing off

When CellarTracker answers **429** or **5xx** the integration waits longer before asking again:
the delay doubles with each consecutive failure up to six hours, with a little random jitter so
that installs throttled together do not all return together. It is never *sooner* than the
interval you configured, and a `Retry-After` from the server is honoured exactly. Once
CellarTracker answers, your schedule comes back on its own. Other errors — a timeout, a refused
connection, a 404 — keep your schedule: they are about the connection, not about load.

### Diagnostics

**Settings → Devices & Services → CellarTracker → ⋮ → Download diagnostics.** The report includes
whether the cache is being served, the backoff state, why the last poll failed, the drink-window
counts, and the export's column names — which is how a change to CellarTracker's format shows up
without anyone sending a copy of their cellar. It leaves out your password, your username, your
rack names, and everything about a bottle beyond a short allowlist.

---

## Actions and events

Neither creates an entity. They give automations the cellar without putting a state in the
recorder for every bottle.

### `cellar_tracker.refresh`

Fetches the inventory now, instead of at the next scheduled poll. It goes through Home
Assistant's own refresh debouncer, so calling it in a loop cannot hammer CellarTracker.

```yaml
action: cellar_tracker.refresh
```

### `cellar_tracker.get_wine_by_bin`

Returns the bottles in a rack bin, for a script or automation to act on. It **returns a
response**, so call it with `response_variable`.

```yaml
- action: cellar_tracker.get_wine_by_bin
  data:
    bin: "A1"
    location: "Cellar"      # optional; omit to search every location
  response_variable: rack
- action: notify.persistent_notification
  data:
    message: >
      {% for wine in rack.bottles %}
        {{ wine.name }} {{ wine.vintage or 'NV' }} — {{ wine.drink_status }}
      {% else %}
        Bin A1 is empty.
      {% endfor %}
```

Each bottle in `rack.bottles` has `name`, `vintage`, `wine_id`, `location`, `bin`,
`drink_window` (`begin` and `end`), `drink_status` (`ready`, `past`, `aging` or `unknown`),
`peak` and `unique_bottle_id`. A non-vintage wine has `vintage: null` rather than `0`, and a bottle
with no recorded window has `null` years. Bins are matched ignoring case and surrounding spaces,
an empty `bin` matches nothing, and an empty `location` means the same as leaving it out — an
automation that renders an empty template searches every location rather than only unplaced
bottles. The tasting note, the price paid and the barcode are
deliberately left out: responses land in automation traces, which are shared far more freely than
the cellar itself.

**`peak`** is true in the **middle third** of a bottle's drinking window: with
`span = EndConsume - BeginConsume`, from `BeginConsume + span/3` to `EndConsume - span/3`. The
first and last thirds are still ready to drink — just not at their best — so the opening and
closing years of a window are not `peak`. The one exception is a **one-year window**
(`BeginConsume` equal to `EndConsume`): its only year is both, and it is `peak` in that year. For a window of 2020–2030 that is 2024 to 2026. It is never true for
a window with only one end, since there is no span to divide, and it is always a subset of
`ready`. A bottle is `peak` only while its `drink_status` is `ready`.

### The `cellartracker_inventory_changed` event

Fired when the set of bottles changes between two successful polls.

```yaml
triggers:
  - trigger: event
    event_type: cellartracker_inventory_changed
actions:
  - action: persistent_notification.create
    data:
      message: >
        {{ trigger.event.data.added_count }} added,
        {{ trigger.event.data.removed_count }} removed —
        {{ trigger.event.data.total_count }} in the cellar.
```

The payload has `added_bottles`, `removed_bottles` and `total_count`, plus `added_count`,
`removed_count` and `truncated`. Each list holds at most 50 bottles, each with only
`unique_bottle_id`, `iWine`, `Wine`, `Vintage`, `Location` and `Bin` — a large first sync cannot
push hundreds of kilobytes through the event bus, and `truncated` tells you if the lists were cut.

It deliberately **does not fire** when there is no history to compare with — a fresh install, or
after the [cache](#the-disk-cache) has been deleted — nor for a revaluation or an edited note, nor
for a failed poll. Moving a bottle to another bin is reported as removed from the old one and added
to the new.

**A restart does remember.** After one, the first live poll is compared against the cached
inventory, so bottles added, removed or moved while Home Assistant was offline *are* announced. If
the inventory is unchanged, nothing fires.

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

**For a script**, `cellar_tracker.get_wine_by_bin` returns the bottles in a rack bin, drinking
window included — see [Actions and events](#actions-and-events).

If you want the bottles themselves in Lovelace proper, the missing piece is per-bottle entities —
see [Bottle-level data](#bottle-level-data) for why they are not created by default. Please open
an issue if this matters to you; it is a reasonable feature to add behind an opt-in, given the
recorder cost is the user's to accept.

---

## Lighting the rack

If your bottles live in a rack you can put LEDs behind, the cellar can answer "what should I open"
in the room rather than on a screen. `examples/` holds a working set of configurations for two:

| File | What it is |
|---|---|
| `examples/HARDWARE.md` | The build: parts, power budget, wiring, the controller's pin map, and what is still undecided |
| `examples/esphome/winerack1aled.yaml`, `winerack1bled.yaml` | The U-shaped rack — 129 bins in a 13 × 13 envelope, one WS2815 strand per bin row, on two E8-WiFi Plus boards: 1A drives rows A–G, 1B rows H–M. Each is one file, nothing beside it |
| `examples/esphome/winerack2led.yaml` | The second rack — a full 7 × 7 on its own E8-WiFi Plus, same design at a smaller size |
| `examples/home_assistant/wine_rack_leds.yaml` | The Home Assistant package that pushes the integration's rack grids to the nodes, plus three scripts: `wine_rack_locate`, `wine_rack_show_overview` and `wine_rack_clear` |
| `examples/enclosure/` | A parametric OpenSCAD wall enclosure for one E8-WiFi Plus board, printed in PETG — base with standoffs, cable glands and wall flanges, lid on four M3 heat-set inserts |

Bins are addressed the way CellarTracker addresses them — `Location` is the rack, `Bin` is the
slot, so bin `A2` is row A, column 2. Rack 1's rows **A**–**H** hold bins 1–4 and 10–13 with an
opening across the middle; rows **I**–**M** run the full width. Rack 2 is rows **A**–**G**,
bins 1–7.

The integration itself knows your racks. Under **Settings → Devices & Services → CellarTracker →
Configure → LED racks**, list one per line — the CellarTracker location, its rows × columns, and
any bins the rack does not have:

```text
Wine Rack 1: 13x13 without A5-H9
Wine Rack 2: 7x7
```

Each rack then gets two sensors on the CellarTracker device: **`<rack> grid`**, the string its
LED node paints, and **`<rack> bottles off the rack`**, bottles filed at that rack in a bin no LED
will ever show. Both update with every sync. A cellar without LEDs leaves the field empty and
gets neither.

Bins are a row letter and a column number; `a-2`, `A 2` and `A02` all read as `A2`. `without`
takes single bins or rectangles (`A5-H9` is the U's opening), and a rack can be at most 255 bins,
the longest state Home Assistant keeps.

To install the package, enable packages in `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

then save `wine_rack_leds.yaml` as `<config>/packages/wine_rack_leds.yaml`, change the entity IDs
in it to your account's (its header lists what to set), and restart. Its contents are ordinary
automations and scripts, so pasting them into `automations.yaml` and `scripts.yaml` works too. The
grid sensors are worth adding to `recorder: exclude:` — they change only when the cellar does,
but each state is up to 169 characters.

### What it shows

Every lit bin carries the same drinking-window state the dashboard paints, so the racks and
`/cellartracker/cellar.html` cannot tell you different things about the same bottle:

| Bin | Meaning |
|---|---|
| Green | **Ready** — this year is inside the drinking window |
| Amber | **Drink this year** — the final year of the window |
| Red | **Past window** — the window closed before this year |
| Blue | **Needs aging** — the window has not opened yet |
| Dim white | **No window** — CellarTracker has no recommendation for that bottle |
| Dark | No bottle, or no bin there at all |

A bin usually holds several bottles. It shows the one that most wants dealing with: past, then
drink-this-year, then ready, then aging, then a bottle with no window at all.

There is also a **locator** — one bin lit on its own with the rest of the rack dark, for finding a
particular bottle. Copy a bin from the dashboard's bottle drawer, run the `wine_rack_locate`
script with the rack and bin, and walk to the rack. It holds for 120 seconds by default (`0` holds
until something else changes the rack), and takes an optional `[r, g, b]` colour. The overview
comes back when the hold expires, and a poll that lands while you are looking does not steal the
answer from you.

`wine_rack_show_overview` cancels a running locator and repaints every rack straight away;
`wine_rack_clear` turns all the LEDs off. The racks come back on their own at the next sync.

### Why the strips run horizontally

The strip's holder sits behind the bins, and anywhere but horizontal along the back of the rack
it covers a bin's opening. So there is one strand per bin **row**, fed from the bin-1 end.

Eight of rack 1's thirteen rows are split in two by the U's opening — bins 1–4 and 10–13. Each
of those is still one strand: the two pieces are chained by a jumper carrying 12 V, ground and
data across the gap, and the firmware continues the pixel count from bin 4 straight to bin 10.
That keeps rack 1 at thirteen data lines; running every piece as its own strand would make it
21. The test suite asserts that every piece of strip is exactly one unbroken run of bins and
that only rows A–H need a jumper, so the wiring cannot quietly stop matching the rack.

### How the two halves talk

Each node exposes four actions and knows nothing about wine:

| Action | Takes |
|---|---|
| `esphome.winerack1aled_light_rack` | `grid`: 169 state characters, row-major — the whole envelope in one call |
| `esphome.winerack1aled_light_row` | `row`: `A`-`M`, `states`: 13 characters |
| `esphome.winerack1aled_light_bin` | `bin_id`: `A2`, `r`/`g`/`b`, `seconds` to hold it |
| `esphome.winerack1aled_clear_all` | nothing |

Rack 1's other board, `winerack1bled`, takes exactly the same actions with the same data. Both
halves keep the whole 13 × 13 envelope and draw only their own rows, so the package sends every
rack-1 call to both and never has to know where the seam is — and a locator aimed at a bin on
one half blanks the other.

Rack 2 is the same, with 49 characters and rows `A`-`G`. A state character per bin — `R` ready,
`U` urgent, `P` past, `A` aging, `N` no window, `.` empty — means a whole rack fits in one action
call and in an ordinary sensor state. The integration builds those strings during each sync, in
[`racks.py`](custom_components/cellar_tracker/racks.py), with the same rule
[`_drink_window_counts`](custom_components/cellar_tracker/cellar_data.py) and the dashboard use,
and the package pushes them rather than polling on a timer: when a grid sensor changes, after
every sync (so a rack turned off with `wine_rack_clear` lights again even if no bottle moved), and
when a node comes back from unavailable, so a power cut does not leave a rack dark until the next
sync.

Rack 1's grid stays a full 13 × 13 even though the rack has 129 bins: the bins the U does not have
are sent as empty and light nothing. That also means a bottle CellarTracker still files at a bin
the rebuild removed is not mis-lit — it is just dark, and the rack's *bottles off the rack* sensor
counts them so a rebuild does not quietly swallow bottles.

### Changing the shape of a rack

Neither node's YAML knows how big its rack is up front, and neither needs a file
beside it. The rack's shape and the arithmetic that turns a bin into a run of
pixels are both `substitutions:` at the top of the node's own configuration:

```yaml
  # {first column, bins, first column, bins} per bin row: the piece of strip
  # the data reaches first, then the piece after the jumper. Row A is 0.
  rack_table: >-
    {0, 4, 9, 4}, {0, 4, 9, 4}, {0, 4, 9, 4}, {0, 4, 9, 4},
    {0, 4, 9, 4}, {0, 4, 9, 4}, {0, 4, 9, 4}, {0, 4, 9, 4},
    {0, 13, 0, 0}, {0, 13, 0, 0}, {0, 13, 0, 0}, {0, 13, 0, 0}, {0, 13, 0, 0}

  bin_first_led: |-
    auto bin_first_led = [](int col, int first_a, int bins_a, int first_b, int bins_b,
                            int *count) -> int {
      auto edge = [](int k) -> int {
        return (2 * k * ${bin_width_mm} * ${strip_density} + 999) / 2000;
      };
      int offset = 0;
      int k = -1;
      if (bins_a > 0 && col >= first_a && col < first_a + bins_a) {
        k = col - first_a;
      } else if (bins_b > 0 && col >= first_b && col < first_b + bins_b) {
        offset = bins_a > 0 ? edge(bins_a) : 0;
        k = col - first_b;
      }
      if (k < 0) return -1;
      if (count != nullptr) *count = edge(k + 1) - edge(k);
      return offset + edge(k);
    };
```

A row is at most two pieces, each a first column and a count, so a rack with an
opening in it is a table rather than a special case. Bins are placed by position
rather than at a fixed number of LEDs each: a 95 mm bin on a 60/m strip is 5.7
LEDs, and `edge(k)` is the first LED whose centre lies past the k-th bin wall,
so bins get 5 or 6 LEDs and bin 13 is where bin 13 actually is. Each strand's lambda is its
row number and three `${...}` references — thirteen copies of an integer and one
copy of the maths. To rebuild a rack, edit `rack_table` and the matching
`num_leds:`; `tests/test_rack_leds_example.py` fails if the two stop agreeing.

**Data enters at the bin-1 end.** Pixel 0 of every row is its bin 1 and the
bin numbers count up along the strand, across the jumper on a split row. That
puts every feed on one riser at the side of the rack.

### Testing C++ that lives inside a YAML string

An `addressable_lambda` body is ordinary C++ that happens to be written inside a
string, which normally makes it testable only by flashing a board.
[`tests/cpp`](tests/cpp) does not flash anything and does not keep a copy:
`yaml_lambda.py` lifts those blocks straight out of the configuration, and
[`test_yaml_lambdas.cpp`](tests/cpp/test_yaml_lambdas.cpp) `#include`s them
inside wrappers that supply the same names a lambda has in scope:

```cpp
void paint(FakeLight &it, int kRow) {
#include "rack1/row_extent.inc"
#include "rack1/bin_first_led.inc"
#include "rack1/paint_row.inc"
}
```

Those three lines are the strand's lambda, in the order the YAML has them. The
text under test is the text that ships, so a test cannot pass against a copy
that has drifted. `FakeLight::operator[]` goes through `std::vector::at`, which
turns the bug this whole arrangement exists to catch — a split row indexed as
a full one, writing past the end of a 46-pixel strand — into a thrown exception
a test can assert on rather than a flickering row somewhere else on the rack.

```console
$ cmake -S tests/cpp -B build/cpp && cmake --build build/cpp && ctest --test-dir build/cpp
```

CI runs the same three commands.

**Why the geometry is compile-time rather than Home Assistant entities.** Every
number above is folded into flash by the compiler, so a rack's shape costs zero
bytes of RAM and is readable before WiFi comes up. Measured on both nodes,
moving all of it out of the twenty hand-written lambdas it used to live in cost
no RAM at all. Runtime entities would buy re-shaping a rack without reflashing —
which happens roughly never — at the price of heap and a new failure mode where
an unavailable entity leaves the rack dark.

### Before you build it

[`examples/HARDWARE.md`](examples/HARDWARE.md) is the full build document — every part with
the reasoning behind it, the wiring and termination spec, the controller pin map, and the
decisions still open. The rest of this section is the short version.

- **No token is needed.** The grids are sensors of the integration, so the package only calls
  the nodes' actions. (Earlier versions read the inventory endpoint back over HTTP with a
  long-lived access token; if you set one up for that, you can revoke it.)
- **Power.** Rack 1 draws 3.4 A for a fully green overview and 5.7 A worst case; rack 2 adds
  2.2 A. One 12 V 12.5 A supply runs both if they can share a bus, and a single feed at the bin-1
  end of each row is enough at 0.6 A per strand — the same end the data line enters, so power and
  signal share one run up the riser. Halve the lit part by halving the palette.
- **WS2815, not WS2812B.** The backup data line means one dead pixel is one dark bin rather than a
  dark row, which matters behind a rack you cannot get at. It costs a second rail: 12 V for the
  LEDs, 5 V from a buck for the ESP32 and the level shifters.
- **Thirteen strands is more than one controller has ports for.** The Lightish E8-WiFi Plus has
  eight buffered outputs, seven usable once GPIO12 is left alone, so rack 1 is two boards — seven
  rows and six. That also keeps every node inside the ESP32's eight RMT channels, so all three run
  the native `esp32_rmt_led_strip` driver on ESP-IDF.
- **Two settings were found on real hardware.** The strip takes its colours in **RGB** order, not
  the GRB most WS281x parts use, so the configurations set `channel_colors: RGB` (with GRB, green
  lights red). And on the classic ESP32 each strand needs `rmt_symbols: 64`; with the default,
  only two of seven strands start.
- **An enclosure for the boards.** [`examples/enclosure/`](examples/enclosure/) is a parametric
  OpenSCAD case for one E8-WiFi Plus, 171 × 111 × 50.6 mm, with cut-outs placed from the measured
  board. Its README covers printing and the parameters to change.

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
  After a restart the sensors show the [cached](#the-disk-cache) inventory instead, with
  *Last synchronised* showing how old it is.
- *"CellarTracker asked us to slow down"* — HTTP 429 or 5xx. The poll [backs off](#backing-off)
  and your schedule returns by itself.
- *"unrecognised row(s) with no 'iWine' column"* — CellarTracker returned something that was not
  inventory data, typically a maintenance or error page. It recovers on its own.
- *"returned no inventory rows but the cellar previously held N bottles"* — a zero reading right
  after a stocked cellar is treated as an error the first time. **If you genuinely emptied your
  cellar, the next refresh accepts it** and the sensors go to zero.
- *"returned N bottles but the cellar previously held M; treating it as a truncated export"* — the
  response held fewer than half the bottles it did a moment ago, which is how a cut-off download
  looks. It is refused once so a half-finished export cannot replace your inventory, overwrite the
  cache or announce the missing bottles as removed. **If you really did sell or drink that much,
  the next refresh accepts it.**

### Can I poll more often than every 15 minutes?

No — 900 seconds is enforced. Each refresh downloads your entire inventory, and CellarTracker is
a small service. If you need a value right now, call `cellar_tracker.refresh` (see
[Actions and events](#actions-and-events)) or use **⋮ → Reload** on the integration.

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

### A wine rack stays dark, or lights the wrong bins

Check the rack's **grid** sensor first. If it is all dots (`.`, empty) while the rack holds
bottles, the rack's line under **Configure → LED racks** does not name the CellarTracker
`Location` exactly as your bottles are filed, so none of them are counted for it. If the grid looks right but the rack does not, the problem is
between Home Assistant and the node: the package's entity IDs must match your account's (see the
header of `wine_rack_leds.yaml`), and the ESPHome node must be adopted so its actions exist. A
grid that lands on the wrong rack means the two locations are swapped in the options.

If **bottles off the rack** is above zero, some bottles are filed at that rack in a bin it does not
have — a gap in the U, a bin outside the grid, or a bin name that is not a row letter and a column.
They are still counted everywhere else; re-bin them in CellarTracker and they light.

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
ruff format --check .
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

It runs under `mypy --strict`. Running `mypy` against an interpreter without Home Assistant is
worse than not running it: every
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

