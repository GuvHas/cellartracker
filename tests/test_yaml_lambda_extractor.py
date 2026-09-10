"""The tool that makes the ESPHome lambdas testable has to be right first.

``tests/cpp`` proves the wine rack's coordinate maths by lifting it out of
``examples/esphome/winerack*led.yaml`` and compiling it. That is only worth
anything if the lifting is faithful: an extractor that dropped a line, or
resolved ``${bin_pitch}`` to something ESPHome would not, would hand doctest a
program that passes while the board runs a different one.

So this checks the extractor against the substitution rules ESPHome actually
applies - including references between substitutions, which is what lets
``paint_column`` be written once with the pitch as a parameter.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples" / "esphome"

_spec = importlib.util.spec_from_file_location(
    "yaml_lambda", REPO_ROOT / "tests" / "cpp" / "yaml_lambda.py"
)
assert _spec and _spec.loader
yaml_lambda = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(yaml_lambda)


def write(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    path = tmp_path / "node.yaml"
    path.write_text(body)
    return path


def test_a_plain_substitution_comes_back_as_written(tmp_path):
    path = write(tmp_path, 'substitutions:\n  bin_pitch: "9"\n')
    assert yaml_lambda.substitutions(path) == {"bin_pitch": "9"}


def test_a_substitution_may_reference_another():
    """The whole reason the maths can be parameterised.

    `bin_first_led` says `${bin_pitch}` rather than 9, so a rack built at a
    different spacing changes one number. ESPHome resolves that; if this did
    not, the tests would compile a literal `${bin_pitch}` and fail to build.
    """
    subs = yaml_lambda.substitutions(EXAMPLES / "winerack1led.yaml")
    assert "${" not in subs["bin_first_led"]
    assert "* 9;" in subs["bin_first_led"]


def test_both_syntaxes_resolve(tmp_path):
    path = write(tmp_path, 'substitutions:\n  n: "4"\n  a: "${n}"\n  b: "$n"\n')
    subs = yaml_lambda.substitutions(path)
    assert subs["a"] == subs["b"] == "4"


def test_references_resolve_all_the_way_down(tmp_path):
    path = write(tmp_path, 'substitutions:\n  a: "1"\n  b: "${a}2"\n  c: "${b}3"\n')
    assert yaml_lambda.substitutions(path)["c"] == "123"


def test_a_substitution_that_expands_to_itself_is_an_error_not_a_hang(tmp_path):
    path = write(tmp_path, 'substitutions:\n  a: "${b}"\n  b: "${a}"\n')
    with pytest.raises(yaml_lambda.CircularSubstitution):
        yaml_lambda.substitutions(path)


def test_a_missing_substitution_is_named(tmp_path):
    path = write(tmp_path, 'substitutions:\n  a: "${nope}"\n')
    with pytest.raises(KeyError, match="nope"):
        yaml_lambda.substitutions(path)


def test_secret_tags_do_not_stop_the_parse():
    """The configs are full of `!secret`, and the extractor has no secrets file.

    Reading one would be worse than failing: this runs in CI, where the only
    thing a secrets file could contain is somebody's real WiFi password.
    """
    subs = yaml_lambda.substitutions(EXAMPLES / "winerack1led.yaml")
    assert subs["device_name"] == "winerack1led"


def test_emit_writes_every_block_the_tests_include(tmp_path):
    written = yaml_lambda.emit(EXAMPLES / "winerack1led.yaml", tmp_path)
    assert sorted(p.name for p in written) == [
        f"{name}.inc" for name in sorted(yaml_lambda.CPP_BLOCKS)
    ]
    for path in written:
        assert "do not edit" in path.read_text()
        assert "${" not in path.read_text()


def test_emit_leaves_an_unchanged_file_alone(tmp_path):
    """CMake reruns the extractor whenever the YAML is touched; rewriting a
    byte-identical file would relink the test suite for nothing."""
    (first,) = [p for p in yaml_lambda.emit(EXAMPLES / "winerack1led.yaml", tmp_path)][:1]
    before = first.stat().st_mtime_ns
    yaml_lambda.emit(EXAMPLES / "winerack1led.yaml", tmp_path)
    assert first.stat().st_mtime_ns == before


def test_both_racks_extract():
    for name in ("winerack1led.yaml", "winerack2led.yaml"):
        subs = yaml_lambda.substitutions(EXAMPLES / name)
        for block in yaml_lambda.CPP_BLOCKS:
            assert block in subs, f"{name} is missing {block}"
