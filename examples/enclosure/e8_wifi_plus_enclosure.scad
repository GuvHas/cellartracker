// =============================================================================
//  E8-WiFi Plus wall enclosure  (Lightish / computerstyretjulelys.dk)
//  Two-piece PETG enclosure: base with board standoffs, cable glands and
//  wall-mount flanges, plus a lid held by four M3 screws into heat-set inserts.
// =============================================================================
//
//  WHAT IS KNOWN AND WHAT IS NOT
//  -----------------------------
//  From the vendor datasheet (E8-WiFi Plus V1.01, English):
//    * Board / product envelope: 135 x 85 x 26 mm  (W x D x H)
//    * X1-X4: pixel outputs O1-O8, two per double-level spring terminal,
//             0.5-1 mm2 with ferrule, strip 9-10 mm
//    * X5:    main power input 5-24 V, 0.5-6 mm2, strip 15-16 mm
//    * X6:    EXT PWR input,  X7: two button inputs (spring terminals)
//    * USB-C: programming. V1.02 changed it from horizontal to VERTICAL.
//    * ESP32 with an external antenna lead.
//  Positions below were scaled off the vendor's "Board Dimensions" photo of
//  a V1.02 board (135 x 85 mm, about 4.8 px/mm), so treat them as +-1 mm.
//  Values tagged [CHECK] are worth a caliper check before printing.
//  Board layout, seen from above with the terminals towards you:
//    * FRONT edge (-Y), left to right: X1 X2 X3 X4 (outputs, each block has
//      O-odd on the upper/back level and O-even on the lower/front level,
//      pins - D +), then X5 INPUT (orange levers) at the right.
//    * BACK edge (+Y): ESP32 module with the u.FL antenna socket, vertical
//      USB-C, X7 BTN INPUT and X6 EXT PWR (both unused here).
//    * Four M3 mounting holes on a 127 x 77 mm rectangle, centred on the
//      board (measured on a real board).
//
//  COORDINATES (assembled, lying on its back as if the wall were the floor)
//    X = length (along the outputs), Y = depth, Z = away from the wall.
//    The base's back face (wall side) is z = 0.
//
//  HOW TO USE
//    Set `part` below, press F6, export STL.
//      "assembly" - base + lid + ghost board, for checking
//      "base"     - base only, print orientation (floor on the bed)
//      "lid"      - lid only, flipped for printing (outer face on the bed)
//      "print"    - base and lid side by side, both in print orientation
//
//  PRINT NOTES (PETG)
//    * 0.2 mm layers, 4 perimeters (gives a solid 3 mm wall at 0.45 mm width),
//      25-40 % gyrid infill. No supports needed: the side holes are
//      teardrop-shaped so they bridge cleanly.
//    * Heat-set inserts: M3 x 4-5 mm long, 4.0-4.2 mm OD knurled brass.
//      Press at ~230 C. If you would rather self-tap, set
//      `insert_hole_d = 2.6` and use M3 (or 3.5 mm PT-type) self-tappers.
//
// =============================================================================


/* [Render] */
part = "assembly";          // ["assembly", "base", "lid", "print"]
show_board_ghost = true;    // translucent board in assembly view
$fn = 64;


/* [Board - E8-WiFi Plus] */
board_l      = 135.0;       // PCB length along X (datasheet)
board_w      = 85.0;        // PCB depth along Y (datasheet)
board_t      = 1.6;         // PCB thickness                           [CHECK]
board_comp_h = 24.4;        // tallest part above the PCB top surface   [CHECK]
                            //   (datasheet overall height 26 mm minus PCB)
board_under_h = 3.0;        // tallest solder joint / lead under the PCB [CHECK]

// Mounting holes: a rectangle of hole centres, centred on the board
// (measured on a real board).
hole_span_x  = 127.0;
hole_span_y  = 77.0;


/* [Material & tolerances] */
wall      = 3.0;            // side wall thickness (2.5-3 mm recommended)
floor_t   = 3.0;            // base floor thickness (this face sits on the wall)
lid_t     = 3.0;            // lid plate thickness
fit_clear = 0.3;            // slip-fit clearance, lid lip to base wall (0.25-0.3)
board_clear = 1.0;          // gap between PCB edge and anything else
fillet_r  = 3.0;            // internal cavity corner / floor fillet (>= 1.5)
post_fillet = 1.5;          // fillet at the root of standoffs and bosses
edge_round = 1.5;           // rounding on the outer top edge of the lid


