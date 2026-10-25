# E8-WiFi Plus wall enclosure

[`e8_wifi_plus_enclosure.scad`](e8_wifi_plus_enclosure.scad) is a parametric, two-piece PETG
enclosure for one Lightish E8-WiFi Plus board. It has a base with board standoffs, cable-gland
holes and wall-mount flanges, and a lid held by four M3 screws into heat-set inserts. Open it
in OpenSCAD, set `part`, press F6 and export the STL.

![assembly](enclosure_preview.png)

## Default size

| | |
|---|---|
| Outside, without flanges | 167 × 107 × 47 mm |
| Footprint with flanges | 195 × 107 mm |
| Cavity | 161 × 101 × 41 mm |

## Measure before printing

The vendor datasheet gives the board envelope (**135 × 85 × 26 mm**) and the terminal specs,
but it does not give hole positions, connector placement or component heights. Every
parameter tagged `[MEASURE]` in the script is a placeholder:

| Parameter | Default | What to measure |
|---|---|---|
| `board_holes` | 4 mm in from each corner | Mounting-hole centres from the corner at the output-terminal edge |
| `board_t`, `board_comp_h`, `board_under_h` | 1.6 / 24.4 / 3.0 mm | PCB thickness, tallest part on top, tallest solder joint below |
| `output_offset_x` | 0 | Shift of the 8 output glands so they line up with X1–X4 |
| `power_y` | 42.5 mm | Where X5 sits along the short edge (default assumes the left edge) |
| `antenna_y` | 60 mm | Where the antenna lead leaves (default assumes the right edge) |
| `usb_x`, `usb_y` | 20 / 70 mm | Centre of the vertical USB-C on V1.02 boards (lid window) |

If your board has the older horizontal USB-C (V1.01), set `usb_mode = "wall"`.

## Hardware per enclosure

| Item | Qty |
|---|---|
| M3 heat-set insert, 4.0–4.2 mm OD, 4–5 mm long | 8 |
| M3 × 6 screw, board to standoffs | 4 |
| M3 × 8 screw, lid | 4 |
| M12 × 1.5 cable gland (3–6.5 mm cable) | up to 8, one per output in use |
| M16 × 1.5 cable gland | 1, power in |
| 4 mm countersunk wood screw + plug | 4 |

Rack 1's second board drives only 6 strands, so it needs 6 output glands; blank the unused
holes with M12 blanking plugs.

## Print settings

PETG, 0.2 mm layers, 4 perimeters, 25–40 % gyroid. Print the base floor-down and the lid
outer-face-down (`part = "print"` lays out both). No supports: the wall holes are teardrops,
and the gland's hex and sealing washer cover the point.
