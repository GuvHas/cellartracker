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
| Shape | A **U** — rows A–H hold bins 1–4 and 10–13, rows I–M run full width | A plain **7 × 7** |
| Bins | 129, in a 13 × 13 envelope | 49 |
| Strands | **13** (one per bin row) | **7** (one per bin row) |
| Pixels | 738 | 280 |
| Strand lengths | 5 × 74 px (1.23 m, rows I–M), 8 × 46 px (two 23 px / 0.38 m pieces, rows A–H) | 7 × 40 px (0.67 m) |
| Jumpers | 8, one across the U's opening on each of rows A–H | none |

One WS2815 strand per **bin row**, mounted **horizontally along the back** of the rack and fed
from the **bin-1 end**. Horizontal is not a preference: the strip's holder covers a bin's
opening anywhere else. All thirteen feeds come up one riser at the bin-1 side.

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

That is a full row; it ends at LED 74, 1233 mm against the rack's 1235. Each piece of strip is
cut at its first bin's wall, so on a split row bins 10–13 sit on LEDs 23–45 with the same
5/6 pattern as bins 1–4. `bin_width_mm` and `strip_density` at the top of each config are
the only two numbers involved.

### The U's opening

Rows A–H hold bins 1–4 and 10–13 with the opening between them, so each of those rows is two
four-bin pieces of strip. They are **chained, not split**: a short jumper of the same 3-core
cable carries +12 V, GND and data from the end of the first piece (bin 4) across the opening
to the start of the second (bin 10). The jumper has no pixels, so in the firmware bin 10 is
simply the pixel after bin 4 — `rack_table` lists each row as up to two pieces and
`bin_first_led` continues the count across the gap. Because of that, the opening's width
never enters the firmware; it only sets how long the jumper is.

| | Chained (built) | Split |
|---|---|---|
| Rack 1 strands / data lines | **13** | 21 (16 pieces + 5 full rows) |
| E8 boards for rack 1 | **2** (7 + 6) | 3 (7 + 7 + 7) |
| Extra parts | 8 jumpers, ~0.6 m each | 8 more feed runs from the board |

Chaining keeps the data-line count exactly where the vertical layout had it, so the controller
plan does not change. The test suite asserts that every piece in the table is exactly one
unbroken run of bins and that only rows A–H need a jumper.

**1018 pixels, 20 strands, 20 independent data lines.** That last number is what rules out
most of the LED controllers on the market.

---

## Bill of materials

### Decided

| Item | Qty | Notes |
|---|---|---|
| **WS2815** strip, 12 V, 60 LEDs/m | **4 × 5 m reels** | 17.0 m used. Confirm `DI` *and* `BI` pads on the listing, and that it cuts at every LED |
| **Mean Well XLG-200-12** (plain, **not** `-A`) | 1 | 12 V, 16 A, 192 W, IP67, ENEC + CB. Runs both racks at 49 % load |
| **Lightish E8-WiFi Plus** | **3** | 8 buffered 5 V outputs each. 1 for rack 2, 2 for rack 1 (7 + 6) |
| **ROLANCHE 3-core 0.42 mm²** (red/black/yellow) | **7 × 5 m** | 2 reels for rack 2, 5 for rack 1: its 13 feeds plus 8 jumpers of ~0.6 m |
| **Mini blade fuses, 2 A** | 20 + spares | Littelfuse `0287002.PXCN`. **Not** the 5 A supplied — see *Fusing* |
| **Ferrules, 0.5 mm²** | 25 | Required: the cable is under the terminal's minimum — see *Terminations* |
| 16 AWG red + black | 2 m each | XLG → each board's input terminal |
| WAGO 221 lever connectors | 2 | Splits the XLG's potted leads to both racks (+12 V and GND) |
| Aluminium channel + diffuser | ~10 × 2 m | Optional, and doubles as the horizontal mount at the back. Six bare LEDs read as six dots |
| Solder, heatshrink, cable clips, crimp tool | — | |

### Cut plan — 4 reels

A 5 m reel is 300 LEDs. Nesting the three piece lengths — 5 full rows (74), 16 half-row pieces
(23) and 7 rack-2 rows (40):

| Reel | Cut | LEDs used |
|---|---|---|
| 1 | 4 full (74) | 296 of 300 |
| 2 | 1 full (74) + 5 rack-2 (40) + 1 piece (23) | 297 |
| 3 | 2 rack-2 (40) + 9 pieces (23) | 287 |
| 4 | 6 pieces (23) | 138, ~2.7 m spare |

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
| Dark but powered | 0.7 A | 0.3 A | **1.0 A** | 12 W |
| Every bin ready (green) | 3.4 A | 1.3 A | **4.7 A** | 56 W |
| Every bin amber — **worst case** | 5.7 A | 2.2 A | **7.8 A** | 94 W |

