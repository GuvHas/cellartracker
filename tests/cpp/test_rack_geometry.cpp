// Tests for the rack coordinate mapping.
//
// These were written before rack_geometry.h existed. The header's whole reason
// to exist is that the mapping from a bin - "which column, which row" - to a
// range of LED indices used to live in twenty copy-pasted ESPHome lambdas,
// where it could not be tested and could not disagree with itself loudly.
//
// The header deliberately includes nothing from ESPHome or Arduino, which is
// what lets this file compile on a laptop. If a future change makes it need
// esphome/core/*, that is the change to argue with, not this test.
//
// Topology under test: split data lines. Every bin column is its own strip on
// its own GPIO, so an LED index is only ever meaningful relative to a column.
// There is no global pixel numbering and no serpentine.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include "rack_geometry.h"

using rack::Column;
using rack::Geometry;
using rack::Span;

namespace {

// Rack 2: a plain 7 x 7, six LEDs lit in a pitch of nine.
constexpr Geometry kRack2{7, 7, 6, 9};

// Rack 1: the U. Columns 1-4 and 10-13 carry rows A-M; columns 5-9 exist only
// for rows I-M, so they start eight rows down and are five bins long.
constexpr Column kRack1Columns[] = {
    {0, 13}, {0, 13}, {0, 13}, {0, 13},
    {8, 5},  {8, 5},  {8, 5},  {8, 5}, {8, 5},
    {0, 13}, {0, 13}, {0, 13}, {0, 13},
};
constexpr Geometry kRack1{kRack1Columns, 13, 6, 9};

}  // namespace

// ---------------------------------------------------------------------------
// A uniform rack
// ---------------------------------------------------------------------------
TEST_SUITE("uniform geometry") {
  TEST_CASE("reports what it was built with") {
    CHECK(kRack2.valid());
    CHECK(kRack2.columns() == 7);
    CHECK(kRack2.leds_per_bin() == 6);
    CHECK(kRack2.bin_pitch() == 9);
    CHECK(kRack2.bins() == 49);
  }

  TEST_CASE("a strand is one pitch per bin, less the gap the last bin does not need") {
    CHECK(kRack2.strand_leds(0) == 60);   // 7 * 9 - 3
    CHECK(kRack2.strand_leds(6) == 60);
    CHECK(kRack2.total_leds() == 420);
  }

  TEST_CASE("the first bin of a column starts at pixel zero") {
    const Span s = kRack2.span(0, 0);
    CHECK(s.valid);
    CHECK(s.first == 0);
    CHECK(s.count == 6);
  }

  TEST_CASE("the last bin ends exactly at the end of the strand") {
    const Span s = kRack2.span(0, 6);
    CHECK(s.valid);
    CHECK(s.first == 54);
    CHECK(s.count == 6);
    CHECK(s.first + s.count == kRack2.strand_leds(0));
  }

  TEST_CASE("bins are spaced by the pitch, not by the lit count") {
    CHECK(kRack2.span(3, 1).first == 9);
    CHECK(kRack2.span(3, 2).first == 18);
    CHECK(kRack2.span(3, 3).first == 27);
  }

  TEST_CASE("every column of a uniform rack maps identically") {
    for (int c = 0; c < kRack2.columns(); c++) {
      CHECK(kRack2.span(c, 4).first == kRack2.span(0, 4).first);
      CHECK(kRack2.strand_leds(c) == kRack2.strand_leds(0));
    }
  }
}

