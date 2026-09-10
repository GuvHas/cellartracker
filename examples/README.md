# Examples

Working configurations that sit on top of the integration. Nothing here is installed by HACS or
loaded by Home Assistant on its own — copy what you want.

| File | What it is |
|---|---|
| [`esphome/rack_geometry.h`](esphome/rack_geometry.h) | Bin → pixels, once. No ESPHome in it, so the tests can compile it too |
| [`esphome/winerack1_geometry.h`](esphome/winerack1_geometry.h) | Rack 1's shape — the column table that makes it a U |
| [`esphome/winerack2_geometry.h`](esphome/winerack2_geometry.h) | Rack 2's shape — four numbers, because it is a rectangle |
| [`esphome/winerack1led.yaml`](esphome/winerack1led.yaml) | An ESPHome node lighting the U-shaped rack — 129 bins, one WS2815 strand per bin column |
| [`esphome/winerack2led.yaml`](esphome/winerack2led.yaml) | The same design for the second rack, a full 7 × 7 on its own ESP32 |
| [`home_assistant/wine_rack_leds.yaml`](home_assistant/wine_rack_leds.yaml) | The Home Assistant package that turns the cellar's inventory into what both nodes paint |

These are halves of one thing: the nodes own the pixels and know nothing about wine, and the
package owns the wine and knows nothing about pixels. Each file's header says what you have to set
before it will work; [Lighting the rack](../README.md#lighting-the-rack) in the main README covers
what it does and what to know before building the hardware.

The two `.h` files next to each YAML are how a node learns its rack's shape — copy them alongside
the configuration, because ESPHome reads them from the same directory. Both are shape only; the
arithmetic is in `rack_geometry.h`, which [`tests/cpp`](../tests/cpp) compiles under doctest so a
rack can be re-cut without flashing anything to find out whether the numbers still add up.
