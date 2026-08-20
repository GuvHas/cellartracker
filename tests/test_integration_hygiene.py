"""F-07 and F-08: import placement and manifest correctness.

F-07: ``WineCellarData.__init__`` imported the client library inside the
constructor, which ``async_setup_entry`` runs on the event loop. Home Assistant
flags that as "Detected blocking call to import_module inside the event loop".
Home Assistant imports integration modules in an executor, so a module-level
import does the file I/O off the loop.

F-08: the manifest floated its requirement, so any upstream release reached
every user unreviewed, and it registered HTTP views without declaring the
``http`` dependency.
"""

from __future__ import annotations

import inspect
import json
import pathlib

import pytest

from cellar_tracker import cellar_data, config_flow

COMPONENT = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "cellar_tracker"
MANIFEST = json.loads((COMPONENT / "manifest.json").read_text())
HACS = json.loads((COMPONENT.parent.parent / "hacs.json").read_text())


# --------------------------------------------------------------------------
# F-07: imports must not happen on the event loop
# --------------------------------------------------------------------------
def test_client_library_is_imported_at_module_level():
    assert hasattr(cellar_data, "cellartracker"), (
        "the client library must be imported at module scope, not in __init__"
    )


def test_coordinator_init_performs_no_import():
    """__init__ runs on the event loop via async_setup_entry."""
    source = inspect.getsource(cellar_data.WineCellarData.__init__)
    assert "import " not in source


@pytest.mark.parametrize(
    "func",
    [
        cellar_data.WineCellarData._process_inventory,
        cellar_data.WineCellarData._async_update_data,
    ],
)
def test_hot_paths_perform_no_import(func):
    assert "import " not in inspect.getsource(func)


def test_config_flow_validator_performs_no_import():
    source = inspect.getsource(config_flow._validate_credentials)
    assert "import " not in source


# --------------------------------------------------------------------------
# F-08: manifest correctness
# --------------------------------------------------------------------------
def test_requirements_are_version_pinned():
    assert MANIFEST["requirements"], "the client library must be declared"
    for requirement in MANIFEST["requirements"]:
        assert "==" in requirement, f"{requirement!r} floats; pin it"


def test_http_dependency_is_declared():
    """The integration calls hass.http.register_view."""
    assert "http" in MANIFEST["dependencies"]


def test_domain_matches_the_package_directory():
    assert MANIFEST["domain"] == COMPONENT.name == cellar_data.DOMAIN


def test_manifest_and_hacs_versions_agree():
    assert MANIFEST["version"] == HACS["version"]


def test_config_flow_is_declared():
    assert MANIFEST["config_flow"] is True


def test_integration_owns_its_logger():
    """Lets Home Assistant attribute library log records to this integration."""
    assert "cellartracker" in MANIFEST.get("loggers", [])