/* [Cavity layout] */
end_bay   = 14.0;           // free space at each short end. Must clear the
                            //   lid-screw bosses AND the X1 gland's lock nut.
front_bay = 18.0;           // free space in front of the terminals: gland
                            //   lock-nut, then the cores fan out to - D +
back_bay  = 10.0;           // extra space behind the board, along the top
                            //   (+Y) wall, for routing the antenna lead
top_clear = 3.0;            // air between tallest component and the lid lip


/* [Board standoffs] */
standoff_d     = 8.0;
standoff_h     = 7.0;       // floor top to PCB underside (>= board_under_h + 2)
insert_hole_d  = 4.2;       // heat-set insert bore (4.0-4.5). 2.6 for self-tapping
insert_depth   = 5.0;       // insert bore depth (4-5)
screw_relief_d = 2.8;       // extra bore below the insert for the screw tip
screw_relief_h = 1.5;


/* [Lid screws & bosses] */
boss_d         = 9.0;       // corner boss diameter (in the cavity corners)
boss_inset     = 5.0;       // boss centre distance from the inner wall faces
lid_screw_d    = 3.4;       // M3 clearance hole in the lid
lid_head_d     = 6.4;       // counterbore for an M3 socket/pan head
lid_head_depth = 1.2;       // counterbore depth (0 = flat lid, head sits proud)
lip_h          = 5.0;       // lid lip depth into the base
lip_t          = 2.0;       // lid lip thickness


/* [Wall mounting] */
flange_w      = 14.0;       // how far each mounting flange sticks out
flange_t      = 5.0;        // flange thickness
flange_hole_inset = 10.0;   // screw centre from the flange's Y ends
mount_shank_d = 4.5;        // clearance for a 4 mm wood/plug screw
mount_head_d  = 8.5;        // countersunk head diameter (90 deg)
flange_fillet = 3.0;        // fillet between flange top and side wall


/* [Output cable entries (X1-X4, front wall)] */
// Each double-level block gets two glands, staggered: the lower gland feeds
// the lower (even) output, the upper gland the upper (odd) output. Keeps
// every cable straight in front of its own terminal.
block_x        = [10.2, 36.7, 64.2, 89.9];  // middle (D) pin of X1..X4,
                                            //   from board's left edge [CHECK]
outputs_used   = [true, true, true, true, true, true, true, true]; // O1..O8
                            // Rack 1's second board drives 6 strands: set
                            // O7/O8 false to leave those holes out.
output_hole_d  = 12.2;      // M12x1.5 cable gland (fits ~3-6.5 mm cable).
                            //   Use 7.0 for a plain rubber grommet instead.
gland_nut_ac   = 17.4;      // gland lock-nut across corners (M12: AF15)
pair_dx        = 6.5;       // each gland's X offset from its block centre
lower_z        = 11.5;      // lower-row centre above the floor's top
upper_z        = 23.5;      // upper-row centre above the floor's top

// Optional zip-tie anchor rib behind the front wall (for grommets instead
// of glands -- glands already clamp the cable).
tie_bar        = false;
tie_bar_gap    = 3.0;       // rib distance from the inner front wall
tie_bar_t      = 3.0;
tie_bar_h      = 8.0;
tie_slot_w     = 4.5;       // zip-tie width + clearance
tie_slot_h     = 2.2;       // zip-tie thickness + clearance


/* [Power entry (X5, front wall)] */
power_hole_d   = 15.2;      // M16x1.5 gland, takes a 2-core 1.5 mm2 cable
power_nut_ac   = 22.0;      // M16 lock-nut across corners (AF19)
power_x        = 119.2;     // X5 centre from board's left edge         [CHECK]
power_z        = 17.5;      // centre above the floor's top


/* [Antenna (back wall)] */
antenna_hole   = true;
antenna_hole_d = 6.6;       // RP-SMA bulkhead. 4.0 for just the lead.
antenna_x      = 48.6;      // u.FL socket, from board's left edge      [CHECK]
antenna_z_above_pcb = 12.0;


/* [USB-C] */
usb_mode    = "lid";        // ["lid", "wall", "none"]
// "lid": window in the lid over a vertical USB-C (board V1.02)
usb_x       = 87.0;         // connector centre from board's left edge  [CHECK]
usb_y       = 82.0;         // connector centre from board's front edge [CHECK]
usb_win_l   = 14.0;         // window size: plug overmould + 2 mm
usb_win_w   = 8.5;          //   (also cut through the lid lip, which sits
                            //   right over this connector)
