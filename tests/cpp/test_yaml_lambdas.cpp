// The maths in the ESPHome YAML, compiled and run on a workstation.
// =============================================================================
//
// Every #include of a .inc below is a block of C++ lifted verbatim out of the
// `substitutions:` of examples/esphome/winerack*led.yaml by yaml_lambda.py.
// Nothing in this file retypes the firmware's arithmetic - the wrappers set up
// the same names an addressable_lambda has in scope (`kRow`, `it`, `cell_rgb`)
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

// These mirror the substitutions of the same name. They are duplicated here
// rather than generated because a test that derives its expectations from the
// thing under test proves nothing; the Python suite checks they agree.
constexpr int kRows = 13;
constexpr int kCols = 13;
constexpr int kBinWidthMm = 95;
constexpr int kStripDensity = 60;  // LEDs per metre
constexpr int kFullStrand = 74;    // 13 bins, rows I-M
constexpr int kPiece = 23;         // 4 bins, one arm of the U
constexpr int kSplitStrand = 46;   // two pieces jumpered across the U, rows A-H

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
int first_led(int at_col, int from_a, int count_a, int from_b, int count_b,
              int *out_leds = nullptr) {
#include "rack1a/bin_first_led.inc"
  return bin_first_led(at_col, from_a, count_a, from_b, count_b, out_leds);
}

struct Extent {
  int first_a;
  int bins_a;
  int first_b;
  int bins_b;
};

/// The shipped `row_extent`, for one row.
Extent extent_of(int kRow) {
#include "rack1a/row_extent.inc"
  return Extent{kFirstA, kBinsA, kFirstB, kBinsB};
}

/// Where bin (row, col) starts on its row's strand, through the shipped table.
int led_of(int row, int col) {
  const Extent e = extent_of(row);
  return first_led(col, e.first_a, e.bins_a, e.first_b, e.bins_b);
}

/// How many LEDs bin (row, col) owns, or 0 if the rack has no such bin.
int leds_of(int row, int col) {
  const Extent e = extent_of(row);
  int leds = 0;
  if (first_led(col, e.first_a, e.bins_a, e.first_b, e.bins_b, &leds) < 0) return 0;
  return leds;
}

/// A whole strand painted by the shipped `paint_row` - the three lines of a
/// light's lambda, in the order the light has them.
void paint(FakeLight &it, int kRow) {
#include "rack1a/row_extent.inc"
#include "rack1a/bin_first_led.inc"
#include "rack1a/paint_row.inc"
}

/// The strand length a row's light declares as `num_leds`.
int strand_leds(int row) {
  return extent_of(row).bins_b > 0 ? kSplitStrand : kFullStrand;
}

bool parse(const char *written, int *out_column, int *out_row) {
#include "rack1a/parse_bin_id.inc"
  return parse_bin_id(written, out_column, out_row);
}

}  // namespace rack1

// -----------------------------------------------------------------------------
// Rack 1's other half - rows H-M, on the second board
// -----------------------------------------------------------------------------
// The same rack in a second file. Everything above reads rack 1A; this exists
// so that 1B's copy of the maths is compiled and run too, not just compared as
// text by the Python suite.
namespace rack1b {

int first_led(int at_col, int from_a, int count_a, int from_b, int count_b,
              int *out_leds = nullptr) {
#include "rack1b/bin_first_led.inc"
  return bin_first_led(at_col, from_a, count_a, from_b, count_b, out_leds);
}

rack1::Extent extent_of(int kRow) {
#include "rack1b/row_extent.inc"
  return rack1::Extent{kFirstA, kBinsA, kFirstB, kBinsB};
}

int led_of(int row, int col) {
  const rack1::Extent e = extent_of(row);
  return first_led(col, e.first_a, e.bins_a, e.first_b, e.bins_b);
}

int leds_of(int row, int col) {
  const rack1::Extent e = extent_of(row);
  int leds = 0;
  if (first_led(col, e.first_a, e.bins_a, e.first_b, e.bins_b, &leds) < 0) return 0;
  return leds;
}

/// 1B paints from the same envelope-wide cell_rgb a lambda on 1A would see.
using rack1::cell_rgb;

void paint(FakeLight &it, int kRow) {
#include "rack1b/row_extent.inc"
#include "rack1b/bin_first_led.inc"
#include "rack1b/paint_row.inc"
}

}  // namespace rack1b