// ---------------------------------------------------------------------------
// The U - columns of different heights, starting at different rows
// ---------------------------------------------------------------------------
TEST_SUITE("irregular geometry") {
  TEST_CASE("knows its own shape") {
    CHECK(kRack1.valid());
    CHECK(kRack1.columns() == 13);
    CHECK(kRack1.rows() == 13);      // the envelope, not the bin count
    CHECK(kRack1.bins() == 129);
    CHECK(kRack1.total_leds() == 1122);
  }

  TEST_CASE("tall and short columns get different strand lengths") {
    CHECK(kRack1.strand_leds(0) == 114);   // 13 bins
    CHECK(kRack1.strand_leds(3) == 114);
    CHECK(kRack1.strand_leds(4) == 42);    // 5 bins
    CHECK(kRack1.strand_leds(8) == 42);
    CHECK(kRack1.strand_leds(9) == 114);
  }

  TEST_CASE("a short column's first bin is pixel zero, not row A's offset") {
    // The single most important case in this file. Column 5 serves rows I-M,
    // so row I - envelope row 8 - is that strip's first pixel. Reading it as
    // row 8 of a 13-row column would index past the end of a 42-pixel strand.
    const Span s = kRack1.span(4, 8);
    CHECK(s.valid);
    CHECK(s.first == 0);
    CHECK(s.count == 6);
  }

  TEST_CASE("a short column's last bin still ends at the end of its strand") {
    const Span s = kRack1.span(4, 12);
    CHECK(s.valid);
    CHECK(s.first == 36);
    CHECK(s.first + s.count == kRack1.strand_leds(4));
  }

  TEST_CASE("rows above a short column do not exist on it") {
    for (int row = 0; row <= 7; row++) {
      CHECK_FALSE(kRack1.has_bin(4, row));
      CHECK_FALSE(kRack1.span(4, row).valid);
    }
  }

  TEST_CASE("the same rows do exist on the tall columns") {
    for (int row = 0; row <= 7; row++) {
      CHECK(kRack1.has_bin(0, row));
      CHECK(kRack1.has_bin(12, row));
    }
  }

  TEST_CASE("has_bin over the whole envelope is exactly the U") {
    int counted = 0;
    for (int col = 0; col < 13; col++) {
      for (int row = 0; row < 13; row++) {
        const bool expected = (row >= 8) || (col < 4) || (col >= 9);
        CHECK(kRack1.has_bin(col, row) == expected);
        if (expected) counted++;
      }
    }
    CHECK(counted == kRack1.bins());
  }

  TEST_CASE("no span ever runs past the end of its own strand") {
    for (int col = 0; col < kRack1.columns(); col++) {
      for (int row = 0; row < kRack1.rows(); row++) {
        const Span s = kRack1.span(col, row);
        if (!s.valid) continue;
        CHECK(s.first >= 0);
        CHECK(s.first + s.count <= kRack1.strand_leds(col));
      }
    }
  }

  TEST_CASE("two spans on one column never overlap") {
    for (int col = 0; col < kRack1.columns(); col++) {
      int previous_end = 0;
      for (int row = 0; row < kRack1.rows(); row++) {
        const Span s = kRack1.span(col, row);
        if (!s.valid) continue;
        CHECK(s.first >= previous_end);
        previous_end = s.first + s.count;
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Out of bounds
// ---------------------------------------------------------------------------
TEST_SUITE("bounds") {
  TEST_CASE("a column outside the rack is not a column") {
    CHECK_FALSE(kRack2.span(-1, 0).valid);
    CHECK_FALSE(kRack2.span(7, 0).valid);
    CHECK_FALSE(kRack2.span(9999, 0).valid);
    CHECK_FALSE(kRack2.has_bin(-1, 0));
    CHECK_FALSE(kRack2.has_bin(7, 0));
  }

  TEST_CASE("a row outside the column is not a bin") {
    CHECK_FALSE(kRack2.span(0, -1).valid);
    CHECK_FALSE(kRack2.span(0, 7).valid);
    CHECK_FALSE(kRack2.span(0, 9999).valid);
  }

  TEST_CASE("an invalid span reports zero length, so a caller that ignores the flag draws nothing") {
    const Span s = kRack2.span(0, 99);
    CHECK(s.count == 0);
    CHECK(s.first == 0);
  }

  TEST_CASE("strand_leds of a column that does not exist is zero") {
    CHECK(kRack2.strand_leds(-1) == 0);
    CHECK(kRack2.strand_leds(7) == 0);
  }
}

// ---------------------------------------------------------------------------
// Geometries that cannot be built
// ---------------------------------------------------------------------------
TEST_SUITE("degenerate geometry") {
  TEST_CASE("lit LEDs may fill the whole pitch") {
    constexpr Geometry solid{4, 4, 9, 9};
    CHECK(solid.valid());
    CHECK(solid.strand_leds(0) == 36);
    CHECK(solid.span(0, 1).first == 9);
  }

  TEST_CASE("but may not exceed it - bins would overlap") {
    constexpr Geometry bad{4, 4, 10, 9};
    CHECK_FALSE(bad.valid());
  }

  TEST_CASE("zero and negative dimensions are refused") {
    CHECK_FALSE(Geometry{0, 7, 6, 9}.valid());
    CHECK_FALSE(Geometry{7, 0, 6, 9}.valid());
    CHECK_FALSE(Geometry{7, 7, 0, 9}.valid());
    CHECK_FALSE(Geometry{7, 7, 6, 0}.valid());
    CHECK_FALSE(Geometry{-1, 7, 6, 9}.valid());
  }

  TEST_CASE("an invalid geometry answers nothing rather than answering wrongly") {
    constexpr Geometry bad{4, 4, 10, 9};
    CHECK_FALSE(bad.span(0, 0).valid);
    CHECK(bad.strand_leds(0) == 0);
    CHECK(bad.total_leds() == 0);
    CHECK_FALSE(bad.has_bin(0, 0));
  }

  TEST_CASE("a column table with a negative first row or bin count is refused") {
    static constexpr Column bad_first[] = {{-1, 5}};
    static constexpr Column bad_bins[] = {{0, 0}};
    CHECK_FALSE(Geometry(bad_first, 1, 6, 9).valid());
    CHECK_FALSE(Geometry(bad_bins, 1, 6, 9).valid());
  }
}

// ---------------------------------------------------------------------------
// One-indexed input, which is what humans and CellarTracker use
// ---------------------------------------------------------------------------
TEST_SUITE("indexing") {
  TEST_CASE("the one-indexed helper agrees with the zero-indexed core") {
    for (int col = 0; col < kRack1.columns(); col++) {
      for (int row = 0; row < kRack1.rows(); row++) {
        const Span zero = kRack1.span(col, row);
        const Span one = kRack1.span_1(col + 1, row + 1);
        CHECK(one.valid == zero.valid);
        CHECK(one.first == zero.first);
        CHECK(one.count == zero.count);
      }
    }
  }

  TEST_CASE("one-indexed zero is out of bounds, not the first bin") {
    CHECK_FALSE(kRack2.span_1(0, 1).valid);
    CHECK_FALSE(kRack2.span_1(1, 0).valid);
    CHECK(kRack2.span_1(1, 1).first == 0);
  }
}

// ---------------------------------------------------------------------------
// Parsing a bin id, which arrives from Home Assistant as text
// ---------------------------------------------------------------------------
TEST_SUITE("bin ids") {
  TEST_CASE("a row letter and a column number") {
    int col = -1, row = -1;
    REQUIRE(rack::parse_bin_id("A1", &col, &row));
    CHECK(row == 0);
    CHECK(col == 0);

    REQUIRE(rack::parse_bin_id("M13", &col, &row));
    CHECK(row == 12);
    CHECK(col == 12);
  }

  TEST_CASE("separators, padding and case are all the same bin") {
    for (const char *written : {"D2", "d2", "D-2", "D 2", "D02", "  D2  ", "d_2"}) {
      int col = -1, row = -1;
      REQUIRE_MESSAGE(rack::parse_bin_id(written, &col, &row), written);
      CHECK_MESSAGE(row == 3, written);
      CHECK_MESSAGE(col == 1, written);
    }
  }

  TEST_CASE("what is not a bin id") {
    int col = 0, row = 0;
    for (const char *bad : {"", "A", "7", "AA", "A0", "-", "12A", "A1B"}) {
      CHECK_FALSE_MESSAGE(rack::parse_bin_id(bad, &col, &row), bad);
    }
  }

  TEST_CASE("null arguments are refused rather than dereferenced") {
    int col = 0, row = 0;
    CHECK_FALSE(rack::parse_bin_id(nullptr, &col, &row));
    CHECK_FALSE(rack::parse_bin_id("A1", nullptr, &row));
    CHECK_FALSE(rack::parse_bin_id("A1", &col, nullptr));
  }

  TEST_CASE("parsing does not decide whether the rack has that bin") {
    // "A7" is inside the 13 x 13 envelope and parses fine; it is the geometry
    // that knows the U has no bin there.
    int col = -1, row = -1;
    REQUIRE(rack::parse_bin_id("A7", &col, &row));
    CHECK(row == 0);
    CHECK(col == 6);
    CHECK_FALSE(kRack1.has_bin(col, row));
  }
}

// ---------------------------------------------------------------------------
// The two racks this repository actually ships
// ---------------------------------------------------------------------------
TEST_SUITE("the shipped racks") {
  TEST_CASE("rack 1 is the U described in winerack1led.yaml") {
    CHECK(kRack1.bins() == 129);
    CHECK(kRack1.total_leds() == 1122);
    CHECK(kRack1.strand_leds(0) == 114);
    CHECK(kRack1.strand_leds(4) == 42);
  }

  TEST_CASE("rack 2 is the 7 by 7 described in winerack2led.yaml") {
    CHECK(kRack2.bins() == 49);
    CHECK(kRack2.total_leds() == 420);
    CHECK(kRack2.strand_leds(0) == 60);
  }

  TEST_CASE("both racks light the same number of LEDs per bin") {
    CHECK(kRack1.leds_per_bin() == kRack2.leds_per_bin());
  }
}

// ---------------------------------------------------------------------------
// Iterating a column, which is what the ESPHome effect lambda does
// ---------------------------------------------------------------------------
TEST_SUITE("iteration") {
  TEST_CASE("visits every bin of a column, in strand order") {
    int visits = 0;
    int previous_first = -1;
    rack::for_each_bin(kRack2, 2, [&](int row, Span s) {
      CHECK(row == visits);
      CHECK(s.valid);
      CHECK(s.first > previous_first);
      previous_first = s.first;
      visits++;
    });
    CHECK(visits == 7);
  }

  TEST_CASE("on a short column it visits five bins, starting at row I") {
    int visits = 0;
    int first_row = -1;
    rack::for_each_bin(kRack1, 6, [&](int row, Span s) {
      if (visits == 0) {
        first_row = row;
        CHECK(s.first == 0);
      }
      visits++;
    });
    CHECK(visits == 5);
    CHECK(first_row == 8);
  }

  TEST_CASE("a column outside the rack yields nothing") {
    int visits = 0;
    rack::for_each_bin(kRack1, 99, [&](int, Span) { visits++; });
    CHECK(visits == 0);
  }

  TEST_CASE("every column iterated together covers every bin exactly once") {
    int total = 0;
    for (int col = 0; col < kRack1.columns(); col++) {
      rack::for_each_bin(kRack1, col, [&](int, Span) { total++; });
    }
    CHECK(total == kRack1.bins());
  }
}
