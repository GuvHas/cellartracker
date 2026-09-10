# Examples

Working configurations that sit on top of the integration. Nothing here is installed by HACS or
loaded by Home Assistant on its own — copy what you want.

| File | What it is |
|---|---|
| [`esphome/winerack1led.yaml`](esphome/winerack1led.yaml) | An ESPHome node lighting the U-shaped rack — 129 bins, one WS2815 strand per bin column |
| [`esphome/winerack2led.yaml`](esphome/winerack2led.yaml) | The same design for the second rack, a full 7 × 7 on its own ESP32 |
| [`home_assistant/wine_rack_leds.yaml`](home_assistant/wine_rack_leds.yaml) | The Home Assistant package that turns the cellar's inventory into what both nodes paint |

These are halves of one thing: the nodes own the pixels and know nothing about wine, and the
package owns the wine and knows nothing about pixels. Each file's header says what you have to set
before it will work; [Lighting the rack](../README.md#lighting-the-rack) in the main README covers
what it does and what to know before building the hardware.

Each node is one file. Its rack's shape and the arithmetic that turns a bin into a run of pixels
are `substitutions:` at the top of the configuration, so copying a node into your ESPHome
directory is copying one file and there is nothing beside it to forget.
[`tests/cpp`](../tests/cpp) lifts that C++ back out and compiles it under doctest, which is how a
rack gets re-cut without flashing anything to find out whether the numbers still add up.
