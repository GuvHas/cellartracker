// =============================================================================
//  LED profile clip for diamond-set wine rack dividers
//  Snaps over a 37 mm square wooden divider that sits corner-up (rotated
//  45 deg) and carries a 16 x 16 mm aluminium corner LED profile ACROSS it,
//  so one long profile bridges several dividers behind the bottles. The
//  profile is tilted so the light shines towards the front of the rack.
//  Designed for PETG.
// =============================================================================
//
//  ASSUMPTIONS (check these against the real parts)
//  ------------------------------------------------
//  * The divider is a square 37 x 37 mm stick running front-to-back, turned
//    45 deg about its length so one corner points straight up and two point
//    sideways. The clip's saddle wraps its upper corner.
//  * The LED profile is a 90 deg CORNER profile: two flat 16 mm backs at a
//    right angle (the "V"), with the diffuser (flat, angled or half-round)
//    across the open side, where the 10 mm strip sits.
//  * `beam_angle` is the angle of the diffuser's facing direction, measured
//    from straight up towards the front of the rack. At the default 45 deg
//    the V lies as an "L": one back flat on a horizontal floor and the other
//    against a vertical back wall, with the light going out forwards and
//    upwards at 45 deg.
//  * The aluminium has a small edge where each back meets the diffuser. Two
//    lips hook over those edges by `lip_overlap`, so the profile slides in
//    from the end and cannot lift out. If your diffuser bulges out over the
//    full width, lower `lip_overlap` (0 = rely on the crush ribs).  [CHECK]
//  * The divider is clear under its two side corners where the clip sits,
//    so the hooks can wrap `grip_depth` past them. If not, set
//    `grip_depth = 0` and the clip becomes a rest-on saddle.
//
//  COORDINATES (as fitted)
//    X = left/right along the rack (the LED profile's length)
//    Y = front/back, along the divider (+Y = towards the FRONT of the rack)
//    Z = up
//    The divider's centre line is the Y axis.
//
//  HOW TO USE
//    Set `part`, press F6, export STL.
//      "clip"     - one clip in print orientation
//      "assembly" - clip as fitted, with ghost divider and ghost profile
//      "print"    - `print_count` clips in a row, in print orientation
//    Mount: push a clip straight down over the back end of each divider in
//    the row until the hooks click under the side corners. Line them up,
//    then slide the profile through all of them from one end.
//
//  PRINT NOTES (PETG)
//    * Printed standing on its BACK face (-Y on the bed). The saddle's
//      cross-section then lies in every layer, so the hooks flex within a
//      layer (their strong direction), the back wall of the channel is on
//      the bed, and at the default 45 deg beam every overhang is 45 deg or
//      less. No supports needed. Other beam angles may need a little
//      support under the front lip.
//    * 0.2 mm layers, 4 perimeters (a solid 2.5 mm wall at 0.45 mm width),
//      25-40 % gyroid infill for the solid block under the channel.
//    * Print one first and adjust `divider_clear`, `profile_tol` and
//      `crush` until both fits feel right. Wood varies, so measure the real
//      divider rather than trusting the nominal 37 mm.
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
wood_relief_r = 1.0;        // relief along the saddle's top inside corner
                            //   so a sharp (un-eased) wood edge still seats
grip_depth    = 2.5;        // how far the hooks reach BELOW the divider's
                            //   side corners (vertical mm). More = firmer
                            //   grip but harder to push on. 0 = no hooks.


/* [LED profile] */
profile_leg  = 16.0;        // length of each flat back of the corner profile
profile_tol  = 0.3;         // sliding clearance, per face (0.25-0.3 PETG)
lip_overlap  = 1.2;         // how far each lip hooks over the profile's
                            //   front edges                       [CHECK]
crush        = 0.15;        // crush-rib interference with the profile backs.
                            //   Ribs run along the profile, so it still
                            //   slides but stays put. 0 = no ribs.
rib_r        = 0.6;         // crush-rib radius


/* [Light direction] */
beam_angle   = 45;          // diffuser direction, degrees from straight up
                            //   towards the rack front (+Y). 0 = up,
                            //   90 = straight forward. Negative aims back.


/* [Clip body] */
wall          = 2.5;        // minimum wall everywhere (>= 2.5 for PETG)
lip_t         = 2.5;        // thickness of the retaining lips
channel_len   = 30.0;       // length of the channel along the profile (X)
saddle_depth  = 26.0;       // length of the saddle along the divider (Y).
                            //   26 covers the whole channel at 45 deg, so
                            //   the front lip has no overhang when printed
round_r       = 1.0;        // rounding of outside edges and hook tips
                            //   (must stay below wall/2)
fillet_r      = 4.0;        // fillet where the channel block meets the arms
bridge_drop   = 10.0;       // how far down the saddle faces the solid block
                            //   under the channel reaches. The arms below
                            //   stay at `wall` so they can flex.


// =============================================================================
//  Derived dimensions -- normally no need to edit below this line
// =============================================================================

s2 = sqrt(2);
cav_side = divider_side + 2*divider_clear;  // saddle cavity square
cav_h    = cav_side/2*s2;                   // cavity top corner above centre
out_h    = cav_h + wall*s2;                 // saddle outer top corner
out_w    = (cav_side + 2*wall)*s2;          // saddle width across the diamond

pa       = profile_leg/s2;                  // half hypotenuse = V depth
seat_relief_r = 0.8;                        // relief in the channel's corner

// Height of the profile's back corner (the channel's inside corner).
// At beam_angle 45 the profile's floor is flat at seat_z - profile_tol, and
// this keeps `wall` of solid over the cavity's relief cut.
seat_z   = cav_h + wood_relief_r + wall + seat_relief_r + profile_tol*s2;

