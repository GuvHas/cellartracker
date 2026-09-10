// Just enough ESPHome to compile a lambda lifted out of the YAML.
// =============================================================================
//
// An `addressable_lambda` effect body is ordinary C++ that happens to be
// written inside a string. What it can see is small: `it`, the strand being
// painted; `Color`; and `id(x)`, which is a macro over a global. Provide those
// three and the shipped text compiles here exactly as it compiles on the ESP32.
//
// The important one is FakeLight::operator[], which goes through std::vector
// ::at. On the board an index past the end of a strand writes into whatever is
// next in RAM and the bug shows up as a flickering column somewhere else
// entirely. Here it throws, and a test can say so out loud.

#pragma once

#include <cstdint>
#include <ostream>
#include <stdexcept>
#include <vector>

/// ESPHome's Color, to the extent a strand lambda uses it.
struct Color {
  uint8_t r{0};
  uint8_t g{0};
  uint8_t b{0};

  constexpr Color() = default;
  constexpr Color(int red, int green, int blue)
      : r(static_cast<uint8_t>(red)), g(static_cast<uint8_t>(green)), b(static_cast<uint8_t>(blue)) {}

  constexpr bool operator==(const Color &other) const {
    return r == other.r && g == other.g && b == other.b;
  }
  constexpr bool operator!=(const Color &other) const { return !(*this == other); }
  constexpr bool is_black() const { return r == 0 && g == 0 && b == 0; }
};

/// So that a failing CHECK prints the two colours rather than "{?} == {?}".
inline std::ostream &operator<<(std::ostream &out, const Color &colour) {
  return out << "Color(" << +colour.r << ", " << +colour.g << ", " << +colour.b << ")";
}

/// The `it` an addressable_lambda is handed.
///
/// `size()` returns int because that is what ESPHome's AddressableLight does,
/// and the lambda compares it against an int counter. Matching the signedness
/// keeps -Wsign-compare meaningful over the shipped text rather than over a
/// paraphrase of it.
class FakeLight {
 public:
  explicit FakeLight(int leds) : pixels_(static_cast<size_t>(leds < 0 ? 0 : leds)) {}

  int size() const { return static_cast<int>(pixels_.size()); }

  /// Throws std::out_of_range where the firmware would corrupt memory.
  Color &operator[](int index) {
    if (index < 0) throw std::out_of_range("negative LED index");
    return pixels_.at(static_cast<size_t>(index));
  }
  const Color &operator[](int index) const {
    if (index < 0) throw std::out_of_range("negative LED index");
    return pixels_.at(static_cast<size_t>(index));
  }

  int lit() const {
    int count = 0;
    for (const Color &pixel : pixels_)
      if (!pixel.is_black()) count++;
    return count;
  }

 private:
  std::vector<Color> pixels_;
};

// `id(cell_rgb)` in the YAML is ESPHome's accessor for a global. Here the
// global is just a global.
#define id(name) (name)
