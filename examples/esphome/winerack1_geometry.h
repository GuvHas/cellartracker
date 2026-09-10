// The shape of rack 1, in one place.
// =============================================================================
//
// A U: rows A-H carry bins 1-4 and 10-13, rows I-M run the full width. 129 bins
// inside a 13 x 13 envelope, on thirteen strips - one per bin column, each on
// its own GPIO.
//
// This is the only file that knows the rack is U-shaped. The effect lambdas in
// winerack1led.yaml ask `for_each_bin` which bins their column has; the Home
// Assistant side sends a full 13 x 13 grid and lets the bins that do not exist
// come through empty. Change the rack, change this table, and the firmware
// follows - the static_asserts below will stop the build if the arithmetic no
// longer adds up.
//
// The numbers here are duplicated by `num_leds:` on each light in the YAML,
// because ESPHome needs that as a literal. tests/test_rack_leds_example.py
// reads both and fails if they ever disagree.

#pragma once

#include "rack_geometry.h"

namespace winerack1 {

/// Envelope columns. Index 0 is bin column 1; `first_bin` 0 is row A, 8 is row I.
constexpr int kEnvelopeColumns = 13;
constexpr int kLedsPerBin = 6;
constexpr int kBinPitch = 9;

constexpr rack::Column kColumns[] = {
    {0, 13},  // column 1   rows A-M   the U's left arm
    {0, 13},  // column 2   rows A-M
    {0, 13},  // column 3   rows A-M
    {0, 13},  // column 4   rows A-M
    {8, 5},   // column 5   rows I-M   the opening: no bins above row I
    {8, 5},   // column 6   rows I-M
    {8, 5},   // column 7   rows I-M
    {8, 5},   // column 8   rows I-M
    {8, 5},   // column 9   rows I-M
    {0, 13},  // column 10  rows A-M   the right arm
    {0, 13},  // column 11  rows A-M
    {0, 13},  // column 12  rows A-M
    {0, 13},  // column 13  rows A-M
};

constexpr rack::Geometry kRack{kColumns, kEnvelopeColumns, kLedsPerBin, kBinPitch};

// Checked when the firmware is compiled, not when it runs. A table that no
// longer describes a buildable rack fails here rather than at 3 a.m. in a
// cellar.
static_assert(kRack.valid(), "rack 1 geometry is not buildable");
static_assert(kRack.rows() == 13, "rack 1 envelope should be 13 rows");
static_assert(kRack.bins() == 129, "rack 1 should have 129 bins");
static_assert(kRack.total_leds() == 1122, "rack 1 should be 1122 pixels");
static_assert(kRack.strand_leds(0) == 114, "a full-height column is 114 pixels");
static_assert(kRack.strand_leds(4) == 42, "a column in the opening is 42 pixels");

}  // namespace winerack1