// The saddle runs along Y from the back of the channel forwards. At
// beam_angle 45 this makes the channel's back wall flush with the saddle.
saddle_y0 = -(wall + profile_tol);

big = 300;                                  // "infinite" for 2D cuts

echo(str("Clip: saddle ", saddle_depth, " mm along the divider, channel ",
         channel_len, " mm along the profile, ", out_w,
         " mm wide over the hooks"));


// =============================================================================
//  Helpers
// =============================================================================

// Rounds every convex corner of a 2D shape by r.
module round_convex(r)  { offset(r = r) offset(delta = -r) children(); }

// Fills every concave corner of a 2D shape with a radius-r fillet.
module fill_concave(r)  { offset(r = -r) offset(delta = r) children(); }

// Square, rotated so one corner points up. `side` is the side length.
module diamond(side) { rotate(45) square(side, center = true); }

// 2D sketch in the FRONT view (2D x -> X, 2D y -> Z), extruded along Y.
module along_y(len, y0) {
    translate([0, y0 + len, 0]) rotate([90, 0, 0])
        linear_extrude(height = len) children();
}

// 2D sketch in the SIDE view (2D x -> Y, 2D y -> Z), extruded along X.
module along_x(len) {
    rotate([90, 0, 90]) linear_extrude(height = len, center = true) children();
}

// Places a side-view 2D sketch in the channel's frame: origin at the
// profile's back corner, V opening along the beam direction.
module at_seat() { translate([0, seat_z]) rotate(-beam_angle) children(); }


// =============================================================================
//  Side view (YZ): the channel and the saddle's depth
// =============================================================================

// Channel outline in its own frame: the V walls plus the lip band.
module seat_outer_2d() {
    top = pa + profile_tol + lip_t;
    intersection() {
        offset(delta = wall + profile_tol)
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

// Crush ribs: half-round bumps on each back face, at mid-leg, standing
// `crush` proud of the nominal profile surface.
module crush_ribs_2d() {
    if (crush > 0)
        for (m = [-1, 1]) {
            n = [m, -1] / s2;                       // outward face normal
            p = [m*pa/2, pa/2] + n*(rib_r - crush); // rib centre
            translate(p) circle(r = rib_r, $fn = 24);
        }
}

module side_silhouette_2d() {
    round_convex(round_r) fill_concave(fillet_r) {
        // saddle band, full height, `saddle_depth` long
        translate([saddle_y0, -big]) square([saddle_depth, big + out_h]);
        // channel, blended into the top of the saddle
        hull() {
            at_seat() seat_outer_2d();
            translate([saddle_y0, out_h - bridge_drop])
                square([saddle_depth, bridge_drop]);
        }
    }
}


// =============================================================================
//  Front view (XZ): the saddle and the block under the channel
// =============================================================================

// Saddle outline (solid), cut off `grip_depth` below the side corners.
module saddle_outer_2d() {
    intersection() {
        diamond(cav_side + 2*wall);
        translate([-big, -grip_depth]) square([2*big, big]);
    }
}

module saddle_cavity_2d() {
    diamond(cav_side);
    translate([0, cav_h]) circle(r = wood_relief_r);         // top relief
    translate([-big, -big]) square([2*big, big - grip_depth]); // open below
}

module front_silhouette_2d() {
    round_convex(round_r)
        difference() {
            fill_concave(fillet_r) union() {
                saddle_outer_2d();
                hull() {
                    intersection() {
                        saddle_outer_2d();
                        translate([-big, out_h - bridge_drop])
                            square([2*big, big]);
                    }
                    translate([-channel_len/2, seat_z - profile_tol - wall])
                        square([channel_len, big]);
                }
            }
            saddle_cavity_2d();
        }
}


// =============================================================================
//  3D parts
// =============================================================================

// The body is where the front and side silhouettes overlap; then the
// divider and the profile are cut out of it.
module clip() {
    difference() {
        intersection() {
            along_y(saddle_depth + 2*big, saddle_y0 - big)
                front_silhouette_2d();
            along_x(channel_len + 2*big) side_silhouette_2d();
        }
        along_y(2*big, -big) saddle_cavity_2d();
        along_x(2*big) difference() {
            at_seat() seat_pocket_2d();
            at_seat() crush_ribs_2d();
        }
    }
}

// Print orientation: back face (-Y) on the bed.
module clip_print() {
    translate([0, 0, -saddle_y0]) rotate([90, 0, 0]) clip();
}

// Ghost divider and profile for the "assembly" view.
module ghost_divider(len) {
    color("BurlyWood", 0.45)
        translate([0, saddle_y0 - 15, 0]) rotate([-90, 0, 0])
            linear_extrude(height = len) diamond(divider_side);
}

module ghost_profile(len) {
    t = 1.2;                    // aluminium wall, for looks only
    color("Silver", 0.7)
        along_x(len) at_seat() difference() {
            polygon([[0, 0], [pa, pa], [-pa, pa]]);
            offset(delta = -t) polygon([[0, 0], [pa, pa], [-pa, pa]]);
        }
    color("WhiteSmoke", 0.6)    // diffuser
        along_x(len) at_seat() translate([0, pa]) intersection() {
            scale([1, 0.35]) circle(r = pa - lip_overlap - 0.2);
            translate([-big/2, 0]) square(big);
        }
}


if (part == "clip") {
    clip_print();
} else if (part == "assembly") {
    color("SteelBlue") clip();
    ghost_divider(100);
    ghost_profile(160);
} else if (part == "print") {
    pitch = max(out_w, channel_len) + 6;    // widest view of the clip + gap
    for (i = [0 : print_count - 1])
        translate([i*pitch, 0, 0]) clip_print();
}