// -----------------------------------------------------------------------------
// Rack 2 - a plain 7 x 7
// -----------------------------------------------------------------------------
namespace rack2 {

constexpr int kRows = 7;
constexpr int kCols = 7;
constexpr int kStrand = 40;  // 7 bins of 95 mm at 60 LEDs/m

uint8_t cell_rgb[kRows * kCols * 3];

int first_led(int at_col, int from_a, int count_a, int from_b, int count_b,
              int *out_leds = nullptr) {
#include "rack2/bin_first_led.inc"
  return bin_first_led(at_col, from_a, count_a, from_b, count_b, out_leds);
}

struct Extent {
  int first_a;
  int bins_a;
  int first_b;
  int bins_b;
};

Extent extent_of(int kRow) {
#include "rack2/row_extent.inc"
  return Extent{kFirstA, kBinsA, kFirstB, kBinsB};
}

int led_of(int row, int col) {
  const Extent e = extent_of(row);
  return first_led(col, e.first_a, e.bins_a, e.first_b, e.bins_b);
}

/// How many LEDs bin (row, col) owns, or 0 if the rack has no such bin.
int leds_of(int row, int col) {
  const Extent e = extent_of(row);
  int leds = 0;
  if (first_led(col, e.first_a, e.bins_a, e.first_b, e.bins_b, &leds) < 0) return 0;
  return leds;
}

void paint(FakeLight &it, int kRow) {
#include "rack2/row_extent.inc"
#include "rack2/bin_first_led.inc"
#include "rack2/paint_row.inc"
}

}  // namespace rack2

// =============================================================================
// The direction the data line runs
// =============================================================================
//
// The strips run horizontally along the back of the rack, one per bin row, and
// DIN enters at the bin-1 end of every row of rack 1 so that all the feeds come
// up one riser at the side. Bin 1 is pixel 0 and the bin numbers count up along
// the strand from there. Rack 2 is fed from the bin-7 end; see its own suite.

TEST_SUITE("left-to-right indexing") {
  using namespace rack1;

  TEST_CASE("bin 1 of a full row is the first LED on the strand") {
    CHECK(led_of(12, 0) == 0);  // M1
  }

  TEST_CASE("bin 13 of a full row is the last LEDs on the strand") {
    CHECK(led_of(12, 12) == 68);  // M13
    CHECK(68 + leds_of(12, 12) == kFullStrand);
  }

  TEST_CASE("bin numbers count up along the strand") {
    CHECK(led_of(8, 0) == 0);    // I1
    CHECK(led_of(8, 1) == 6);    // I2
    CHECK(led_of(8, 2) == 11);   // I3
    CHECK(led_of(8, 6) == 34);   // I7, the middle of the base
    CHECK(led_of(8, 12) == 68);  // I13
  }

  TEST_CASE("the pixel index rises with the column") {
    for (int col = 1; col < kCols; col++) {
      CAPTURE(col);
      CHECK(led_of(12, col) > led_of(12, col - 1));
    }
  }

  TEST_CASE("every row starts at bin 1, so every feed is at the same side") {
    for (int row = 0; row < kRows; row++) {
      CAPTURE(row);
      CHECK(led_of(row, 0) == 0);
    }
  }
}

// =============================================================================
// 95 mm bins on a 60/m strip
// =============================================================================
//
// A bin is 5.7 LEDs. Giving every bin six would put bin 13 four LEDs - 65 mm -
// past its own wall. The shipped maths places each bin by position instead, so
// these check the thing that matters physically: where the LEDs are.