// "wall": horizontal USB-C (board V1.01), cut through the back wall (+Y)
usb_wall_z_above_pcb = 1.6; // receptacle centre above the PCB top
usb_wall_w  = 13.0;
usb_wall_h  = 7.5;


// =============================================================================
//  Derived dimensions -- normally no need to edit below this line
// =============================================================================

cav_l = board_l + 2*board_clear + 2*end_bay;
cav_w = board_w + 2*board_clear + front_bay + back_bay;
cav_h = standoff_h + board_t + board_comp_h + top_clear + lip_h;

out_l  = cav_l + 2*wall;
out_w  = cav_w + 2*wall;
base_h = floor_t + cav_h;
out_r  = fillet_r + wall;           // outer corner radius follows the cavity

// Board origin (front-left corner, PCB underside)
bx = wall + end_bay + board_clear;
by = wall + front_bay + board_clear;
bz = floor_t + standoff_h;
pcb_top = bz + board_t;

// Mounting-hole positions from the board's front-left corner
board_holes = [
    for (sx = [-1, 1], sy = [-1, 1])
        [board_l/2 + sx*hole_span_x/2, board_w/2 + sy*hole_span_y/2]
];

// Lid-screw boss centres
boss_pos = [
    [wall + boss_inset,         wall + boss_inset],
    [wall + cav_l - boss_inset, wall + boss_inset],
    [wall + boss_inset,         wall + cav_w - boss_inset],
    [wall + cav_l - boss_inset, wall + cav_w - boss_inset]
];

assert(end_bay > boss_inset + boss_d/2,
       "end_bay too small: the lid-screw bosses would hit the board");
assert(standoff_h >= board_under_h + 2,
       "standoff_h too low for the solder side of the board");
// Glands: [x, z, hole_d, nut_ac] for every front-wall entry in use
output_glands = [
    for (i = [0 : 7]) if (outputs_used[i])
        [bx + block_x[floor(i/2)] + (i % 2 == 0 ? pair_dx : -pair_dx),
         floor_t + (i % 2 == 0 ? upper_z : lower_z),
         output_hole_d, gland_nut_ac]
];
front_glands = concat(output_glands,
    [[bx + power_x, floor_t + power_z, power_hole_d, power_nut_ac]]);

boss_reach = wall + boss_inset + boss_d/2;
assert(front_glands[0][0] - front_glands[0][3]/2 > boss_reach,
       "left gland nut hits the corner boss: raise end_bay");
assert(bx + power_x + power_nut_ac/2 < out_l - boss_reach,
       "power gland nut hits the corner boss: raise end_bay");
for (a = front_glands, b = front_glands)
    if (a != b)
        assert(norm([a[0] - b[0], a[1] - b[1]]) >= (a[3] + b[3])/2 - 0.5,
               str("gland nuts overlap at x=", a[0], " and x=", b[0]));
assert(upper_z + gland_nut_ac/2 < cav_h - lip_h,
       "upper glands reach into the lid lip");

eps = 0.01;


// =============================================================================
//  Small helpers
// =============================================================================

// Rounded rectangle, corner at origin
module rrect(l, w, r) {
    r2 = min(r, l/2 - eps, w/2 - eps);
    translate([r2, r2]) offset(r = r2) square([l - 2*r2, w - 2*r2]);
}

// Teardrop: a horizontal hole that prints without support (point up, +Z)
module teardrop_2d(d) {
    union() {
        circle(d = d);
        rotate(45) square(d/2);
    }
}

// Horizontal hole through a wall along +Y (rotated as needed by caller)
module hole_y(d, len) {
    rotate([-90, 0, 0]) linear_extrude(len) rotate(0) mirror([0, 1]) teardrop_2d(d);
}
module hole_x(d, len) {
    rotate([0, 90, 0]) linear_extrude(len) rotate(90) teardrop_2d(d);
}

// Cylinder with a concave fillet at its foot
module filleted_post(d, h, f) {
    rotate_extrude()
        difference() {
            union() {
                square([d/2, h]);
                square([d/2 + f, f]);
            }
            translate([d/2 + f, f]) circle(r = f);
        }
}

// Cavity: rounded box whose vertical corners AND floor edges are filleted
// (hull of spheres at the floor and cylinders above them).
module filleted_cavity(l, w, h, r) {
    hull()
        for (x = [r, l - r], y = [r, w - r]) {
            translate([x, y, r]) sphere(r = r);
            translate([x, y, r]) cylinder(r = r, h = h - r + eps);
        }
}


// =============================================================================
//  Base
// =============================================================================

