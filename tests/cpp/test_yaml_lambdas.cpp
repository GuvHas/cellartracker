// The maths in the ESPHome YAML, compiled and run on a workstation.
// =============================================================================
//
// Every #include of a .inc below is a block of C++ lifted verbatim out of the
// `substitutions:` of examples/esphome/winerack*led.yaml by yaml_lambda.py.
// Nothing in this file retypes the firmware's arithmetic - the wrappers set up
// the same names an addressable_lambda has in scope (`kCol`, `it`, `cell_rgb`)
// and then include the shipped text.
//
// Which is the point: an inline YAML lambda is normally only testable by
// flashing a board. Here the characters that reach the ESP32 are the characters
// doctest runs, so a test cannot pass against a copy that has drifted from what
// ships. If the YAML is edited, this file compiles the edit.
//
// The other half of the harness is FakeLight::operator[], which is std::vector
// ::at: an index past the end of a strand throws here and gets caught, where on
// the board it would write into whatever sits next in RAM.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <set>
#include <stdexcept>

#include "esphome_stubs.h"

// -----------------------------------------------------------------------------
// Rack 1 - the U
// -----------------------------------------------------------------------------
namespace rack1 {

// These four mirror the substitutions of the same name. They are duplicated
// here rather than generated because a test that derives its expectations from
// the thing under test proves nothing; the Python suite checks they agree.
constexpr int kRows = 13;
constexpr int kCols = 13;
constexpr int kLedsPerBin = 6;
constexpr int kBinPitch = 9;
constexpr int kTallStrand = 114;  // 13 bins, rows A-M
constexpr int kShortStrand = 42;  // 5 bins, rows I-M

/// What a lambda sees as `id(cell_rgb)`: the whole envelope, row-major.
uint8_t cell_rgb[kRows * kCols * 3];

void clear_cells() {
  for (uint8_t &channel : cell_rgb) channel = 0;
}

void set_cell(int row, int col, Color colour) {
  uint8_t *rgb = &cell_rgb[static_cast<size_t>((row * kCols + col) * 3)];
  rgb[0] = colour.r;
  rgb[1] = colour.g;
  rgb[2] = colour.b;
}

/// The shipped `bin_first_led`, called. The parameters are named unlike the
/// lambda's so that -Wshadow stays useful over the included text.
int first_led(int at_row, int from_row, int how_many) {
#include "rack1/bin_first_led.inc"
  return bin_first_led(at_row, from_row, how_many);
}

struct Extent {
  int first;
  int bins;
};

/// The shipped `column_extent`, for one column.
Extent extent_of(int kCol) {
#include "rack1/column_extent.inc"
  return Extent{kFirst, kBins};
}

/// A whole strand painted by the shipped `paint_column` - the three lines of a
/// light's lambda, in the order the light has them.
void paint(FakeLight &it, int kCol) {
#include "rack1/column_extent.inc"
#include "rack1/bin_first_led.inc"
#include "rack1/paint_column.inc"
}

/// The strand length a column's light declares as `num_leds`.
int strand_leds(int column) {
  return extent_of(column).bins == kRows ? kTallStrand : kShortStrand;
}

bool parse(const char *written, int *out_column, int *out_row) {
#include "rack1/parse_bin_id.inc"
  return parse_bin_id(written, out_column, out_row);
}

}  // namespace rack1

// -----------------------------------------------------------------------------
// Rack 2 - a plain 7 x 7
// -----------------------------------------------------------------------------
namespace rack2 {

constexpr int kRows = 7;
constexpr int kCols = 7;
constexpr int kStrand = 60;  // 7 bins of 6, pitch 9

uint8_t cell_rgb[kRows * kCols * 3];

int first_led(int at_row, int from_row, int how_many) {
#include "rack2/bin_first_led.inc"
  return bin_first_led(at_row, from_row, how_many);
}

struct Extent {
  int first;
  int bins;
};

Extent extent_of(int kCol) {
#include "rack2/column_extent.inc"
  return Extent{kFirst, kBins};
}

void paint(FakeLight &it, int kCol) {
#include "rack2/column_extent.inc"
#include "rack2/bin_first_led.inc"
#include "rack2/paint_column.inc"
}

}  // namespace rack2

// =============================================================================
// The direction the data line runs
// =============================================================================
//
// DIN enters at the FLOOR of every column and the strip runs upward, so that
// the thirteen feeds sit in a row along the bottom of the rack where they can
// be hidden. The rack is labelled with row A at the top - it is a U, and a U
// opens upward, so rows A-H are the arms and rows I-M are the solid base.
//
// Those two facts together are the whole of this suite: the LAST row of a
// column - the bottom of the rack, row M - has to be pixel 0, and the row
// letters count backwards along the strand from there.