TEST_SUITE("bins placed by position") {
  using namespace rack1;

  TEST_CASE("every bin owns five or six LEDs") {
    for (int col = 0; col < kCols; col++) {
      CAPTURE(col);
      CHECK(leds_of(12, col) >= 5);
      CHECK(leds_of(12, col) <= 6);
    }
  }

  TEST_CASE("a bin's first LED is within one LED of its wall, all the way along") {
    // In units of 1/2000 m so everything stays an integer: the first LED's
    // centre is (2 * led + 1) * 1000 / density, the wall is 2 * col * width.
    for (int col = 0; col < kCols; col++) {
      CAPTURE(col);
      const int centre = (2 * led_of(12, col) + 1) * 1000;
      const int wall = 2 * col * kBinWidthMm * kStripDensity;
      CHECK(centre - wall >= 0);
      CHECK(centre - wall < 2000);
    }
  }

  TEST_CASE("a full row is the 74 LEDs inside 13 bins") {
    // 13 * 95 mm = 1235 mm, and 74 LEDs at 60/m is 1233 mm.
    int total = 0;
    for (int col = 0; col < kCols; col++) total += leds_of(12, col);
    CHECK(total == kFullStrand);
  }

  TEST_CASE("every LED on every strand belongs to exactly one bin") {
    for (int row = 0; row < kRows; row++) {
      CAPTURE(row);
      std::set<int> owned;
      for (int col = 0; col < kCols; col++) {
        const int first = led_of(row, col);
        for (int i = 0; i < leds_of(row, col); i++) CHECK(owned.insert(first + i).second);
      }
      CHECK(static_cast<int>(owned.size()) == strand_leds(row));
      CHECK(*owned.begin() == 0);
      CHECK(*owned.rbegin() == strand_leds(row) - 1);
    }
  }
}

// =============================================================================
// The jumper across the U
// =============================================================================
//
// Rows A-H are two four-bin pieces of strip, bins 1-4 and 10-13, chained by a
// jumper that carries power and data across the opening but has no pixels. So
// bin 10 is the pixel straight after bin 4's last LED - not five bins further
// on, which is where it would be if the strip ran unbroken behind the hole -
// and piece B is cut at bin 10's wall, so it is placed from there afresh.

TEST_SUITE("split rows") {
  using namespace rack1;

  TEST_CASE("the first piece is bins 1 to 4, from pixel 0") {
    CHECK(led_of(0, 0) == 0);   // A1
    CHECK(led_of(0, 3) == 17);  // A4
    CHECK(17 + leds_of(0, 3) == kPiece);
  }

  TEST_CASE("the second piece starts on the pixel after the first piece ends") {
    CHECK(led_of(0, 9) == kPiece);  // A10, straight across the jumper
    CHECK(led_of(0, 9) == 23);
  }

  TEST_CASE("the second piece is bins 10 to 13, spaced like the first") {
    CHECK(led_of(0, 9) == 23);   // A10
    CHECK(led_of(0, 10) == 29);  // A11
    CHECK(led_of(0, 11) == 34);  // A12
    CHECK(led_of(0, 12) == 40);  // A13
    CHECK(40 + leds_of(0, 12) == kSplitStrand);
    for (int i = 0; i < 4; i++) {
      CAPTURE(i);
      CHECK(led_of(0, 9 + i) - led_of(0, 9) == led_of(0, i));
    }
  }

  TEST_CASE("the jumper skips no pixels") {
    // Bin 10 starts on the pixel straight after bin 4's last one. If the
    // formula placed it by its distance along the rack instead, it would land
    // five bins' worth of LEDs late and run off the end of the strand.
    CHECK(led_of(0, 9) - led_of(0, 3) == leds_of(0, 3));
  }

  TEST_CASE("bins in the opening are on neither piece") {
    for (int row = 0; row < 8; row++) {
      for (int col = 4; col < 9; col++) {
        CAPTURE(row);
        CAPTURE(col);
        CHECK(led_of(row, col) == -1);
      }
    }
  }

  TEST_CASE("the same bin column is at different pixels on a split and a full row") {
    // Bin 10 is shelf-for-shelf the same column, but on row I there are five
    // more bins of strip in front of it.
    CHECK(led_of(0, 9) == 23);
    CHECK(led_of(8, 9) == 51);
  }
}

