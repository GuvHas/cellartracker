"""Reported by Codex on #19: the type gate was checking nothing.

The mypy job introduced with the typed coordinator passed on the first try,
which should have been the tell. Home Assistant was not installed in that job
and ``ignore_missing_imports`` was on, so:

  * every ``homeassistant.*`` import resolved to ``Any``;
  * ``WineCellarData`` derives from ``DataUpdateCoordinator``, which was then
    ``Any``, and a class deriving from ``Any`` has ``Any`` for every member it
    does not declare itself;
  * so ``coordinator.data`` was ``Any`` at all five sensors, both views and the
    diagnostics - exactly the call sites ``DataUpdateCoordinator[CellarData]``
    was added to type.

``reveal_type(coordinator.data)`` reported ``Any``, and
``coordinator.data["definitely_not_a_key"]`` was accepted without a word. The
gate reported success over code it had not checked, which is worse than having
no gate: the PR claimed those errors were now impossible.

The fix is to resolve Home Assistant's real types (requirements_mypy.txt) and
to refuse imported ``Any`` rather than assume it. These tests pin the wiring
that makes that true. The claim itself - that ``coordinator.data`` really does
have a type now - is asserted where a type checker can verify it, in
tests/typing_gate.py, which mypy checks and pytest does not collect.
"""

from __future__ import annotations

import pathlib
import tomllib

REPO = pathlib.Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"]["mypy"]
CI = (REPO / ".github" / "workflows" / "ci.yml").read_text()
GATE = REPO / "tests" / "typing_gate.py"


def mypy_requirements() -> str:
    """The type job's pinned dependencies, or "" if the file is gone.

    Read through a function rather than at import, so that a missing file
    fails the tests that depend on it with their own message instead of
    breaking collection for the whole module.
    """
    path = REPO / "requirements_mypy.txt"
    return path.read_text() if path.is_file() else ""


# --------------------------------------------------------------------------
# Home Assistant has to be visible to the checker
# --------------------------------------------------------------------------
def test_home_assistant_is_installed_for_the_type_job():
    """Its absence is what made every inherited member Any."""
    assert "homeassistant==" in mypy_requirements(), (
        "mypy cannot check code against a framework it cannot see"
    )


def test_the_home_assistant_version_is_pinned():
    """An unpinned framework makes the gate's verdict depend on the day."""
    requirements = mypy_requirements()
    assert requirements, "requirements_mypy.txt is missing"
    for line in requirements.splitlines():
        requirement = line.split("#")[0].strip()
        if requirement:
            assert "==" in requirement, f"{requirement} is not pinned"


def test_the_type_job_installs_those_requirements():
    assert "requirements_mypy.txt" in CI


def test_unresolved_imports_are_not_waved_through():
    """ignore_missing_imports is what turned Home Assistant into Any."""
    assert not CONFIG.get("ignore_missing_imports", False), (
        "a blanket ignore_missing_imports puts the gate back where it started"
    )


def test_imported_any_is_rejected():
    """The belt to that brace: an unresolved import must fail, not degrade."""
    assert CONFIG["disallow_any_unimported"] is True
    assert CONFIG["warn_return_any"] is True


def test_the_one_untyped_dependency_is_stubbed_rather_than_ignored():
    """cellartracker ships no py.typed, and RateLimited derives from its errors.

    A base class that is Any hands every undeclared member back as Any - the
    same hole, one dependency further down.
    """
    stubs = REPO / "stubs" / "cellartracker"
    assert (stubs / "errors.pyi").is_file()
    assert "stubs" in CONFIG["mypy_path"]


# --------------------------------------------------------------------------
# The gate file itself
# --------------------------------------------------------------------------
def test_the_gate_is_checked():
    assert GATE.is_file()
    assert any(str(GATE).endswith(entry.lstrip("./")) for entry in CONFIG["files"]), (
        f"{GATE.name} is not in mypy's files, so nothing checks it"
    )


def test_the_gate_asserts_the_types_that_were_any():
    """Every member Codex named, asserted where a checker can see it."""
    source = GATE.read_text()
    for expression in (
        "assert_type(coordinator.data,",
        "assert_type(entry.runtime_data,",
        'assert_type(data["total_bottles"], int)',
    ):
        assert expression in source, f"the gate no longer asserts {expression}"


def test_the_gate_still_expects_a_misspelled_key_to_be_rejected():
    source = GATE.read_text()
    assert 'data["definitely_not_a_key"]  # type: ignore[typeddict-item]' in source


def test_the_negative_assertions_can_fail():
    """The misspelled-key checks are ignores, so they only bite with this on.

    ``warn_unused_ignores`` turns an ignore that stopped being necessary into
    an error of its own. Without it, a gate that quietly went back to accepting
    those keys would still report success.
    """
    assert CONFIG["warn_unused_ignores"] is True


def test_pytest_does_not_collect_the_gate():
    """Its assertions are static; importing it would need the real framework."""
    assert not GATE.name.startswith("test_")
    assert not GATE.name.endswith("_test.py")


# --------------------------------------------------------------------------
# The two have to agree on a Python version
# --------------------------------------------------------------------------
def test_the_job_runs_a_python_the_pinned_home_assistant_supports():
    """2026.2 needs 3.13; checking it under 3.12 fails before it starts."""
    assert CONFIG["python_version"] == "3.13"
    job = CI.split("  mypy:")[1].split("\n  hassfest:")[0]
    assert 'python-version: "3.13"' in job