TEST_SUITE("bottom-up indexing") {
  using namespace rack1;

  TEST_CASE("the bottom bin of a full column is the first LED on the strand") {
    // Row M, envelope row 12, is where the data line enters.
    CHECK(first_led(12, 0, 13) == 0);
  }

  TEST_CASE("the top bin of a full column is the last LEDs on the strand") {
    // Row A is furthest from the feed: twelve bins up, at pitch 9.
    CHECK(first_led(0, 0, 13) == 108);
    CHECK(108 + kLedsPerBin == kTallStrand);
  }

  TEST_CASE("row letters count backwards along the strand") {
    CHECK(first_led(12, 0, 13) == 0);    // M
    CHECK(first_led(11, 0, 13) == 9);    // L
    CHECK(first_led(10, 0, 13) == 18);   // K
    CHECK(first_led(1, 0, 13) == 99);    // B
    CHECK(first_led(0, 0, 13) == 108);   // A
  }

  TEST_CASE("a short column's bottom bin is also pixel zero") {
    // Columns 5-9 exist only for rows I-M. Their feed is at the same floor as
    // every other column's, so row M is pixel 0 there too - which is the whole
    // reason all thirteen data lines can be hidden along one skirting board.
    CHECK(first_led(12, 8, 5) == 0);
  }

  TEST_CASE("a short column's top bin is row I, four bins up") {
    CHECK(first_led(8, 8, 5) == 36);
    CHECK(36 + kLedsPerBin == kShortStrand);
  }

  TEST_CASE("the same row is at different pixels on a tall and a short column") {
    // Row I is the top of a short column and the ninth bin of a tall one. It
    // is the same shelf in the room, at different distances from two feeds.
    CHECK(first_led(8, 8, 5) == 36);
    CHECK(first_led(8, 0, 13) == 36);
    // Both happen to be 36 here, because both columns' feeds are at row M and
    // row I is four bins above it either way. That is a property of this rack,
    // not of the formula - check one where it is not true:
    CHECK(first_led(12, 8, 5) == 0);
    CHECK(first_led(12, 0, 13) == 0);
    CHECK(first_led(0, 0, 13) == 108);
    CHECK(first_led(0, 8, 5) == -1);  // row A is not on a short column at all
  }

  TEST_CASE("the pixel index falls as the row index rises") {
    for (int row = 1; row < kRows; row++) {
      CHECK(first_led(row, 0, kRows) < first_led(row - 1, 0, kRows));
    }
  }
}

TEST_SUITE("bounds") {
  using namespace rack1;

  TEST_CASE("a row above a short column is not on it") {
    for (int row = 0; row < 8; row++) {
      CAPTURE(row);
      CHECK(first_led(row, 8, 5) == -1);
    }
  }

  TEST_CASE("a row below the rack is not on any column") {
    CHECK(first_led(13, 0, 13) == -1);
    CHECK(first_led(99, 0, 13) == -1);
  }

  TEST_CASE("a negative row is refused rather than indexed backwards") {
    // (first + bins - 1 - row) grows without limit as row goes negative, so an
    // unchecked formula would hand back a plausible-looking index off the end.
    CHECK(first_led(-1, 0, 13) == -1);
    CHECK(first_led(-100, 0, 13) == -1);
  }

  TEST_CASE("a column with no bins has no LEDs") {
    CHECK(first_led(0, 0, 0) == -1);
    CHECK(first_led(0, 0, -3) == -1);
  }

  TEST_CASE("no bin ever runs past the end of its own strand") {
    for (int column = 0; column < kCols; column++) {
      const Extent extent = extent_of(column);
      const int leds = strand_leds(column);
      for (int row = extent.first; row < extent.first + extent.bins; row++) {
        CAPTURE(column);
        CAPTURE(row);
        const int first = first_led(row, extent.first, extent.bins);
        REQUIRE(first >= 0);
        CHECK(first + kLedsPerBin <= leds);
      }
    }
  }

  TEST_CASE("two bins on one column never light the same LED") {
    for (int column = 0; column < kCols; column++) {
      const Extent extent = extent_of(column);
      std::set<int> lit;
      for (int row = extent.first; row < extent.first + extent.bins; row++) {
        const int first = first_led(row, extent.first, extent.bins);
        for (int i = 0; i < kLedsPerBin; i++) {
          CAPTURE(column);
          CAPTURE(row);
          CHECK(lit.insert(first + i).second);
        }
      }
      CHECK(static_cast<int>(lit.size()) == extent.bins * kLedsPerBin);
    }
  }
}