Every pixel is behind a bin now, so all of them can be lit at once; there are fewer of them.
7.8 A into a 16 A supply is **49 % load** — the efficient, long-lived place for a switching
supply to sit.

### Why this supply

Not a capacity decision. The XLG is IP67 and potted, so there are no exposed 230 V
terminals in a damp cellar, and it carries **ENEC and CB** marks — third-party tested,
unlike a self-declared CE. Its `-A` variant adds a potentiometer that adjusts the current
limit down to 8 A, barely above the 7.8 A worst case: cross that and the rail walks toward 8.4 V,
under the WS2815's 9.5 V minimum. Buy the plain one.

### Siting

Both racks sit within half a metre, with the supply **between** them. Drop over a 1 m feed:

| Feed | Current | 16 AWG |
|---|---|---|
| Rack 1 | 5.7 A | **0.15 V** |
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

The cable bundle goes up the riser at the bin-1 side of rack 2 and peels off one cable per
shelf, top row first, so the ports run in order down the rack instead of crossing over.

| Bin row | Port | GPIO |
|---|---|---|
| — | O1 | *damaged, empty* |
| A | O2 | 12 |
| B | O3 | 4 |
| C | O4 | 27 |
| D | O5 | 17 |
| E | O6 | 26 |
| F | O7 | 33 |
| G | O8 | 25 |

Rack 2's O1 port was damaged on 2026-10-26, so row A runs from O2, the other half of the
same X1 terminal block. That puts a strand on GPIO12 after all. It works because the pin only
drives the port's buffer and its own pull-down holds it low at reset. If the board ever fails
to boot, burn the flash-voltage eFuse to 3.3 V once (`espefuse.py --port <port>
set_flash_voltage 3.3V`, with the board on USB) and GPIO12 stops being a strapping pin. The
eFuse cannot be undone, so first check the module's flash is 3.3 V.

### Port → bin row, rack 1

Two boards, one config each. They take the same Home Assistant calls — the package sends
every rack-1 call to both — and each draws only its own rows.

| Board 1A — `winerack1aled.yaml` | | | Board 1B — `winerack1bled.yaml` | | |
|---|---|---|---|---|---|
| **Bin row** | **Port** | **GPIO** | **Bin row** | **Port** | **GPIO** |
| A | O1 | 5 | — | O1 | *empty* |
| B | O3 | 4 | H | O3 | 4 |
| C | O4 | 27 | I | O4 | 27 |
| D | O5 | 17 | J | O5 | 17 |
| E | O6 | 26 | K | O6 | 26 |
| F | O7 | 33 | L | O7 | 33 |
| G | O8 | 25 | M | O8 | 25 |

Board 1A carries the seven split rows A–G; board 1B carries split row H and the five full
rows I–M. With only six strands, 1B leaves O1 empty as well as O2, so it uses no strapping
pin at all. The split is by row rather than by load: 1A draws 2.5 A worst case, 1B 3.2 A,
both well inside the board's 30 A.

Purely a build convenience — every `kRow` in the configs still names the bin row its entity
is called after, so nothing about the picture depends on the order. **OPEN:** if a board
mounts at the bottom of its riser, you may prefer the bottom row on the lowest port; reverse
the GPIO column.

### The relay

GPIO23 drives an **external** relay — you supply it. The topology the board expects: a
secondary feed keeps the controller alive while the relay cuts the main LED rail, so the node
stays on the network with the pixels dead. Needs a 12 V coil and contacts rated for the
board's load (a 10 A automotive relay covers any of them: 1A is 2.5 A, 1B 3.2 A, rack 2 2.2 A).
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

### Jumpers across the U (rack 1, rows A–H)

Same cable, same colours, one per split row:

| Core | From (end of bin 4's piece) | To (start of bin 10's piece) |
|---|---|---|
| Red | `+12V` | `+12V` |
| Black | `GND` | `GND` |
| Yellow | `DO` | `DI` **and** `BI` |

Leave the first piece's `BO` unconnected. Tying the second piece's `DI` and `BI` together
means the last pixel before the jumper is the one pixel whose failure darkens the far half
of the row; a fourth core from `BO` to `BI` would close that, and is not worth a different
cable. The jumper runs behind the opening, so it is visible through it — sleeve it black or
clip it to the back rail. Measure it from the real rack: the opening is five 95 mm bins,
475 mm, plus the slack to the pads — about 0.6 m. Only the jumper depends on that number.

