# Building the rack lighting

Everything you need to buy, wire and flash to make
[`esphome/winerack1aled.yaml`](esphome/winerack1aled.yaml),
[`esphome/winerack1bled.yaml`](esphome/winerack1bled.yaml) and
[`esphome/winerack2led.yaml`](esphome/winerack2led.yaml) light real bottles. The configs
describe what the firmware does; this describes the hardware underneath it, and the
decisions behind each part — so a choice made once does not have to be made again from
memory.

Numbers here are derived from the power budget in each config and will stay in step with
it. Where something is still undecided it is marked **OPEN** and collected at the bottom.

---

## What this builds

| | Rack 1 | Rack 2 |
|---|---|---|
| Shape | A full **14 × 13** (14 rows, 13 columns), A1–N13 | A plain **7 × 7** |
| Bins | 182 | 49 |
| Strands | **14** (one per bin row) | **7** (one per bin row) |
| Pixels | 1036 | 280 |
| Strand lengths | 14 × 74 px (1.23 m) | 7 × 40 px (0.67 m) |
| Jumpers | none | none |

One WS2815 strand per **bin row**, mounted **horizontally along the back** of the rack and fed
from one end: rack 1 from the **bin-1 end**, rack 2 from the **bin-7 end** (`din_column` in
each node's config). Horizontal is not a preference: the strip's holder covers a bin's
opening anywhere else. Each rack's feeds come up one riser at its feed side.

### 95 mm bins on a 60/m strip

A bin is **95 mm** wide and the strip's cut lines are **16.7 mm** apart (60/m), so a bin is
5.7 LEDs — not a whole number. Six per bin would drift four LEDs (65 mm) by bin 13; five per
bin would drift the other way. So the firmware places each bin by **position**: a bin owns the
LEDs whose centres fall between its two walls, which gives 5 or 6 per bin and keeps every
bin's first LED within one LED of its wall all the way along. There is no deliberate dark gap
between bins any more — the bin wall is the divider.

| Bin | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| First LED | 0 | 6 | 11 | 17 | 23 | 28 | 34 | 40 | 46 | 51 | 57 | 63 | 68 |
| LEDs | 6 | 5 | 6 | 6 | 5 | 6 | 6 | 6 | 5 | 6 | 6 | 5 | 6 |

That is every row of rack 1; it ends at LED 74, 1233 mm against the rack's 1235. `bin_width_mm` and `strip_density` at the top of each config are
the only two numbers involved.

### Rack 1 used to be a U

Until November 2026 rows A–H of rack 1 held only bins 1–4 and 10–13, with an opening at
A5–H9. Each of those rows was two four-bin pieces (23 LEDs each) chained by a pixel-less
jumper across the opening. That section has since been built in and a fourteenth row, N,
added, so the rack is A1–N13, every row is 13 bins and `rack_table` lists each one as
`{0, 13, 0, 0}`.

Row N goes on board 1B, which now drives seven rows like 1A. To keep the ports in row order,
1B's cables each move up one port: H to O1, I to O3, and so on to N on O8 (see the port table
below).

To convert a row built the old way, take the jumper out and splice a **28-LED piece** (bins
5–9) in its place, so the row runs 23 + 28 + 23 = 74 LEDs unbroken: DO → DI and BI, +12 V and
GND straight across at each join. The firmware places bin 10 at LED 51, which is where the
start of the third piece lands. A fresh 74-LED strip per row does the same job with two fewer
joints. The firmware still accepts a row of two pieces, so a rack with a gap can be described
again later; the test suite asserts that every piece in the table is exactly one unbroken run of
bins.

**1316 pixels, 21 strands, 21 independent data lines.** That last number is what rules out
most of the LED controllers on the market.

---

## Bill of materials

### Decided

