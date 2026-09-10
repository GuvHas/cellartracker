# Host build for the maths that lives in the ESPHome YAML.
#
# There is no C++ source in examples/ any more - the coordinate map is a block
# of C++ inside `substitutions:` in each node's configuration, which is what
# lets a node be a single file. yaml_lambda.py lifts those blocks out and
# writes them as .inc files; test_yaml_lambdas.cpp includes them inside
# wrappers that supply the same names an addressable_lambda has in scope.
#
# So the text under test is the text that ships. Nothing is retyped, and a
# change to the YAML is compiled here before it is ever flashed - which is the
# only reason a C++ suite is affordable in a repository that is otherwise
# Python: no cross-compiler, no board, no ESP32.
cmake_minimum_required(VERSION 3.16)
project(rack_yaml_tests CXX)

# C++17 because that is what ESPHome's ESP32 toolchain builds with. A lambda
# that needs C++20 would pass here and fail on the board.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Python3 REQUIRED COMPONENTS Interpreter)

set(EXAMPLES ${CMAKE_CURRENT_SOURCE_DIR}/../../examples/esphome)
set(GENERATED ${CMAKE_CURRENT_BINARY_DIR}/generated)

# One extraction per node. The output list names every .inc the test includes,
# so editing a lambda in the YAML re-runs this and rebuilds the test.
set(GENERATED_INCS "")
foreach(RACK 1 2)
  set(OUT_DIR ${GENERATED}/rack${RACK})
  set(OUTS
    ${OUT_DIR}/bin_first_led.inc
    ${OUT_DIR}/column_extent.inc
    ${OUT_DIR}/paint_column.inc
    ${OUT_DIR}/parse_bin_id.inc)
  add_custom_command(
    OUTPUT ${OUTS}
    COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_CURRENT_SOURCE_DIR}/yaml_lambda.py
            ${EXAMPLES}/winerack${RACK}led.yaml
            ${OUT_DIR}
    DEPENDS ${EXAMPLES}/winerack${RACK}led.yaml
            ${CMAKE_CURRENT_SOURCE_DIR}/yaml_lambda.py
    COMMENT "Lifting the C++ out of winerack${RACK}led.yaml")
  list(APPEND GENERATED_INCS ${OUTS})
endforeach()

add_custom_target(yaml_lambdas DEPENDS ${GENERATED_INCS})

include(FetchContent)
FetchContent_Declare(
  doctest
  GIT_REPOSITORY https://github.com/doctest/doctest.git
  GIT_TAG v2.4.11
  GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(doctest)

# The .inc files are listed as sources only so that CMake tracks them as
# dependencies; HEADER_FILE_ONLY stops it trying to compile them alone.
set_source_files_properties(${GENERATED_INCS} PROPERTIES HEADER_FILE_ONLY TRUE)
add_executable(rack_yaml_tests test_yaml_lambdas.cpp ${GENERATED_INCS})
add_dependencies(rack_yaml_tests yaml_lambdas)

target_include_directories(rack_yaml_tests PRIVATE ${GENERATED})
target_link_libraries(rack_yaml_tests PRIVATE doctest::doctest)

target_compile_options(rack_yaml_tests PRIVATE
  -Wall -Wextra -Wpedantic -Werror
  # Signed/unsigned mixing is how an LED index quietly wraps to four billion.
  -Wconversion -Wsign-conversion -Wshadow)

enable_testing()
add_test(NAME rack_yaml COMMAND rack_yaml_tests)