### Gauge

The ROLANCHE cable's 21 strands of 0.16 mm work out to **0.422 mm²** — nearer 21 AWG than the
"20 AWG" on the listing, about 41 mΩ/m. Drop over the longest runs:

| Run | Current | Drop |
|---|---|---|
| Rack 2, 1.5 m | 0.31 A | **0.038 V** |
| Rack 1, 2.5 m (up the riser) | 0.57 A | **0.12 V** |
| Rack 1 jumper, 0.6 m | 0.18 A | **0.009 V** |

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
a pad on a flexible PCB with nothing to clamp. Four joints per strand, plus seven per jumper
(three on the way out, four on the way in): 28 for rack 2 and 108 for rack 1:

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
| Rack 1 split row, 46 px | 0.35 A | 1.20 A | holds |
| Rack 1 full row, 74 px | 0.57 A | 1.92 A | holds, just |

With the shorter strands nothing clears at full white any more, and nothing needs to: every
strand at full white is under the cable's rating. Full white is not a state the design
produces — it only happens if someone selects effect "None" in Home Assistant and turns a row
up — and all 20 strands at full white would ask **26 A** of a 16 A supply, which then current-
limits and drops the lot. A 1 A fuse would catch the full rows and the split rows at full white
while holding every designed state, but not rack 2's; that trade is listed under **OPEN**.

The holder takes normal, mini or low-profile mini blades; the board ships with **mini**
(Littelfuse 287 series), so buy mini.

---

## Build order

Build **rack 2 first**, complete, before cutting anything for rack 1.

Seven strands proves the whole chain — the supply, the ferrules, the fuse ratings, the
left-to-right indexing, the Home Assistant package, the colour mapping — on a third of the
soldering. The one thing it cannot prove is a jumper: make one row of rack 1 next, and check
bins 4 and 10 either side of it before doing the other seven. One reel of strip and one
controller gets you there, and anything learned applies thirteen times over on rack 1.

1. Check a few bins at the back of the rack are **95 mm** wall to wall, and the strip is
   **60/m** cut line to cut line. Those are `bin_width_mm` and `strip_density`; a different
   value is a one-number change and the tests recompute every bin. On rack 1, also measure the
   opening's width for the jumpers.
2. Flash and bench-test the controller over USB-C before wiring anything to 12 V.
3. Cut, solder and heatshrink seven strands. Test each one on the bench.
4. Mount, route, ferrule, fuse at 2 A.
5. Run the Home Assistant package and check a bin you know against the dashboard.
6. Then rack 1.

---

## Energy

Worth deciding deliberately, because a permanently-lit rack is not cheap:

| | Power | Per year |
|---|---|---|
| Dark but powered | 12 W | ~105 kWh |
| Overview showing, all green | **56 W** | **~490 kWh** |

At Swedish prices that overview is several hundred kronor a year to light a cellar nobody is
standing in. **The big lever is an automation, not hardware** — light the racks on a door
contact or a motion sensor and blank them on a timer. The GPIO23 relay then removes the last
12 W once the picture is dark. Both are worth having; the automation is worth about ten times
the relay.

Halving the palette's values halves everything above the standing current.

---

## OPEN

| | Why it matters |
|---|---|
| **Which CellarTracker `Location` is the 7 × 7 rack?** | [`home_assistant/wine_rack_leds.yaml`](home_assistant/wine_rack_leds.yaml) maps `'Wine Rack 1'` to the 13-strand U and `'Wine Rack 2'` to the 7 × 7. If your data says otherwise the grids go to the wrong nodes and every bin is wrong — a two-line fix, best caught before soldering |
| **Does rack 2's board sit at the top or the bottom of the riser?** | Decides whether the port → row table above runs A→G or G→A. One-line change either way |
| **Which GPIO, if any, the relay needs beyond 23** | The secondary-power input's wiring is not in the published spec |
| **Bin width** | 95 mm and 60/m are what the configs use. Check a few bins agree before cutting — the mapping tolerates up to half an LED of error per piece, not a different number |
| **1 A fuses instead of 2 A?** | Would make a full row or split row at full white blow its own fuse rather than tripping the supply's current limit. Rack 2's 40 px rows would still not clear, so it buys less than it did |
| **Which side the riser goes up** | The configs feed every row from the **bin-1** end. If the bin-13 side is more convenient, each row's pieces and `bin_first_led` have to count from the other end — a one-place change, but one the tests should see before the strip is cut |