| Item | Qty | Notes |
|---|---|---|
| **WS2815** strip, 12 V, 60 LEDs/m | **5 × 5 m reels** | 21.9 m used. Confirm `DI` *and* `BI` pads on the listing, and that it cuts at every LED |
| **Mean Well XLG-200-12** (plain, **not** `-A`) | 1 | 12 V, 16 A, 192 W, IP67, ENEC + CB. Runs both racks at 63 % load |
| **Lightish E8-WiFi Plus** | **3** | 8 buffered 5 V outputs each. 1 for rack 2, 2 for rack 1 (7 + 6) |
| **ROLANCHE 3-core 0.42 mm²** (red/black/yellow) | **7 × 5 m** | 2 reels for rack 2, 5 for rack 1's 14 feeds |
| **Mini blade fuses, 2 A** | 21 + spares | Littelfuse `0287002.PXCN`. **Not** the 5 A supplied — see *Fusing* |
| **Ferrules, 0.5 mm²** | 25 | Required: the cable is under the terminal's minimum — see *Terminations* |
| 16 AWG red + black | 2 m each | XLG → each board's input terminal |
| WAGO 221 lever connectors | 2 | Splits the XLG's potted leads to both racks (+12 V and GND) |
| Aluminium channel + diffuser | ~10 × 2 m | Optional, and doubles as the horizontal mount at the back. Six bare LEDs read as six dots |
| Solder, heatshrink, cable clips, crimp tool | — | |

### Cut plan — 5 reels

A 5 m reel is 300 LEDs. Nesting the two strand lengths — 14 rack-1 rows (74) and 7 rack-2 rows
(40):

| Reel | Cut | LEDs used |
|---|---|---|
| 1–3 | 4 rack-1 rows (74) each | 296 of 300 |
| 4 | 2 rack-1 rows (74) + 3 rack-2 (40) | 268 |
| 5 | 4 rack-2 (40) | 160, ~2.3 m spare |

Converting the old U instead needs only 8 pieces of 28 LEDs — 224, under one reel.

Cut every piece **at a bin wall's position**, not by counting from the last cut — the
firmware assumes each piece starts flush with its first bin.

### Deliberately not bought

| | Why |
|---|---|
| QuinLED Dig-Octa Brainboard + Power-5 | Equivalent, and a strong second choice — but needs two boards, screw terminals with ferrules, and splits power and data across them. Its advantage is **Ethernet**, which the E8 lacks |
| 74HCT245 modules, buck converters, stripboard | The E8's outputs are already buffered 5 V TTL, and it regulates its own logic |
| 4-pin JST-SM connectors | The crimp takes 0.08–0.33 mm²; the cable is 0.42 mm². Disconnection happens at the board's own pluggable terminals instead |
| Falcon F16V5, Advatek PixLite, Kulp | E1.31/DDP **receivers** — no state, no logic. Would mean writing a frame-streaming bridge to replace working firmware |
| GLEDOPTO, Dig-Quad, Dig-Uno, Dig2Go | 1–5 outputs. The requirement is 13 |

---

## Power

Per-pixel budget, from the configs: `(R + G + B) / 765 × 25 mA + 1 mA` at 12 V. The palette
caps every channel at 150 and `gamma_correct` is 1.0, so these are what the pixels draw.

| State | Rack 1 | Rack 2 | Both | At 12 V |
|---|---|---|---|---|
| Dark but powered | 1.0 A | 0.3 A | **1.3 A** | 16 W |
| Every bin ready (green) | 4.8 A | 1.3 A | **6.1 A** | 73 W |
| Every bin amber — **worst case** | 8.0 A | 2.2 A | **10.1 A** | 122 W |

Every pixel is behind a bin, so all of them can be lit at once.
10.1 A into a 16 A supply is **63 % load** — the efficient, long-lived place for a switching
supply to sit.

### Why this supply