module base_shell() {
    difference() {
        linear_extrude(base_h) rrect(out_l, out_w, out_r);
        translate([wall, wall, floor_t])
            filleted_cavity(cav_l, cav_w, cav_h + 1, fillet_r);
    }
}

module standoffs() {
    for (p = board_holes)
        translate([bx + p[0], by + p[1], floor_t - eps])
            difference() {
                filleted_post(standoff_d, standoff_h + eps, post_fillet);
                translate([0, 0, standoff_h - insert_depth])
                    cylinder(d = insert_hole_d, h = insert_depth + 1);
                translate([0, 0, standoff_h - insert_depth - screw_relief_h])
                    cylinder(d = screw_relief_d, h = screw_relief_h + eps);
            }
}

// Corner boss: hull of the boss and the cavity corner, so it blends into
// both walls with obtuse (not sharp) junctions.
module corner_boss_solid(p) {
    cx = p[0] < out_l/2 ? wall : wall + cav_l - 1;
    cy = p[1] < out_w/2 ? wall : wall + cav_w - 1;
    hull() {
        translate([p[0], p[1], floor_t - eps]) cylinder(d = boss_d, h = cav_h + eps);
        translate([cx, cy, floor_t - eps]) cube([1, 1, cav_h + eps]);
    }
    // root fillet against the floor
    translate([p[0], p[1], floor_t - eps])
        filleted_post(boss_d, post_fillet, post_fillet);
}

module corner_bosses() {
    for (p = boss_pos)
        difference() {
            corner_boss_solid(p);
            translate([p[0], p[1], base_h - insert_depth])
                cylinder(d = insert_hole_d, h = insert_depth + 1);
            translate([p[0], p[1], base_h - insert_depth - 4])
                cylinder(d = screw_relief_d, h = 4 + eps);
        }
}

module mount_flanges() {
    for (side = [0, 1]) {
        x0 = side == 0 ? -flange_w : out_l;
        // flange plate, overlapping into the base so it fuses with the wall
        difference() {
            translate([side == 0 ? x0 : x0 - out_r, 0, 0])
                linear_extrude(flange_t)
                    rrect(flange_w + out_r, out_w, out_r);
            for (y = [flange_hole_inset, out_w - flange_hole_inset])
                translate([x0 + flange_w/2, y, 0]) countersunk_hole();
        }
        // fillet between flange top face and side wall
        fx = side == 0 ? 0 : out_l;
        translate([fx, out_r, flange_t])
            rotate([-90, 0, 0])
                linear_extrude(out_w - 2*out_r)
                    mirror([side == 0 ? 0 : 1, 0])
                        mirror([0, 1])
                        difference() {
                            translate([-flange_fillet, 0]) square(flange_fillet);
                            translate([-flange_fillet, flange_fillet]) circle(r = flange_fillet);
                        }
    }
}

module countersunk_hole() {
    translate([0, 0, -1]) cylinder(d = mount_shank_d, h = flange_t + 2);
    cs_h = (mount_head_d - mount_shank_d) / 2;
    translate([0, 0, flange_t - cs_h])
        cylinder(d1 = mount_shank_d, d2 = mount_head_d, h = cs_h + eps);
    translate([0, 0, flange_t]) cylinder(d = mount_head_d, h = 20);
}

module tie_bar_rib() {
    y0 = wall + tie_bar_gap;
    xs = [for (g = output_glands) g[0]];
    x_lo = min(xs) - output_hole_d;
    x_hi = max(xs) + output_hole_d;
    difference() {
        translate([x_lo, y0, floor_t - eps])
            cube([x_hi - x_lo, tie_bar_t, tie_bar_h]);
        // a tunnel through the rib's foot either side of each entry
        for (x = xs, sgn = [-1, 1])
            translate([x + sgn*output_hole_d*0.45 - tie_slot_w/2, y0 - 1, floor_t + 1])
                cube([tie_slot_w, tie_bar_t + 2, tie_slot_h]);
    }
}

module base_cutouts() {
    // output and power glands, front wall
    for (g = front_glands)
        translate([g[0], -1, g[1]]) hole_y(g[2], wall + 2);

    // antenna, back wall
    if (antenna_hole)
        translate([bx + antenna_x, out_w - wall - 1, pcb_top + antenna_z_above_pcb])
            hole_y(antenna_hole_d, wall + 2);

    // horizontal USB-C through the back wall
    if (usb_mode == "wall")
        translate([bx + usb_x - usb_wall_w/2, out_w - wall - 1,
                   pcb_top + usb_wall_z_above_pcb - usb_wall_h/2])
            rotate([90, 0, 0]) mirror([0, 0, 1])
                linear_extrude(wall + 2) rrect(usb_wall_w, usb_wall_h, 2);
}