TEST_SUITE("bounds") {
  using namespace rack1;

  TEST_CASE("a column past the end of the rack is not on any row") {
    CHECK(led_of(12, 13) == -1);
    CHECK(led_of(0, 13) == -1);
    CHECK(led_of(12, 99) == -1);
  }

  TEST_CASE("a negative column is refused rather than indexed backwards") {
    CHECK(led_of(12, -1) == -1);
    CHECK(led_of(0, -1) == -1);
    CHECK(led_of(0, -100) == -1);
  }

  TEST_CASE("a row with no bins has no LEDs") {
    CHECK(first_led(0, 0, 0, 0, 0) == -1);
    CHECK(first_led(0, 0, -3, 0, 0) == -1);
  }

  TEST_CASE("a lone second piece starts at pixel 0") {
    // Not a row this rack has, but the formula should not invent a first piece.
    CHECK(first_led(9, 0, 0, 9, 4) == 0);
  }

  TEST_CASE("no bin ever runs past the end of its own strand") {
    for (int row = 0; row < kRows; row++) {
      const int leds = strand_leds(row);
      for (int col = 0; col < kCols; col++) {
        CAPTURE(row);
        CAPTURE(col);
        const int first = led_of(row, col);
        if (first < 0) continue;
        CHECK(first + leds_of(row, col) <= leds);
      }
    }
  }

  TEST_CASE("two bins on one row never light the same LED") {
    for (int row = 0; row < kRows; row++) {
      std::set<int> lit;
      int expected = 0;
      for (int col = 0; col < kCols; col++) {
        const int first = led_of(row, col);
        if (first < 0) continue;
        expected += leds_of(row, col);
        for (int i = 0; i < leds_of(row, col); i++) {
          CAPTURE(row);
          CAPTURE(col);
          CHECK(lit.insert(first + i).second);
        }
      }
      CHECK(static_cast<int>(lit.size()) == expected);
    }
  }
}

// =============================================================================
// The row table
// =============================================================================

TEST_SUITE("row extents") {
  using namespace rack1;

  TEST_CASE("the arms of the U are two pieces of four") {
    for (int row = 0; row < 8; row++) {
      CAPTURE(row);
      const Extent e = extent_of(row);
      CHECK(e.first_a == 0);
      CHECK(e.bins_a == 4);
      CHECK(e.first_b == 9);
      CHECK(e.bins_b == 4);
    }
  }

  TEST_CASE("the base of the U is one piece of thirteen") {
    for (int row = 8; row < 13; row++) {
      CAPTURE(row);
      const Extent e = extent_of(row);
      CHECK(e.first_a == 0);
      CHECK(e.bins_a == 13);
      CHECK(e.bins_b == 0);
    }
  }

  TEST_CASE("a row outside the rack carries nothing") {
    // kRow is a literal in each light, so this cannot happen from a strand -
    // but light_bin passes a row that came off the network.
    for (int row : {-1, 13, 9999}) {
      CAPTURE(row);
      CHECK(extent_of(row).bins_a == 0);
      CHECK(extent_of(row).bins_b == 0);
    }
  }

  TEST_CASE("the rack has 129 bins in a 13 by 13 envelope") {
    int bins = 0;
    for (int row = 0; row < kRows; row++) bins += extent_of(row).bins_a + extent_of(row).bins_b;
    CHECK(bins == 129);
    CHECK(kRows * kCols == 169);
  }

  TEST_CASE("the strands add up to 738 pixels") {
    int total = 0;
    for (int row = 0; row < kRows; row++) total += strand_leds(row);
    CHECK(total == 738);
  }
}

// =============================================================================
// The painter, as shipped
// =============================================================================