Not a capacity decision. The XLG is IP67 and potted, so there are no exposed 230 V
terminals in a damp cellar, and it carries **ENEC and CB** marks — third-party tested,
unlike a self-declared CE. Its `-A` variant adds a potentiometer that adjusts the current
limit down to 8 A, below the 10.1 A worst case: cross that and the rail walks toward 8.4 V,
under the WS2815's 9.5 V minimum. Buy the plain one.

### Siting

Both racks sit within half a metre, with the supply **between** them. Drop over a 1 m feed:

| Feed | Current | 16 AWG |
|---|---|---|
| Rack 1 | 8.0 A | **0.21 V** |
| Rack 2 | 2.2 A | **0.06 V** |

Against a 1.5 V budget (12 V → the 10.5 V a WS2815 wants), both are noise. One supply,
split at the WAGOs.

### The board's 10 A minimum matters

The E8's input spec says **minimum available current 10 A**. That is not about running the
LEDs — it is so the per-output fuses can actually clear. Feed a 30 A distribution board from
a 3 A supply and a shorted output makes the supply current-limit instead of the fuse
blowing: the fault never isolates and the whole rack drops. The XLG's 16 A clears it.

### Mains

The XLG has potted flying leads (L / N / **PE** — it is Class I, earth it). Terminate into a
3-core flex and a Schuko plug, or an IP-rated junction box. A plug-in supply on a flex is
yours to install; anything hard-wired into fixed wiring is an authorised-electrician job in
Sweden.

**Never put a dimmer upstream.** The pixels dim themselves from the data; a phase-cut dimmer
would either refuse to start the supply or damage it, and the controller needs continuous
power to stay on the network.

---

## The controller

**Lightish E8-WiFi Plus** — ESP32, 8 ports, each a **buffered 5 V TTL output** with a 33 Ω
series resistor, each with its own fuse and status LED. Power and data share one 3-pin
connector per port, which is exactly the 3-core cable above. 5–24 V in, 30 A max, spring-cage
terminals. WLED ships on it; the vendor states **ESPHome** is supported.

### Pin map

| GPIO | Function | | GPIO | Function |
|---|---|---|---|---|
| 5 | O1 data | | 23 | **Relay output** |
| **12** | **O2 data — avoid** | | 2 | IR receiver |
| 4 | O3 data | | 32 / 13 | I²C SDA / SCK |
| 27 | O4 data | | 18 | DMX out |
| 17 | O5 data | | 14 / 15 / 16 / 36 | SD card |
| 26 | O6 data | | 1 / 3 | Serial TX / RX |
| 33 | O7 data | | 34 / 35 | Button inputs (input-only) |
| 25 | O8 data | | 21 / 22 | Spare |

**Skip O2.** GPIO12 is MTDI, the flash-voltage strapping pin: held high at boot the ESP32
selects 1.8 V flash and will not start. The buffer in front of it makes that unlikely — the
pin drives a high-impedance input, so nothing on the cable side can pull it up — but you
need 7 of 8 ports and have 8, so there is no reason to take the risk.

**GPIO21 and 22 are spare pins, not extra outputs.** They come straight off the ESP32 at
3.3 V, below the WS2815's 3.5 V V<sub>IH</sub>. Same for anything repurposed from the I²C,
DMX or SD pins. It stays **8 usable outputs per board**, which is why rack 1 needs two.

### Port → bin row, rack 2

The cable bundle goes up the riser at the bin-7 side of rack 2 and peels off one cable per
shelf, top row first, so the ports run in order down the rack instead of crossing over.

| Bin row | Port | GPIO |
|---|---|---|
| A | O1 | 5 |
| B | O3 | 4 |
| C | O4 | 27 |
| D | O5 | 17 |
| E | O6 | 26 |
| F | O7 | 33 |
| G | O8 | 25 |

### Port → bin row, rack 1

Two boards, one config each. They take the same Home Assistant calls — the blueprints send
every rack-1 call to both — and each draws only its own rows.

