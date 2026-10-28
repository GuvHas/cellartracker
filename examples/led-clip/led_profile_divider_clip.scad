// =============================================================================
//  LED profile clip for diamond-set wine rack dividers
//  Snaps over a 37 mm square wooden divider that sits corner-up (rotated
//  45 deg) and holds a 16 x 16 mm aluminium corner LED profile in a slide-in
//  channel on top. Designed for PETG, printed with no supports.
// =============================================================================
//
//  ASSUMPTIONS (check these against the real parts)
//  ------------------------------------------------
//  * The divider is a square 37 x 37 mm stick, turned 45 deg so one corner
//    points straight up and two corners point sideways. Its upper corner is
//    a 90 deg convex edge, which the clip's saddle wraps.
//  * The LED profile is a 90 deg CORNER profile: two flat 16 mm backs at a
//    right angle (the "V"), with the diffuser (flat, angled or half-round)
//    across the open side, where the 10 mm strip sits. A corner profile's
//    backs form a CONVEX right angle, so it cannot sit directly on the
//    divider's convex top corner. The clip therefore carries a concave 90 deg
//    V-channel on top of the saddle: the profile's backs nest in the channel
//    and the diffuser faces up (or wherever `aim_angle` points it).
//  * The aluminium has a small edge/flange where each back meets the
//    diffuser. The channel's two lips hook over those edges by
//    `lip_overlap`, so the profile slides in from the end and cannot lift
//    out. If your diffuser bulges out over the full width, lower
//    `lip_overlap` (or set it to 0 and rely on the crush ribs).    [CHECK]
//  * The rail is clear under its two side corners, so the saddle's hooks can
//    wrap `grip_depth` past them. If something sits right below, set
//    `grip_depth = 0` and the clip becomes a rest-on saddle (glue or a
//    screw then holds it).
//
//  COORDINATES
//    X = across the divider (front/back of the rack), Y = up,
//    Z = along the divider and along the LED profile.
//    The divider's centre line is the Z axis.
//    The cross-section is drawn in XY and extruded along Z, so the model is
//    already in print orientation: one end face on the bed.
//
//  HOW TO USE
//    Set `part`, press F6, export STL.
//      "clip"     - one clip, print orientation
//      "assembly" - clip with ghost divider and ghost profile, for checking
//      "print"    - `print_count` clips in a row, ready to slice
//    Mount: push the clip straight down over the divider until the hooks
//    click under the side corners. Fit all clips along a row (two per bin
//    width is plenty, roughly every 150-200 mm), then slide the profile
//    through them from one end.
//
//  PRINT NOTES (PETG)
//    * Print as modelled (end face on the bed). Every layer then holds the
//      whole cross-section, so the hook arms flex within a layer, which is
//      the strong direction. No supports needed.
//    * 0.2 mm layers, 4 perimeters (a solid 2.5 mm wall at 0.45 mm width),
//      100 % infill is cheap here and makes the hooks springier and tougher.
//    * Print one first and adjust `divider_clear`, `profile_tol` and
//      `crush` until both fits feel right. Wood dimensions vary, so measure
//      the real divider rather than trusting the nominal 37 mm.
//
// =============================================================================


/* [Render] */
part        = "assembly";   // ["clip", "assembly", "print"]
print_count = 4;            // clips laid out for "print"
$fn = 64;


/* [Wooden divider] */
divider_side  = 37.0;       // square section, side length         [CHECK]
divider_clear = 0.4;        // gap between wood and saddle, per face. Wood
                            //   swells and varies, so this is looser than
                            //   the profile fit.
wood_relief_r = 1.0;        // round relief in the saddle's top corner so a
                            //   sharp (un-eased) wood edge still seats fully
grip_depth    = 2.5;        // how far the hooks reach BELOW the divider's
                            //   side corners (vertical mm). More = firmer
                            //   grip but harder to push on. 0 = no hooks.


/* [LED profile] */
profile_leg  = 16.0;        // length of each flat back of the corner profile
profile_tol  = 0.3;         // sliding clearance, per face (0.25-0.3 PETG)
lip_overlap  = 1.2;         // how far each lip hooks over the profile's
                            //   front edge (along X before aim rotation) [CHECK]
crush        = 0.15;        // crush-rib interference with the profile backs.
                            //   Ribs run along Z, so the profile still slides,
                            //   but stays put. 0 = no ribs.
rib_r        = 0.6;         // crush-rib radius
aim_angle    = 0;           // tilts the channel about the profile's back
                            //   corner. 0 = diffuser faces straight up,
                            //   +/-30 aims it towards the rack front/back.
                            //   Keep within about +/-45.


/* [Clip body] */
wall        = 2.5;          // minimum wall everywhere (>= 2.5 for PETG)
lip_t       = 2.5;          // thickness of the retaining lips
clip_len    = 15.0;         // length along the divider (Z)
round_r     = 1.0;          // rounding of all outside edges and hook tips
                            //   (must stay below wall/2)
fillet_r    = 4.0;          // fillet where the channel meets the saddle
bridge_drop = 12.0;         // how far down the saddle faces the solid
                            //   channel support reaches. The arms below
                            //   that stay at `wall` so they can flex.


// =============================================================================
//  Derived dimensions -- normally no need to edit below this line
// =============================================================================

s2 = sqrt(2);
cav_side = divider_side + 2*divider_clear;  // saddle cavity square
cav_h    = cav_side/2*s2;                   // cavity top corner above centre
out_h    = cav_h + wall*s2;                 // saddle outer top corner