TEST_SUITE("painting a strand") {
  using namespace rack1;

  TEST_CASE("bin 1 lands on the first LEDs") {
    clear_cells();
    set_cell(12, 0, Color(0, 110, 0));  // M1, ready
    FakeLight it(kFullStrand);
    paint(it, 12);

    for (int i = 0; i < 6; i++) {
      CAPTURE(i);
      CHECK(it[i] == Color(0, 110, 0));
    }
    CHECK(it[6].is_black());  // bin 2's first LED
    CHECK(it.lit() == 6);
  }

  TEST_CASE("bin 13 lands on the last LEDs") {
    clear_cells();
    set_cell(12, 12, Color(140, 0, 0));  // M13, past its window
    FakeLight it(kFullStrand);
    paint(it, 12);

    CHECK(it[kFullStrand - 1] == Color(140, 0, 0));
    CHECK(it[68] == Color(140, 0, 0));
    CHECK(it[67].is_black());
    CHECK(it.lit() == 6);
  }

  TEST_CASE("neighbouring bins meet at their wall, with no LED shared") {
    // The bin wall between them is the divider; there is no dark gap to keep.
    clear_cells();
    set_cell(12, 0, Color(0, 110, 0));   // M1
    set_cell(12, 1, Color(140, 0, 0));   // M2
    FakeLight it(kFullStrand);
    paint(it, 12);

    CHECK(it[5] == Color(0, 110, 0));
    CHECK(it[6] == Color(140, 0, 0));
    CHECK(it[10] == Color(140, 0, 0));
    CHECK(it[11].is_black());
    CHECK(it.lit() == 6 + 5);
  }

  TEST_CASE("a split row lights bin 4 and bin 10 back to back") {
    // Either side of the jumper. On the strip they are adjacent LEDs; on the
    // rack they are six bins apart.
    clear_cells();
    set_cell(0, 3, Color(0, 110, 0));    // A4
    set_cell(0, 9, Color(0, 45, 120));   // A10
    FakeLight it(kSplitStrand);
    paint(it, 0);

    CHECK(it[kPiece - 1] == Color(0, 110, 0));
    CHECK(it[kPiece] == Color(0, 45, 120));
    CHECK(it.lit() == leds_of(0, 3) + leds_of(0, 9));
  }

  TEST_CASE("a split row paints its eight bins and nothing else") {
    clear_cells();
    for (int col = 0; col < kCols; col++) set_cell(2, col, Color(0, 45, 120));
    FakeLight it(kSplitStrand);
    paint(it, 2);

    CHECK(it.lit() == kSplitStrand);  // every pixel on it belongs to a bin
    CHECK(it[0] == Color(0, 45, 120));
    CHECK(it[kSplitStrand - 1] == Color(0, 45, 120));
  }

  TEST_CASE("a cell in the U's opening is never drawn") {
    // A7 is inside the 13 x 13 envelope and outside the rack. Home Assistant
    // sends the whole envelope, so this cell can carry a colour; row A's
    // strand has no pixels behind the opening and must not guess.
    clear_cells();
    set_cell(0, 6, Color(150, 55, 0));  // A7
    FakeLight it(kSplitStrand);
    paint(it, 0);
    CHECK(it.lit() == 0);
  }

  TEST_CASE("no row can write past the end of its strand") {
    // The bug this whole harness exists for. FakeLight indexes through
    // vector::at, so an overrun throws instead of quietly corrupting the
    // next strand's buffer.
    clear_cells();
    for (int row = 0; row < kRows; row++)
      for (int col = 0; col < kCols; col++) set_cell(row, col, Color(150, 55, 0));

    for (int row = 0; row < kRows; row++) {
      CAPTURE(row);
      FakeLight it(strand_leds(row));
      CHECK_NOTHROW(paint(it, row));
    }
  }

  TEST_CASE("a fully lit rack lights every LED of every bin and no others") {
    clear_cells();
    for (int row = 0; row < kRows; row++)
      for (int col = 0; col < kCols; col++) set_cell(row, col, Color(150, 55, 0));

    int lit = 0;
    for (int row = 0; row < kRows; row++) {
      FakeLight it(strand_leds(row));
      paint(it, row);
      lit += it.lit();
    }
    CHECK(lit == 738);  // every powered pixel: there are no gaps any more
  }

  TEST_CASE("painting clears what was there before") {
    clear_cells();
    set_cell(12, 0, Color(0, 110, 0));
    FakeLight it(kFullStrand);
    paint(it, 12);
    CHECK(it.lit() == 6);

    clear_cells();
    paint(it, 12);
    CHECK(it.lit() == 0);
  }
}

// =============================================================================
// Rack 1's two boards
// =============================================================================

TEST_SUITE("the two halves of rack 1") {
  TEST_CASE("both halves place every bin of the rack on the same LEDs") {
    for (int row = 0; row < rack1::kRows; row++) {
      for (int col = 0; col < rack1::kCols; col++) {
        CAPTURE(row);
        CAPTURE(col);
        CHECK(rack1b::led_of(row, col) == rack1::led_of(row, col));
        CHECK(rack1b::leds_of(row, col) == rack1::leds_of(row, col));
      }
    }
  }

  TEST_CASE("rows H to M paint on the second board as they would on the first") {
    using namespace rack1;
    clear_cells();
    for (int row = 0; row < kRows; row++)
      for (int col = 0; col < kCols; col++) set_cell(row, col, Color(150, 55, 0));

    for (int row = 7; row < kRows; row++) {
      CAPTURE(row);
      FakeLight on_a(strand_leds(row));
      FakeLight on_b(strand_leds(row));
      paint(on_a, row);
      CHECK_NOTHROW(rack1b::paint(on_b, row));
      CHECK(on_b.lit() == on_a.lit());
      CHECK(on_b.lit() == strand_leds(row));
    }
  }
}