// =============================================================================
// The column table
// =============================================================================

TEST_SUITE("column extents") {
  using namespace rack1;

  TEST_CASE("the arms of the U run the full height") {
    for (int column : {0, 1, 2, 3, 9, 10, 11, 12}) {
      CAPTURE(column);
      CHECK(extent_of(column).first == 0);
      CHECK(extent_of(column).bins == 13);
    }
  }

  TEST_CASE("the base of the U starts at row I") {
    for (int column : {4, 5, 6, 7, 8}) {
      CAPTURE(column);
      CHECK(extent_of(column).first == 8);
      CHECK(extent_of(column).bins == 5);
    }
  }

  TEST_CASE("a column outside the rack carries nothing") {
    // kCol is a literal in each light, so this cannot happen from a strand -
    // but light_bin passes a column that came off the network.
    CHECK(extent_of(-1).bins == 0);
    CHECK(extent_of(13).bins == 0);
    CHECK(extent_of(9999).bins == 0);
  }

  TEST_CASE("the rack has 129 bins in a 13 by 13 envelope") {
    int bins = 0;
    for (int column = 0; column < kCols; column++) bins += extent_of(column).bins;
    CHECK(bins == 129);
    CHECK(kRows * kCols == 169);
  }

  TEST_CASE("the strands add up to 1122 pixels") {
    int total = 0;
    for (int column = 0; column < kCols; column++) total += strand_leds(column);
    CHECK(total == 1122);
  }
}

// =============================================================================
// The painter, as shipped
// =============================================================================

TEST_SUITE("painting a strand") {
  using namespace rack1;

  TEST_CASE("the bottom row lands on the first LEDs") {
    clear_cells();
    set_cell(12, 0, Color(0, 110, 0));  // M1, ready
    FakeLight it(kTallStrand);
    paint(it, 0);

    for (int i = 0; i < kLedsPerBin; i++) {
      CAPTURE(i);
      CHECK(it[i] == Color(0, 110, 0));
    }
    CHECK(it[kLedsPerBin].is_black());  // the gap after it
    CHECK(it.lit() == kLedsPerBin);
  }

  TEST_CASE("the top row lands on the last LEDs") {
    clear_cells();
    set_cell(0, 0, Color(140, 0, 0));  // A1, past its window
    FakeLight it(kTallStrand);
    paint(it, 0);

    CHECK(it[kTallStrand - 1] == Color(140, 0, 0));
    CHECK(it[kTallStrand - kLedsPerBin] == Color(140, 0, 0));
    CHECK(it[kTallStrand - kLedsPerBin - 1].is_black());
    CHECK(it.lit() == kLedsPerBin);
  }

  TEST_CASE("the gap between two lit bins stays dark") {
    clear_cells();
    set_cell(12, 0, Color(0, 110, 0));  // M1
    set_cell(11, 0, Color(0, 110, 0));  // L1
    FakeLight it(kTallStrand);
    paint(it, 0);

    for (int i = kLedsPerBin; i < kBinPitch; i++) {
      CAPTURE(i);
      CHECK(it[i].is_black());
    }
    CHECK(it.lit() == 2 * kLedsPerBin);
  }

  TEST_CASE("a short column paints its five bins and nothing else") {
    clear_cells();
    for (int row = 8; row < 13; row++) set_cell(row, 4, Color(0, 45, 120));
    FakeLight it(kShortStrand);
    paint(it, 4);

    CHECK(it.lit() == 5 * kLedsPerBin);
    CHECK(it[0] == Color(0, 45, 120));
    CHECK(it[kShortStrand - 1] == Color(0, 45, 120));
  }

  TEST_CASE("a cell in the U's opening is never drawn") {
    // A7 is inside the 13 x 13 envelope and outside the rack. Home Assistant
    // sends the whole envelope, so this cell can carry a colour; column 7's
    // strand has nowhere to put it and must not guess.
    clear_cells();
    set_cell(0, 6, Color(150, 55, 0));  // A7
    FakeLight it(kShortStrand);
    paint(it, 6);
    CHECK(it.lit() == 0);
  }

  TEST_CASE("no column can write past the end of its strand") {
    // The bug this whole harness exists for. FakeLight indexes through
    // vector::at, so an overrun throws instead of quietly corrupting the
    // next strand's buffer.
    clear_cells();
    for (int row = 0; row < kRows; row++)
      for (int col = 0; col < kCols; col++) set_cell(row, col, Color(150, 55, 0));

    for (int column = 0; column < kCols; column++) {
      CAPTURE(column);
      FakeLight it(strand_leds(column));
      CHECK_NOTHROW(paint(it, column));
    }
  }

  TEST_CASE("a fully lit rack lights every LED of every bin and no others") {
    clear_cells();
    for (int row = 0; row < kRows; row++)
      for (int col = 0; col < kCols; col++) set_cell(row, col, Color(150, 55, 0));

    int lit = 0;
    for (int column = 0; column < kCols; column++) {
      FakeLight it(strand_leds(column));
      paint(it, column);
      lit += it.lit();
    }
    CHECK(lit == 129 * kLedsPerBin);  // 774 of the 1122 powered pixels
  }

  TEST_CASE("painting clears what was there before") {
    clear_cells();
    set_cell(12, 0, Color(0, 110, 0));
    FakeLight it(kTallStrand);
    paint(it, 0);
    CHECK(it.lit() == kLedsPerBin);

    clear_cells();
    paint(it, 0);
    CHECK(it.lit() == 0);
  }
}