| Board 1A — `winerack1aled.yaml` | | | Board 1B — `winerack1bled.yaml` | | |
|---|---|---|---|---|---|
| **Bin row** | **Port** | **GPIO** | **Bin row** | **Port** | **GPIO** |
| A | O1 | 5 | H | O1 | 5 |
| B | O3 | 4 | I | O3 | 4 |
| C | O4 | 27 | J | O4 | 27 |
| D | O5 | 17 | K | O5 | 17 |
| E | O6 | 26 | L | O6 | 26 |
| F | O7 | 33 | M | O7 | 33 |
| G | O8 | 25 | N | O8 | 25 |

Board 1A carries rows A–G; board 1B carries rows H–N. Both drive seven strands, so both use
O1 and leave only O2 empty, the same as rack 2. Each draws 4.0 A worst case,
both well inside the board's 30 A.

Purely a build convenience — every `kRow` in the configs still names the bin row its entity
is called after, so nothing about the picture depends on the order. **OPEN:** if a board
mounts at the bottom of its riser, you may prefer the bottom row on the lowest port; reverse
the GPIO column.

### The relay

GPIO23 drives an **external** relay — you supply it. The topology the board expects: a
secondary feed keeps the controller alive while the relay cuts the main LED rail, so the node
stays on the network with the pixels dead. Needs a 12 V coil and contacts rated for the
board's load (a 10 A automotive relay covers any of them: 1A and 1B are 4.0 A each, rack 2 2.2 A).
One relay per board, each switching only that board's LED rail.

All three configs declare it as a `switch:` that the render script raises whenever any of
that board's rows is lit and drops when they all go dark. With no relay fitted it toggles a pin and does
nothing — harmless, and the intent is recorded.

---

## Wiring

**Three conductors per strand.** The board's port connector carries all three.

| Core | From | To |
|---|---|---|
| Red | Port +V | Strip `+12V` |
| Black | Port GND | Strip `GND` |
| Yellow | Port data | Strip `DI` **and** `BI` |

Write that mapping down somewhere. Yellow is sometimes used for +12 V in automotive wiring,
and you will have 21 conductors terminated before you next think about it.

### Gauge

The ROLANCHE cable's 21 strands of 0.16 mm work out to **0.422 mm²** — nearer 21 AWG than the
"20 AWG" on the listing, about 41 mΩ/m. Drop over the longest runs:

| Run | Current | Drop |
|---|---|---|
| Rack 2, 1.5 m | 0.31 A | **0.038 V** |
| Rack 1, 2.5 m (up the riser) | 0.57 A | **0.12 V** |

Irrelevant against the budget. The cable was chosen for its colour coding and its fit in the
terminals, not its copper.

### Terminations

**Board end — ferrules are not optional.** The output terminals accept stranded **0.5–1 mm²**
with a sleeve. At 0.42 mm² the cable is ~16 % *under* the minimum, and an undersized
conductor in a spring cage may not develop enough contact force to stay put. Crimp a
**0.5 mm² single ferrule** on every conductor; 0.42 mm² is inside a 0.5 mm² ferrule's crimp
range, and it brings the outside dimension up to what the terminal expects. Strip 9–10 mm.
(Only *twin* ferrules are excluded by the spec.) The input terminal takes 0.5–6 mm², so the
16 AWG feed goes in bare — strip 15–16 mm there.

**Strip end — soldered, and there is no alternative.** A WAGO clamps wires; a WS2815 input is
a pad on a flexible PCB with nothing to clamp. Four joints per strand: 28 for rack 2 and 56 for rack 1:

- Tin the pad and the wire separately, then join
- **~350 °C, 2–3 seconds per pad.** Dwelling lifts the pad off the flex — the usual way these
  get killed
- **Jumper `DI` to `BI` at the first pixel** with a short offcut. That backup line is the
  reason this is WS2815 rather than WS2812B; left floating it can oscillate and take the
  row with it