// =============================================================================
// Rack 2, which shares every line of the maths and none of the shape
// =============================================================================

TEST_SUITE("the second rack") {
  TEST_CASE("every row is one piece of seven bins") {
    for (int row = 0; row < rack2::kRows; row++) {
      CAPTURE(row);
      CHECK(rack2::extent_of(row).first_a == 0);
      CHECK(rack2::extent_of(row).bins_a == 7);
      CHECK(rack2::extent_of(row).bins_b == 0);
    }
  }

  TEST_CASE("it is fed from the bin-7 end, so bin 7 is pixel zero and bin 1 the far end") {
    for (int row = 0; row < rack2::kRows; row++) {
      CAPTURE(row);
      CHECK(rack2::led_of(row, 6) == 0);
      CHECK(rack2::led_of(row, 0) == 34);
      CHECK(34 + rack2::leds_of(row, 0) == rack2::kStrand);
    }
  }

  TEST_CASE("the pixel index falls as the bin number rises") {
    for (int col = 1; col < rack2::kCols; col++) {
      CAPTURE(col);
      CHECK(rack2::led_of(0, col) < rack2::led_of(0, col - 1));
    }
  }

  TEST_CASE("every LED on a strand belongs to exactly one bin") {
    for (int row = 0; row < rack2::kRows; row++) {
      int owner[rack2::kStrand];
      for (int &o : owner) o = -1;
      for (int col = 0; col < rack2::kCols; col++) {
        int leds = 0;
        const int base = rack2::first_led(col, 0, 7, 0, 0, &leds);
        for (int i = 0; i < leds; i++) {
          CAPTURE(row);
          CAPTURE(col);
          REQUIRE(base + i < rack2::kStrand);
          CHECK(owner[base + i] == -1);
          owner[base + i] = col;
        }
      }
      for (int o : owner) CHECK(o != -1);
    }
  }

  TEST_CASE("a column off either side of the rack is not on any row") {
    CHECK(rack2::led_of(0, 7) == -1);
    CHECK(rack2::led_of(0, -1) == -1);
  }

  TEST_CASE("no row can write past the end of its strand") {
    for (uint8_t &channel : rack2::cell_rgb) channel = 200;
    for (int row = 0; row < rack2::kRows; row++) {
      CAPTURE(row);
      FakeLight it(rack2::kStrand);
      CHECK_NOTHROW(rack2::paint(it, row));
    }
  }

  TEST_CASE("both racks place the same bins on the same LEDs") {
    // Different files, same bins and same strip. A bin lit six LEDs wide on
    // one rack and five on the other, in the same position, would mean the
    // two had drifted apart. Rack 2 is fed from the other end, so its bin
    // `col` sits where rack 1 has the bin the same distance from its feed.
    for (int col = 0; col < rack2::kCols; col++) {
      CAPTURE(col);
      CHECK(rack2::led_of(0, col) == rack1::led_of(12, 6 - col));
      CHECK(rack2::leds_of(0, col) == rack1::leds_of(12, 6 - col));
    }
    FakeLight it(rack2::kStrand);
    for (uint8_t &channel : rack2::cell_rgb) channel = 0;
    rack2::cell_rgb[(6 * rack2::kCols + 0) * 3 + 1] = 110;  // G1
    rack2::paint(it, 6);
    CHECK(it.lit() == rack1::leds_of(12, 6));
    CHECK(it.lit() == rack2::leds_of(6, 0));
    // G1 is the far end of row G from the feed: its LEDs are the strand's last.
    CHECK_FALSE(it[rack2::kStrand - 1].is_black());
    CHECK(it[0].is_black());
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
    // parser says where it would be; the row table says whether it exists.
    int column = -1, row = -1;
    REQUIRE(parse("A7", &column, &row));
    CHECK(row == 0);
    CHECK(column == 6);

    CHECK(rack1::led_of(row, column) == -1);
  }
}