pa       = profile_leg/s2;                  // half hypotenuse = channel depth

// The profile's back corner (channel bottom) sits far enough above the
// cavity that `wall` of solid remains between the two relief cuts.
seat_y   = cav_h + wood_relief_r + wall + 0.8;
seat_relief_r = 0.8;

big = 200;                                  // "infinite" for 2D cuts

echo(str("Clip: ", clip_len, " mm long, top of channel ",
         seat_y + pa + profile_tol + lip_t - cav_h + wall,
         " mm above the divider's top corner (before rounding)"));


// =============================================================================
//  Helpers
// =============================================================================

// Rounds every convex corner of a 2D shape by r.
module round_convex(r)  { offset(r = r) offset(delta = -r) children(); }

// Fills every concave corner of a 2D shape with a radius-r fillet.
module fill_concave(r)  { offset(r = -r) offset(delta = r) children(); }

// Square, rotated so one corner points up (+Y). `side` is the side length.
module diamond(side) { rotate(45) square(side, center = true); }

// Places children in the channel's frame: origin at the profile's back
// corner, V opening along +Y (then tilted by aim_angle).
module at_seat() { translate([0, seat_y]) rotate(aim_angle) children(); }


// =============================================================================
//  2D cross-section
// =============================================================================

// Channel outline in its own frame: the V walls plus the lip band on top.
module seat_outer_2d() {
    top = pa + profile_tol + lip_t;
    intersection() {
        offset(delta = wall)
            polygon([[0, 0], [top + 10, top + 10], [-(top + 10), top + 10]]);
        translate([-big, -big]) square([2*big, big + top]);
    }
}

// What the profile needs: its triangle (+ clearance), a slot over the
// diffuser between the lips, and a small relief at the back corner.
module seat_pocket_2d() {
    offset(delta = profile_tol)
        polygon([[0, 0], [pa, pa], [-pa, pa]]);
    translate([-(pa - lip_overlap), pa - 2]) square([2*(pa - lip_overlap), big]);
    circle(r = seat_relief_r);
}

// Crush ribs: half-round bumps on each back face, at mid-leg. They stand
// `crush` proud of the nominal profile surface.
module crush_ribs_2d() {
    if (crush > 0)
        for (m = [-1, 1]) {
            n = [m, -1] / s2;                       // outward face normal
            p = [m*pa/2, pa/2] + n*(rib_r - crush); // rib centre
            translate(p) circle(r = rib_r, $fn = 24);
        }
}

// Saddle outline (solid), cut off `grip_depth` below the side corners.
module saddle_outer_2d() {
    intersection() {
        diamond(cav_side + 2*wall);
        translate([-big, -grip_depth]) square([2*big, big]);
    }
}

module saddle_cavity_2d() {
    diamond(cav_side);
    translate([0, cav_h]) circle(r = wood_relief_r);   // top-corner relief
    translate([-big, -big]) square([2*big, big - grip_depth]); // open below
}

module clip_2d() {
    union() {
        round_convex(round_r)
            difference() {
                fill_concave(fillet_r)
                    union() {
                        saddle_outer_2d();
                        // solid support between saddle top and channel
                        hull() {
                            at_seat() seat_outer_2d();
                            intersection() {
                                saddle_outer_2d();
                                translate([-big, out_h - bridge_drop])
                                    square([2*big, big]);
                            }
                        }
                    }
                saddle_cavity_2d();
                at_seat() seat_pocket_2d();
            }
        // ribs only inside the channel, added after rounding so the
        // rounding does not erase them
        intersection() {
            at_seat() crush_ribs_2d();
            at_seat() offset(delta = profile_tol + 0.01)
                polygon([[0, 0], [pa, pa], [-pa, pa]]);
        }
    }
}


// =============================================================================
//  3D parts
// =============================================================================

module clip() { linear_extrude(height = clip_len) clip_2d(); }

// Ghost divider and profile, shown along Z in the "assembly" view.
module ghost_divider(len) {
    color("BurlyWood", 0.45)
        translate([0, 0, -len/2 + clip_len/2])
            linear_extrude(height = len) diamond(divider_side);
}

module ghost_profile(len) {
    t = 1.2;                    // aluminium wall, for looks only
    color("Silver", 0.6)
        translate([0, 0, -len/2 + clip_len/2])
            linear_extrude(height = len) at_seat() {
                difference() {
                    polygon([[0, 0], [pa, pa], [-pa, pa]]);
                    offset(delta = -t) polygon([[0, 0], [pa, pa], [-pa, pa]]);
                }
            }
    // diffuser (half-round lens over the hypotenuse)
    color("WhiteSmoke", 0.5)
        translate([0, 0, -len/2 + clip_len/2])
            linear_extrude(height = len) at_seat()
                translate([0, pa]) intersection() {
                    scale([1, 0.35]) circle(r = pa - lip_overlap - 0.2);
                    translate([-big/2, 0]) square(big);
                }
}


if (part == "clip") {
    clip();
} else if (part == "assembly") {
    rotate([90, 0, 0]) {        // stood upright: divider horizontal, as fitted
        color("SteelBlue") clip();
        ghost_divider(150);
        ghost_profile(130);
    }
} else if (part == "print") {
    pitch = (cav_side + 2*wall)*s2 + 6;    // saddle width across the diamond + gap
    for (i = [0 : print_count - 1])
        translate([i*pitch, 0, 0]) clip();
}
