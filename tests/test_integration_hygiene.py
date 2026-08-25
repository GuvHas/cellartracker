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
import re

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
    """The integration calls hass.http.register_view and serves a static path."""
    assert "http" in MANIFEST["dependencies"]


def test_domain_matches_the_package_directory():
    assert MANIFEST["domain"] == COMPONENT.name == cellar_data.DOMAIN


# HACS validates hacs.json against a closed schema and fails the repository
# outright on an unknown key. Everything describing the integration itself
# belongs in manifest.json, which is where HACS reads it from.
HACS_ALLOWED_KEYS = {
    "name",
    "content_in_root",
    "zip_release",
    "filename",
    "hide_default_branch",
    "country",
    "homeassistant",
    "persistent_directory",
    "hacs",
    "render_readme",
}


def test_hacs_manifest_uses_only_keys_hacs_accepts():
    extra = sorted(set(HACS) - HACS_ALLOWED_KEYS)
    assert not extra, f"hacs.json keys HACS rejects: {extra}"


def test_the_version_is_declared_once_in_the_manifest():
    """Two copies drift; HACS reads the integration version from manifest.json."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", MANIFEST["version"])
    assert "version" not in HACS


def test_hacs_declares_the_minimum_home_assistant_version():
    """async_register_static_paths landed in 2024.7."""
    assert HACS["homeassistant"] >= "2024.7.0"


def test_the_repository_is_licensed():
    """HACS refuses to validate a repository with no license."""
    licence = COMPONENT.parent.parent / "LICENSE"
    assert licence.is_file(), "HACS requires a LICENSE file at the repository root"
    assert licence.read_text().strip(), "LICENSE is empty"


def test_config_flow_is_declared():
    assert MANIFEST["config_flow"] is True


def test_integration_owns_its_logger():
    """Lets Home Assistant attribute library log records to this integration."""
    assert "cellartracker" in MANIFEST.get("loggers", [])


@pytest.mark.parametrize("field", ["documentation", "issue_tracker"])
def test_manifest_urls_are_https(field):
    assert MANIFEST[field].startswith("https://")


def test_codeowners_are_github_handles():
    assert MANIFEST["codeowners"]
    for owner in MANIFEST["codeowners"]:
        assert owner.startswith("@"), f"{owner!r} is not a GitHub handle"


def test_iot_class_is_recognised():
    """hassfest's list exactly - the shorter "cloud_poll"/"local_poll" are not on it."""
    assert MANIFEST["iot_class"] in {
        "assumed_state", "calculated", "cloud_polling", "cloud_push",
        "local_polling", "local_push",
    }


def test_integration_type_is_recognised():
    assert MANIFEST["integration_type"] in {
        "device", "entity", "hardware", "helper", "hub", "service", "system", "virtual",
    }


# --------------------------------------------------------------------------
# Translations must cover every step and error the flows actually use.
# hassfest enforces this in CI; catching it here gives a faster signal.
# --------------------------------------------------------------------------
STRINGS = json.loads((COMPONENT / "strings.json").read_text())
EN = json.loads((COMPONENT / "translations" / "en.json").read_text())
FLOW_SOURCE = (COMPONENT / "config_flow.py").read_text()


def test_english_translations_match_strings():
    assert EN == STRINGS, "translations/en.json has drifted from strings.json"


def test_every_flow_step_has_a_translation():
    used = set(re.findall(r'step_id="([^"]+)"', FLOW_SOURCE))
    translated = set(STRINGS["config"]["step"]) | set(STRINGS["options"]["step"])
    assert used <= translated, f"untranslated step(s): {sorted(used - translated)}"


def test_every_error_key_has_a_translation():
    used = set(re.findall(r'"base":\s*"([^"]+)"', FLOW_SOURCE))
    translated = set(STRINGS["config"]["error"])
    assert used <= translated, f"untranslated error(s): {sorted(used - translated)}"


def test_reauth_abort_reason_is_translated():
    """async_update_reload_and_abort defaults to this reason."""
    assert "reauth_successful" in STRINGS["config"]["abort"]
