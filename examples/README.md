# Examples

Working configurations that sit on top of the integration. Nothing here is installed by HACS or
loaded by Home Assistant on its own — copy what you want.

| File | What it is |
|---|---|
| [`HARDWARE.md`](HARDWARE.md) | **Start here if you are building it** — parts list, wiring, the controller's pin map, build order |
| [`esphome/winerack1aled.yaml`](esphome/winerack1aled.yaml), [`esphome/winerack1bled.yaml`](esphome/winerack1bled.yaml) | The U-shaped rack — 129 bins, one WS2815 strand per bin row, mounted horizontally at the back. Two E8-WiFi Plus boards: rows A–G and rows H–M |
| [`esphome/winerack2led.yaml`](esphome/winerack2led.yaml) | The same design for the second rack, a full 7 × 7 on its own E8-WiFi Plus |
| [`blueprints/`](../blueprints/) | Not in this folder, but part of the set: two Home Assistant blueprints, one automation that pushes each rack's grid to its nodes and one script for the locator. [Connecting Home Assistant to the racks](../README.md#connecting-home-assistant-to-the-racks) has the import buttons. The racks themselves are set in the integration's options |
| [`enclosure/e8_wifi_plus_enclosure.scad`](enclosure/) | Parametric OpenSCAD wall enclosure for one E8-WiFi Plus, printed in PETG |
| [`led-clip/led_profile_divider_clip.scad`](led-clip/) | Parametric OpenSCAD clip that holds a 16 x 16 mm corner LED profile on a 37 mm diamond-set divider, printed in PETG |

These are halves of one thing: the nodes own the pixels and know nothing about wine, the
integration owns the wine and knows nothing about pixels, and the blueprints only carry one to the
other. Each file's header says what you have to set before it will work; [Lighting the rack](../README.md#lighting-the-rack) in the main README covers
what it does and what to know before building the hardware.

Each node is one file. Its rack's shape and the arithmetic that turns a bin into a run of pixels
are `substitutions:` at the top of the configuration, so copying a node into your ESPHome
directory is copying one file and there is nothing beside it to forget.
[`tests/cpp`](../tests/cpp) lifts that C++ back out and compiles it under doctest, which is how a
rack gets re-cut without flashing anything to find out whether the numbers still add up.