- Heatshrink each joint, then one larger piece over all four
- **Strain-relieve the cable to the rack frame**, 50–100 mm back, with a service loop. The pad
  must never take the load

No connector is needed at the strip end: the board's own terminals are the disconnect, and
they are in the dry where you can see them rather than behind a hundred bottles.

### Fusing

Fit **2 A**, not the 5 A supplied. The fuse protects the *cable*, not the LEDs — the LEDs are
self-limiting — and 0.42 mm² is good for roughly 3 A enclosed.

| Strand | As designed | Full white | 2 A fuse |
|---|---|---|---|
| Rack 2, 40 px | 0.31 A | 1.04 A | holds |
| Rack 1 row, 74 px | 0.57 A | 1.92 A | holds, just |

With the shorter strands nothing clears at full white any more, and nothing needs to: every
strand at full white is under the cable's rating. Full white is not a state the design
produces — it only happens if someone selects effect "None" in Home Assistant and turns a row
up — and all 21 strands at full white would ask **34 A** of a 16 A supply, which then current-
limits and drops the lot. A 1 A fuse would catch rack 1's rows at full white
while holding every designed state, but not rack 2's; that trade is listed under **OPEN**.

The holder takes normal, mini or low-profile mini blades; the board ships with **mini**
(Littelfuse 287 series), so buy mini.

---

## Build order

Build **rack 2 first**, complete, before cutting anything for rack 1.

Seven strands proves the whole chain — the supply, the ferrules, the fuse ratings, the
left-to-right indexing, the Home Assistant blueprints, the colour mapping — on a third of the
soldering. One reel of strip and one
controller gets you there, and anything learned applies fourteen times over on rack 1.

1. Check a few bins at the back of the rack are **95 mm** wall to wall, and the strip is
   **60/m** cut line to cut line. Those are `bin_width_mm` and `strip_density`; a different
   value is a one-number change and the tests recompute every bin.
2. Flash and bench-test the controller over USB-C before wiring anything to 12 V.
3. Cut, solder and heatshrink seven strands. Test each one on the bench.
4. Mount, route, ferrule, fuse at 2 A.
5. Add the racks in the integration's options, create the two blueprints for each rack, and check a bin you know against the dashboard.
6. Then rack 1.

---

## Energy

Worth deciding deliberately, because a permanently-lit rack is not cheap:

| | Power | Per year |
|---|---|---|
| Dark but powered | 16 W | ~140 kWh |
| Overview showing, all green | **73 W** | **~640 kWh** |

At Swedish prices that overview is several hundred kronor a year to light a cellar nobody is
standing in. **The big lever is an automation, not hardware** — light the racks on a door
contact or a motion sensor and blank them on a timer. The GPIO23 relay then removes the last
16 W once the picture is dark. Both are worth having; the automation is worth about ten times
the relay.

Halving the palette's values halves everything above the standing current.

---

## OPEN

| | Why it matters |
|---|---|
| **Which CellarTracker `Location` is the 7 × 7 rack?** | The integration's *LED racks* option names `Wine Rack 1` as the 14 × 13 and `Wine Rack 2` as the 7 × 7, and each rack's paint automation sends that grid to the nodes named in it. If your data says otherwise the grids go to the wrong nodes and every bin is wrong — a two-line fix in the options, best caught before soldering |
| **Does rack 2's board sit at the top or the bottom of the riser?** | Decides whether the port → row table above runs A→G or G→A. One-line change either way |
| **Which GPIO, if any, the relay needs beyond 23** | The secondary-power input's wiring is not in the published spec |
| **Bin width** | 95 mm and 60/m are what the configs use. Check a few bins agree before cutting — the mapping tolerates up to half an LED of error per piece, not a different number |
| **1 A fuses instead of 2 A?** | Would make a rack-1 row at full white blow its own fuse rather than tripping the supply's current limit. Rack 2's 40 px rows would still not clear, so it buys less than it did |