// =============================================================================
// Rack 2, which shares every line of the maths and none of the shape
// =============================================================================

TEST_SUITE("the second rack") {
  TEST_CASE("every column is the full seven bins") {
    for (int column = 0; column < rack2::kCols; column++) {
      CAPTURE(column);
      CHECK(rack2::extent_of(column).first == 0);
      CHECK(rack2::extent_of(column).bins == 7);
    }
  }

  TEST_CASE("row G is the bottom, and so pixel zero") {
    CHECK(rack2::first_led(6, 0, 7) == 0);
    CHECK(rack2::first_led(0, 0, 7) == 54);
    CHECK(54 + rack1::kLedsPerBin == rack2::kStrand);
  }

  TEST_CASE("no column can write past the end of its strand") {
    for (uint8_t &channel : rack2::cell_rgb) channel = 200;
    for (int column = 0; column < rack2::kCols; column++) {
      CAPTURE(column);
      FakeLight it(rack2::kStrand);
      CHECK_NOTHROW(rack2::paint(it, column));
    }
  }

  TEST_CASE("both racks light the same number of LEDs per bin") {
    // Different files, same substitution names. A rack lit six-at-a-time next
    // to one lit three-at-a-time would read as two different states.
    FakeLight it(rack2::kStrand);
    for (uint8_t &channel : rack2::cell_rgb) channel = 0;
    rack2::cell_rgb[(6 * rack2::kCols + 0) * 3 + 1] = 110;  // G1
    rack2::paint(it, 0);
    CHECK(it.lit() == rack1::kLedsPerBin);
  }
}

// =============================================================================
// Bin ids
// =============================================================================

TEST_SUITE("bin ids") {
  using rack1::parse;

  TEST_CASE("a row letter and a column number") {
    int column = -1, row = -1;
    REQUIRE(parse("A1", &column, &row));
    CHECK(row == 0);
    CHECK(column == 0);

    REQUIRE(parse("M13", &column, &row));
    CHECK(row == 12);
    CHECK(column == 12);
  }

  TEST_CASE("separators, padding and case are all the same bin") {
    for (const char *written : {"D2", "d2", "D-2", "D 2", "D02", "  D2  ", "d_2"}) {
      CAPTURE(written);
      int column = -1, row = -1;
      REQUIRE(parse(written, &column, &row));
      CHECK(row == 3);
      CHECK(column == 1);
    }
  }

  TEST_CASE("what is not a bin id") {
    for (const char *written : {"", "A", "7", "AA", "A0", "-", "12A", "A1B"}) {
      CAPTURE(written);
      int column = -1, row = -1;
      CHECK_FALSE(parse(written, &column, &row));
    }
  }

  TEST_CASE("null arguments are refused rather than dereferenced") {
    int column = 0, row = 0;
    CHECK_FALSE(parse(nullptr, &column, &row));
    CHECK_FALSE(parse("A1", nullptr, &row));
    CHECK_FALSE(parse("A1", &column, nullptr));
  }

  TEST_CASE("parsing does not decide whether the rack has that bin") {
    // A7 is a well-formed bin id for a rack that does not have that bin. The
    // parser says where it would be; the column table says whether it exists.
    int column = -1, row = -1;
    REQUIRE(parse("A7", &column, &row));
    CHECK(row == 0);
    CHECK(column == 6);

    const rack1::Extent extent = rack1::extent_of(column);
    CHECK(rack1::first_led(row, extent.first, extent.bins) == -1);
  }
}