module base() {
    difference() {
        union() {
            base_shell();
            standoffs();
            corner_bosses();
            mount_flanges();
            if (tie_bar) tie_bar_rib();
        }
        base_cutouts();
    }
}


// =============================================================================
//  Lid (modelled in assembled position, sitting on top of the base)
// =============================================================================

module lid_plate() {
    // plate with a rounded outer top edge: hull of inset slices along a
    // quarter circle
    r = edge_round;
    hull() {
        linear_extrude(lid_t - r) rrect(out_l, out_w, out_r);
        for (a = [0 : 15 : 90]) {
            inset = r - r * cos(a);
            translate([inset, inset, lid_t - r + r * sin(a) - eps])
                linear_extrude(eps)
                    rrect(out_l - 2*inset, out_w - 2*inset, out_r - inset);
        }
    }
}

module lid_lip() {
    o = fit_clear;
    difference() {
        translate([wall + o, wall + o, -lip_h])
            linear_extrude(lip_h + eps)
                difference() {
                    rrect(cav_l - 2*o, cav_w - 2*o, fillet_r - o);
                    translate([lip_t, lip_t])
                        rrect(cav_l - 2*o - 2*lip_t, cav_w - 2*o - 2*lip_t,
                              max(fillet_r - o - lip_t, 0.5));
                }
        // clear the corner bosses
        for (p = boss_pos)
            translate([0, 0, -lip_h - 1])
                linear_extrude(lip_h + 2)
                    offset(delta = fit_clear)
                        hull() {
                            translate([p[0], p[1]]) circle(d = boss_d);
                            translate([p[0] < out_l/2 ? wall - 1 : wall + cav_l,
                                       p[1] < out_w/2 ? wall - 1 : wall + cav_w])
                                square(1);
                        }
    }
}

module lid() {
    // lid screw: M3 x (lid_t - lid_head_depth + insert_depth), e.g. M3x6/M3x8
    translate([0, 0, base_h])
    difference() {
        union() {
            lid_plate();
            lid_lip();
        }
        for (p = boss_pos) {
            translate([p[0], p[1], -lip_h - 1]) cylinder(d = lid_screw_d, h = lid_t + lip_h + 2);
            if (lid_head_depth > 0)
                translate([p[0], p[1], lid_t - lid_head_depth])
                    cylinder(d = lid_head_d, h = lid_head_depth + 1);
        }
        if (usb_mode == "lid")
            translate([bx + usb_x - usb_win_l/2, by + usb_y - usb_win_w/2, -lip_h - 1])
                linear_extrude(lid_t + lip_h + 2) rrect(usb_win_l, usb_win_w, 2);
    }
}


// =============================================================================
//  Ghost board (assembly view only)
// =============================================================================

module board_ghost() {
    color("green", 0.5) difference() {
        translate([bx, by, bz]) cube([board_l, board_w, board_t]);
        for (p = board_holes)
            translate([bx + p[0], by + p[1], bz - 1]) cylinder(d = 3.2, h = 5);
    }
    // component envelope
    color("grey", 0.15)
        translate([bx, by, pcb_top]) cube([board_l, board_w, board_comp_h]);
    // output terminal blocks X1-X4 and input X5 (rough, front edge)
    for (x = block_x)
        color("DimGray", 0.7)
            translate([bx + x - 10.5, by, pcb_top]) cube([21, 25, 16]);
    color("Orange", 0.7)
        translate([bx + power_x - 9, by, pcb_top]) cube([18, 24, 18]);
}


// =============================================================================
//  Part selection
// =============================================================================

module lid_print() {
    // flip so the outer face is on the bed
    translate([0, out_w, base_h + lid_t]) rotate([180, 0, 0]) lid();
}

if (part == "assembly") {
    color("SteelBlue") base();
    color("LightSteelBlue", 0.6) lid();
    if (show_board_ghost) board_ghost();
} else if (part == "base") {
    base();
} else if (part == "lid") {
    lid_print();
} else if (part == "print") {
    base();
    translate([0, out_w + 10, 0]) lid_print();
}

echo(str("Outer size (without flanges): ", out_l, " x ", out_w, " x ",
         base_h + lid_t, " mm"));
echo(str("Footprint with flanges: ", out_l + 2*flange_w, " x ", out_w, " mm"));
echo(str("Cavity: ", cav_l, " x ", cav_w, " x ", cav_h, " mm"));
