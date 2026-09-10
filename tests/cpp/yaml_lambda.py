"""Pull the C++ out of an ESPHome YAML so a test can compile it.

The coordinate maths lives in the `substitutions:` block of each node's
configuration, which means the firmware and this test suite read the same
characters. Nothing is retyped here, so nothing can drift: if the lambda in
the YAML is wrong, the test compiling it is wrong in the same way and fails.

ESPHome resolves `${name}` inside substitution values as well as in the rest
of the config, so this does too - `paint_column` may say `${bin_pitch}` and
get the number. Everything else about ESPHome's substitution rules is
irrelevant to a block of C++ and is deliberately not reimplemented.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

# ${name} and $name, which is the whole of the syntax that matters here.
_REF = re.compile(r"\$\{([a-zA-Z0-9_]+)\}|\$([a-zA-Z0-9_]+)")

#: Substitutions that hold C++ rather than a value, in the order a test
#: including them needs them declared.
CPP_BLOCKS = ("bin_first_led", "column_extent", "paint_column", "parse_bin_id")


class CircularSubstitution(RuntimeError):
    """A substitution that expands to itself, directly or through others."""


def _loader() -> type[yaml.SafeLoader]:
    """A SafeLoader that ignores the `!secret` and `!lambda` tags."""

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor("!", lambda loader, suffix, node: None)
    return Loader


def substitutions(path: Path) -> dict[str, str]:
    """Every substitution in `path`, with references between them resolved."""
    raw = yaml.load(path.read_text(), Loader=_loader()).get("substitutions", {})
    subs = {key: str(value) for key, value in raw.items()}
    return {key: _resolve(key, subs, ()) for key in subs}


def _resolve(key: str, subs: dict[str, str], seen: tuple[str, ...]) -> str:
    if key in seen:
        raise CircularSubstitution(" -> ".join((*seen, key)))
    if key not in subs:
        raise KeyError(f"{key!r} is referenced but never defined")

    def swap(match: re.Match[str]) -> str:
        return _resolve(match[1] or match[2], subs, (*seen, key))

    return _REF.sub(swap, subs[key])


def emit(source: Path, out_dir: Path) -> list[Path]:
    """Write each C++ substitution of `source` to `out_dir` as a .inc file."""
    subs = substitutions(source)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in CPP_BLOCKS:
        if name not in subs:
            continue
        target = out_dir / f"{name}.inc"
        body = (
            f"// Generated from {source.name} - do not edit.\n"
            f"// Regenerate: python tests/cpp/yaml_lambda.py {source} {out_dir}\n"
            f"{subs[name]}\n"
        )
        # Only rewrite on a real change, so CMake does not relink every build.
        if not target.exists() or target.read_text() != body:
            target.write_text(body)
        written.append(target)
    return written


if __name__ == "__main__":
    for written in emit(Path(sys.argv[1]), Path(sys.argv[2])):
        print(written)
