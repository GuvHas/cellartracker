# Examples

Working configurations that sit on top of the integration. Nothing here is installed by HACS or
loaded by Home Assistant on its own — copy what you want.

| File | What it is |
|---|---|
| [`esphome/winerack1led.yaml`](esphome/winerack1led.yaml) | An ESPHome node that lights a 13 × 13 wine rack with WS2812 strips, one strand per row |
| [`home_assistant/wine_rack_leds.yaml`](home_assistant/wine_rack_leds.yaml) | The Home Assistant package that turns the cellar's inventory into what that node paints |

The two are halves of one thing: the node owns the pixels and knows nothing about wine, and the
package owns the wine and knows nothing about pixels. Each file's header says what you have to set
before it will work; [Lighting the rack](../README.md#lighting-the-rack) in the main README covers
what it does and what to know before building the hardware.
