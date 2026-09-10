// rack_geometry.h - where a bin is, in LEDs.
// =============================================================================
//
// Split data lines: every bin column is its own strip on its own GPIO. There is
// no global pixel numbering and no serpentine, so an LED index only means
// anything relative to the column it belongs to. Everything here is phrased
// that way.
//
// A rack is described by four numbers and, when it is not a rectangle, a table:
//
//   columns        how many strips, and so how many light entities and GPIOs
//   bins_per_column  how many bins one strip serves
//   leds_per_bin   how many LEDs light up in front of one bottle
//   bin_pitch      how many LEDs from the start of one bin to the start of the
//                  next - the difference is the dark gap between bins
//
// A strand is therefore `bins * pitch - (pitch - leds_per_bin)`: the last bin
// has no gap after it. That single subtraction is the off-by-one this file
// exists to get right once instead of twenty times.
//
// -----------------------------------------------------------------------------
// Why this header has no ESPHome in it
// -----------------------------------------------------------------------------
//
// Nothing here includes esphome/, Arduino.h or anything else from the firmware.
// That is deliberate and it is the whole reason tests/cpp can compile and run
// this on a laptop in under a second. `for_each_bin` is a template over its
// callback precisely so that the caller can hand it a lambda that knows about
// `Color` and `AddressableLight` without this file ever naming those types.
//
// If a change here starts wanting an ESPHome header, that is the change to
// argue with rather than the test suite.
//
// -----------------------------------------------------------------------------
// Why it is constexpr
// -----------------------------------------------------------------------------
//
// A `constexpr Geometry` is folded into flash as .rodata. It costs zero bytes
// of RAM, needs no setup order, and is readable before WiFi comes up - which
// matters on a board whose 320 KB of RAM is mostly spoken for by the LED frame
// buffers. See the note on parameterisation at the bottom of the ESPHome
// configs for why this is not a set of Home Assistant number entities.
//
// =============================================================================

#pragma once

namespace rack {

/// A run of LEDs on one column's strip.
///
/// `valid` is false when the requested bin does not exist on that column - a
/// row above a short column of a U-shaped rack, or simply out of range. An
/// invalid span also reports `count == 0`, so a caller that forgets to check
/// the flag draws nothing rather than drawing somewhere wrong.
struct Span {
  int first{0};
  int count{0};
  bool valid{false};
};

/// One column's extent, for racks that are not rectangles.
///
/// `first_bin` is the envelope row this column's *first pixel* sits at. On the
/// U-shaped rack, columns 5-9 exist only for rows I-M, so their `first_bin` is
/// 8 and their strips are five bins long. Getting this wrong is the bug that
/// indexes past the end of a short strand.
struct Column {
  int first_bin{0};
  int bins{0};
};

class Geometry {
 public:
  /// A rectangular rack: every column serves the same bins, from row 0.
  constexpr Geometry(int columns, int bins_per_column, int leds_per_bin, int bin_pitch)
      : table_(nullptr),
        columns_(columns),
        uniform_bins_(bins_per_column),
        leds_per_bin_(leds_per_bin),
        bin_pitch_(bin_pitch) {}

  /// A rack whose columns differ - the U, or anything else with a hole in it.
  /// `table` must have static storage duration and at least `columns` entries.
  constexpr Geometry(const Column *table, int columns, int leds_per_bin, int bin_pitch)
      : table_(table),
        columns_(columns),
        uniform_bins_(0),
        leds_per_bin_(leds_per_bin),
        bin_pitch_(bin_pitch) {}

  /// False for a rack that could not exist. Every other accessor answers
  /// nothing at all rather than answering wrongly when this is false.
  constexpr bool valid() const {
    if (columns_ <= 0 || leds_per_bin_ <= 0 || bin_pitch_ <= 0) return false;
    // More lit LEDs than the pitch would make consecutive bins overlap.
    if (leds_per_bin_ > bin_pitch_) return false;
    if (table_ == nullptr) return uniform_bins_ > 0;
    for (int c = 0; c < columns_; c++) {
      if (table_[c].first_bin < 0 || table_[c].bins <= 0) return false;
    }
    return true;
  }

  constexpr int columns() const { return valid() ? columns_ : 0; }
  constexpr int leds_per_bin() const { return valid() ? leds_per_bin_ : 0; }
  constexpr int bin_pitch() const { return valid() ? bin_pitch_ : 0; }

