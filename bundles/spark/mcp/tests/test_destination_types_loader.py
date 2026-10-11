"""Tests for DestinationTypesLoader.

Coverage:
  - loader finds the bundled spec.yaml files at the repo's default root
  - each of the 4 types (syslog/webhook/xsiam_http/splunk_hec) loads
  - the manifest fields[] include visible_when discriminators correctly
  - schema validation rejects a malformed manifest in a temp root
  - reload() re-reads disk
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.usecase.destination_types_loader import (
    DestinationTypesLoader,
    get_destination_types_loader,
    resolve_destinations_root,
    reset_loader_for_tests,
    validate_manifest,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_loader_for_tests()
    yield
    reset_loader_for_tests()


def test_resolve_destinations_root_default_points_into_repo() -> None:
    """Walk-up resolution finds bundles/spark/destinations/ in the repo."""
    root = resolve_destinations_root()
    # Either container path /app/bundle/destinations OR repo path
    # bundles/spark/destinations — both end with .../destinations
    assert root.name == "destinations"


def test_list_all_loads_four_v1_types() -> None:
    """The four shipped manifests (syslog/webhook/xsiam_http/splunk_hec)
    all load + validate."""
    loader = DestinationTypesLoader()
    manifests = loader.list_all()
    assert {"syslog", "webhook", "xsiam_http", "splunk_hec"}.issubset(
        manifests.keys()
    ), f"missing v1 types: {set(manifests.keys())}"


def test_syslog_manifest_has_tls_visible_when() -> None:
    """The tls_ca_cert field on syslog must have visible_when={protocol: tls}."""
    loader = DestinationTypesLoader()
    syslog = loader.get("syslog")
    assert syslog is not None
    ca_field = next(
        (f for f in syslog.fields if f.name == "tls_ca_cert"), None,
    )
    assert ca_field is not None, "tls_ca_cert field missing"
    assert ca_field.visible_when == {"field": "protocol", "value": "tls"}


def test_webhook_manifest_has_discriminated_auth_fields() -> None:
    """webhook bearer_token / basic_password / header_value are gated by
    auth_type."""
    loader = DestinationTypesLoader()
    webhook = loader.get("webhook")
    assert webhook is not None
    bearer = next(
        (f for f in webhook.fields if f.name == "bearer_token"), None,
    )
    assert bearer is not None
    assert bearer.visible_when == {"field": "auth_type", "value": "bearer"}
    basic_pw = next(
        (f for f in webhook.fields if f.name == "basic_password"), None,
    )
    assert basic_pw is not None
    assert basic_pw.visible_when == {"field": "auth_type", "value": "basic"}
    header_v = next(
        (f for f in webhook.fields if f.name == "header_value"), None,
    )
    assert header_v is not None
    assert header_v.visible_when == {
        "field": "auth_type", "value": "api_key_header",
    }


def test_secret_slot_names_picks_secret_fields() -> None:
    """secret_slot_names() returns only fields of type 'secret' (or 'password')."""
    loader = DestinationTypesLoader()
    xsiam = loader.get("xsiam_http")
    assert xsiam is not None
    slots = xsiam.secret_slot_names()
    assert "auth_key" in slots
    # auth_id is plain text (not secret) — should NOT be in slots
    assert "auth_id" not in slots


def test_splunk_hec_manifest_loads() -> None:
    loader = DestinationTypesLoader()
    splunk = loader.get("splunk_hec")
    assert splunk is not None
    assert splunk.category == "Cloud SIEM"
    assert "token" in splunk.secret_slot_names()
    # verify_ssl is a boolean toggle, not a secret
    assert "verify_ssl" not in splunk.secret_slot_names()


def test_validate_manifest_rejects_missing_required(tmp_path: Path) -> None:
    """A malformed manifest with missing required keys fails validation."""
    bad = {
        "schema_version": 1,
        "id": "bogus",
        # name, description, category, icon, ... all missing
        "fields": [],
        "handler": "x.y.z",
    }
    errors = validate_manifest(bad)
    assert errors, "expected validation errors"


def test_loader_skips_invalid_manifests_in_test_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a type's spec.yaml fails schema validation, the loader logs +
    skips it (instead of failing boot)."""
    # Build a fake destinations tree with ONE bad manifest
    root = tmp_path / "destinations"
    root.mkdir()
    # Copy the schema next to the manifests so validation finds it
    real_schema = resolve_destinations_root() / "destination.schema.json"
    (root / "destination.schema.json").write_text(real_schema.read_text())
    bad_dir = root / "bogus"
    bad_dir.mkdir()
    (bad_dir / "spec.yaml").write_text("schema_version: 1\nid: bogus\n")

    monkeypatch.setenv(
        "PHANTOM_DESTINATIONS_BUNDLE_ROOT", str(root),
    )
    # Also clear the schema cache since we changed paths
    from src.usecase import destination_types_loader
    destination_types_loader._schema_cache = None
    reset_loader_for_tests()

    loader = get_destination_types_loader()
    manifests = loader.list_all()
    assert "bogus" not in manifests, "invalid manifest should be skipped"


def test_reload_picks_up_disk_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reload() re-reads disk so a hot-reload endpoint could refresh."""
    # Capture the REAL bundled paths BEFORE we monkeypatch the root.
    real_root = resolve_destinations_root()
    real_schema_text = (real_root / "destination.schema.json").read_text()
    real_syslog_text = (real_root / "syslog" / "spec.yaml").read_text()

    root = tmp_path / "destinations"
    root.mkdir()
    (root / "destination.schema.json").write_text(real_schema_text)

    # Start with empty root
    monkeypatch.setenv(
        "PHANTOM_DESTINATIONS_BUNDLE_ROOT", str(root),
    )
    from src.usecase import destination_types_loader
    destination_types_loader._schema_cache = None
    reset_loader_for_tests()
    loader = get_destination_types_loader()
    assert loader.list_all() == {}

    # Add a valid manifest using the bundled syslog content as the seed
    syslog_dir = root / "syslog"
    syslog_dir.mkdir()
    (syslog_dir / "spec.yaml").write_text(real_syslog_text)

    after = loader.reload()
    assert "syslog" in after
