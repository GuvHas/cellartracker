// The shape of rack 2, in one place.
// =============================================================================
//
// A plain 7 x 7: rows A-G, bins 1-7, every column the same height. Seven strips,
// one per bin column, each on its own GPIO.
//
// Because it is a rectangle it needs no per-column table - the four numbers are
// the whole description, which is what the uniform constructor is for. Compare
// winerack1_geometry.h, where the U forces a table.

#pragma once

#include "rack_geometry.h"

namespace winerack2 {

constexpr int kEnvelopeColumns = 7;
constexpr int kBinsPerColumn = 7;
constexpr int kLedsPerBin = 6;
constexpr int kBinPitch = 9;

constexpr rack::Geometry kRack{kEnvelopeColumns, kBinsPerColumn, kLedsPerBin, kBinPitch};

static_assert(kRack.valid(), "rack 2 geometry is not buildable");
static_assert(kRack.rows() == 7, "rack 2 should be 7 rows");
static_assert(kRack.bins() == 49, "rack 2 should have 49 bins");
static_assert(kRack.total_leds() == 420, "rack 2 should be 420 pixels");
static_assert(kRack.strand_leds(0) == 60, "each column is 60 pixels");

}  // namespace winerack2