  /// The height of the envelope: one past the lowest row any column reaches.
  /// For the U this is 13 even though no single column serves all 13 rows in
  /// the middle - it is the coordinate space, not the bin count.
  constexpr int rows() const {
    if (!valid()) return 0;
    if (table_ == nullptr) return uniform_bins_;
    int lowest = 0;
    for (int c = 0; c < columns_; c++) {
      const int end = table_[c].first_bin + table_[c].bins;
      if (end > lowest) lowest = end;
    }
    return lowest;
  }

  /// How many bins the rack actually has, which for the U is not rows x columns.
  constexpr int bins() const {
    if (!valid()) return 0;
    if (table_ == nullptr) return columns_ * uniform_bins_;
    int total = 0;
    for (int c = 0; c < columns_; c++) total += table_[c].bins;
    return total;
  }

  constexpr Column column(int c) const {
    if (!valid() || c < 0 || c >= columns_) return Column{0, 0};
    if (table_ == nullptr) return Column{0, uniform_bins_};
    return table_[c];
  }

  /// The length of one column's strip, in LEDs. This is what `num_leds` on
  /// that light must be set to.
  constexpr int strand_leds(int c) const {
    const Column col = column(c);
    if (col.bins <= 0) return 0;
    return col.bins * bin_pitch_ - (bin_pitch_ - leds_per_bin_);
  }

  /// Every strip added together - the number that sizes a power supply.
  constexpr int total_leds() const {
    if (!valid()) return 0;
    int total = 0;
    for (int c = 0; c < columns_; c++) total += strand_leds(c);
    return total;
  }

  /// Does this column carry a bin at this envelope row?
  constexpr bool has_bin(int c, int row) const {
    const Column col = column(c);
    if (col.bins <= 0) return false;
    return row >= col.first_bin && row < col.first_bin + col.bins;
  }

  /// The LEDs that light bin (column, row), both zero-indexed.
  ///
  /// The offset is measured from the column's own first bin, not from row 0 of
  /// the envelope, which is what makes a short column work.
  constexpr Span span(int c, int row) const {
    if (!has_bin(c, row)) return Span{};
    const int offset = (row - column(c).first_bin) * bin_pitch_;
    return Span{offset, leds_per_bin_, true};
  }

  /// The same, for callers counting from one - which is how bins are written
  /// down, and how CellarTracker records them.
  constexpr Span span_1(int column_1, int row_1) const {
    if (column_1 < 1 || row_1 < 1) return Span{};
    return span(column_1 - 1, row_1 - 1);
  }

 private:
  const Column *table_;
  int columns_;
  int uniform_bins_;
  int leds_per_bin_;
  int bin_pitch_;
};

/// Visit every bin one column carries, in the order its pixels run.
///
/// `fn` is called as `fn(int envelope_row, Span span)` and only for bins that
/// exist, so a caller never has to know the rack's shape. Templated on the
/// callback so that this header never has to name an ESPHome type.
template <typename Fn>
inline void for_each_bin(const Geometry &g, int column, Fn &&fn) {
  const Column col = g.column(column);
  for (int i = 0; i < col.bins; i++) {
    const int row = col.first_bin + i;
    const Span s = g.span(column, row);
    if (s.valid) fn(row, s);
  }
}

/// Read a bin id like "A7" into a zero-indexed column and row.
///
/// Accepts the ways a bin gets written down by hand and by CellarTracker:
/// lower case, a leading zero, and a space, dash or underscore between the row
/// letter and the column number. Returns false for anything that is not a row
/// letter followed by at least one digit.
///
/// Parsing deliberately does not care whether the rack has that bin - "A7" is
/// a perfectly good bin id that the U-shaped rack happens not to have. Ask
/// `Geometry::has_bin` for that.
inline bool parse_bin_id(const char *bin_id, int *column, int *row) {
  if (bin_id == nullptr || column == nullptr || row == nullptr) return false;

  const char *p = bin_id;
  while (*p == ' ' || *p == '\t') p++;

  char letter = *p;
  if (letter >= 'a' && letter <= 'z') letter = static_cast<char>(letter - ('a' - 'A'));
  if (letter < 'A' || letter > 'Z') return false;
  p++;

  int number = 0;
  bool any_digit = false;
  for (; *p != '\0'; p++) {
    const char ch = *p;
    if (ch >= '0' && ch <= '9') {
      number = number * 10 + (ch - '0');
      any_digit = true;
    } else if (ch == ' ' || ch == '\t' || ch == '-' || ch == '_') {
      continue;  // a separator, not a second field
    } else {
      return false;  // a letter or punctuation where a digit should be
    }
  }
  if (!any_digit || number < 1) return false;

  *row = letter - 'A';
  *column = number - 1;
  return true;
}

}  // namespace rack
