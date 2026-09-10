# Host build for the rack geometry tests.
#
# rack_geometry.h is deliberately free of ESPHome and Arduino headers, so the
# mapping math compiles and runs on a laptop in under a second. That is the
# only reason a C++ test suite is affordable in a repository that is otherwise
# Python: nothing here needs a cross-compiler, a board, or an ESP32.
cmake_minimum_required(VERSION 3.16)
project(rack_geometry_tests CXX)

# C++17 because that is what ESPHome's ESP32 toolchain builds with; a header
# that needs C++20 here would not compile there.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(FetchContent)
FetchContent_Declare(
  doctest
  GIT_REPOSITORY https://github.com/doctest/doctest.git
  GIT_TAG v2.4.11
  GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(doctest)

add_executable(rack_geometry_tests test_rack_geometry.cpp)

# The header ships beside the ESPHome configs, because that is what a user
# copies into their ESPHome directory. The tests reach across to it rather
# than keeping a second copy that could drift.
target_include_directories(rack_geometry_tests
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../../examples/esphome)
target_link_libraries(rack_geometry_tests PRIVATE doctest::doctest)

target_compile_options(rack_geometry_tests PRIVATE
  -Wall -Wextra -Wpedantic -Werror
  # Signed/unsigned mixing is how an LED index quietly wraps to four billion.
  -Wconversion -Wsign-conversion -Wshadow)

enable_testing()
add_test(NAME rack_geometry COMMAND rack_geometry_tests)
