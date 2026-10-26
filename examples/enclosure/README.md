# E8-WiFi Plus wall enclosure

[`e8_wifi_plus_enclosure.scad`](e8_wifi_plus_enclosure.scad) is a parametric, two-piece PETG
enclosure for one Lightish E8-WiFi Plus board. It has a base with board standoffs, cable-gland
holes and wall-mount flanges, and a lid held by four M3 screws into heat-set inserts. Open it
in OpenSCAD, set `part`, press F6 and export the STL.

![assembly](enclosure_preview.png)

## Default size

| | |
|---|---|
| Outside, without flanges | 171 × 111 × 50.6 mm |
| Footprint with flanges | 199 × 111 mm |
| Cavity | 165 × 105 × 44.6 mm |

## Layout

Positions come from the vendor's *Board Dimensions* photo of a V1.02 board, scaled at about
4.8 px/mm, so they are good to roughly ±1 mm.

- **Front wall:** two staggered M12 glands per output block, right in front of it. The lower
  gland feeds the block's lower (even) output and the upper gland its upper (odd) output.
  The M16 power gland sits in front of X5 at the right.
- **Back wall:** the antenna hole, behind the ESP32's u.FL socket. The board sits 9 mm
  clear of this wall (`back_bay`) so the antenna lead has room to route, and 11 mm from the
  front wall (`front_bay`). Trade one against the other to keep the box the same size.
- **Lid:** a window over the vertical USB-C at the back edge.
- **Standoffs:** four, each with a heat-set insert, on the board's 127 × 77 mm hole rectangle
  (measured on a real board).
- `outputs_used` drops the holes for outputs a board doesn't drive. Rack 1's second board
  only uses 6.

## Check before printing

Every value tagged `[CHECK]` in the script was read off the photo or assumed. A minute with
calipers is worth it for these:

| Parameter | Default | What to check |
|---|---|---|
| `block_x`, `power_x` | 10.2 / 36.7 / 64.2 / 89.9, 119.2 mm | Centre of X1–X4 (the D pin) and of X5 |
| `usb_x`, `usb_y` | 87.0, 82.0 mm | USB-C centre |
| `power_entry_h` | 14 mm | Height of X5's wire entry above the PCB |

Measured on a real board: the X5 block is the tallest part at 28 mm above the PCB, and the
output blocks' wire entries are at 13 mm (lower) and 21 mm (upper). The entries are only 8 mm
apart, which is too close for staggered M12 lock-nuts, so the gland rows are spread to
11.5 mm (`gland_row_dz`) and sit at 10.5 and 22 mm. Each cable bends by 1–2.5 mm on its way
in, which the 11 mm front gap takes easily.

## Hardware per enclosure

| Item | Qty |
|---|---|
| M3 heat-set insert, 4.0–4.2 mm OD, 4–5 mm long | 8 |
| M3 × 6 screw, board to standoffs | 4 |
| M3 × 8 screw, lid | 4 |
| M12 × 1.5 cable gland (3–6.5 mm cable) | up to 8, one per output in use |
| M16 × 1.5 cable gland | 1, power in |
| 4 mm countersunk wood screw + plug | 4 |

For rack 1's second board (6 strands), set O7 and O8 to `false` in `outputs_used` and print
it with 6 output holes.

## Print settings

PETG, 0.2 mm layers, 4 perimeters, 25–40 % gyroid. Print the base floor-down and the lid
outer-face-down (`part = "print"` lays out both). No supports: the wall holes are teardrops,
and the gland's hex and sealing washer cover the point.
