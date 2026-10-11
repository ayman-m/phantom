"""Tests for the data sources YAML loader.

Covers:
  • Bundle-root scan loads N YAMLs
  • User-root scan loads operator-uploaded YAMLs
  • Bundle wins on id collision
  • get_by_id / get_user / get_by_3tuple resolution
  • Schema validation (positive + negative)
  • write_user happy path + bundle-collision refusal
  • delete_user idempotency + bundle-protection refusal
  • YamlDataSource.to_catalog_row shape
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

# Per the existing test convention — import via `usecase.X` so the test
# sees the same module instance as production.
from usecase.data_sources_yaml_loader import (
    DataSourcesYamlLoader,
    YamlDataSource,
    set_data_sources_yaml_loader,
    validate_yaml_doc,
)


# ─── Fixtures ─────────────────────────────────────────────────────


def _write_yaml(path: Path, doc: dict) -> None:
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False)


def _minimal_doc(
    *,
    id: str = "acme-app",
    vendor: str = "AcmeCorp",
    product: str = "AcmeApp",
    origin: str = "bundle",
    fields: list | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "id": id,
        "pack_name": product,
        "rule_name": f"{product}Rule",
        "dataset_name": f"{vendor.lower()}_{product.lower()}_raw",
        "vendor": vendor,
        "product": product,
        "description": f"{vendor} {product} description",
        "categories": ["Endpoint"],
        "version": "1.0.0",
        "origin": origin,
        "author": "phantom-bundle" if origin == "bundle" else "operator",
        "uploaded_by": None,
        "created_at": "2026-05-23T00:00:00Z",
        "updated_at": "2026-05-23T00:00:00Z",
        "logo": None,
        "formats": ["SYSLOG", "CEF"],
        "is_rawlog_only": False,
        "fields": fields or [],
        # No xdm_mappings: they are not part of the schema.
    }


@pytest.fixture
def loader(tmp_path: Path) -> DataSourcesYamlLoader:
    """Fresh loader rooted in tmp_path. Teardown clears the singleton."""
    bundle_root = tmp_path / "bundle"
    user_root = tmp_path / "user"
    bundle_root.mkdir()
    user_root.mkdir()
    # Stamp the schema file next to bundle root so validation works
    import json
    from usecase.data_sources_yaml_loader import resolve_schema_path
    real_schema_path = resolve_schema_path()
    if real_schema_path.is_file():
        (bundle_root / "data_source.schema.json").write_text(
            real_schema_path.read_text()
        )
    loader = DataSourcesYamlLoader(bundle_root=bundle_root, user_root=user_root)
    # Override the module-level schema cache so resolve_schema_path picks
    # up the tmp one — easiest: monkey-patch the env var on the loader.
    import os
    old_bundle = os.environ.get("PHANTOM_DATA_SOURCES_BUNDLE_ROOT")
    os.environ["PHANTOM_DATA_SOURCES_BUNDLE_ROOT"] = str(bundle_root)
    # Reset schema cache to force re-read from new path
    import usecase.data_sources_yaml_loader as mod
    mod._schema_cache = None
    set_data_sources_yaml_loader(loader)
    yield loader
    set_data_sources_yaml_loader(None)
    mod._schema_cache = None
    if old_bundle is None:
        os.environ.pop("PHANTOM_DATA_SOURCES_BUNDLE_ROOT", None)
    else:
        os.environ["PHANTOM_DATA_SOURCES_BUNDLE_ROOT"] = old_bundle


# ─── Loader scan behavior ─────────────────────────────────────────


def test_list_all_empty_roots_returns_empty(loader):
    assert loader.list_all() == []


def test_list_all_reads_bundle_yamls(loader):
    _write_yaml(loader.bundle_root / "pack1" / "data_source.yaml",
                _minimal_doc(id="pack1", vendor="V1"))
    _write_yaml(loader.bundle_root / "pack2" / "data_source.yaml",
                _minimal_doc(id="pack2", vendor="V2"))
    sources = loader.list_all()
    assert len(sources) == 2
    assert {s.id for s in sources} == {"pack1", "pack2"}
    assert all(s.origin == "bundle" for s in sources)


def test_list_all_reads_user_yamls(loader):
    _write_yaml(loader.user_root / "custom-app" / "data_source.yaml",
                _minimal_doc(id="custom-app", vendor="AcmeCorp", origin="user"))
    sources = loader.list_all()
    assert len(sources) == 1
    assert sources[0].id == "custom-app"
    assert sources[0].origin == "user"


def test_list_all_bundle_wins_on_collision(loader):
    """Bundle id always shadows a same-id user upload."""
    _write_yaml(loader.bundle_root / "shared-id" / "data_source.yaml",
                _minimal_doc(id="shared-id", vendor="OfficialVendor"))
    _write_yaml(loader.user_root / "shared-id" / "data_source.yaml",
                _minimal_doc(id="shared-id", vendor="OperatorVendor", origin="user"))
    sources = loader.list_all()
    assert len(sources) == 1
    assert sources[0].vendor == "OfficialVendor"
    assert sources[0].origin == "bundle"


def test_list_user_returns_only_user(loader):
    _write_yaml(loader.bundle_root / "b1" / "data_source.yaml", _minimal_doc(id="b1"))
    _write_yaml(loader.user_root / "u1" / "data_source.yaml",
                _minimal_doc(id="u1", origin="user"))
    user_only = loader.list_user()
    assert len(user_only) == 1
    assert user_only[0].id == "u1"


def test_get_by_id(loader):
    _write_yaml(loader.bundle_root / "pack-a" / "data_source.yaml",
                _minimal_doc(id="pack-a"))
    found = loader.get_by_id("pack-a")
    assert found is not None
    assert found.id == "pack-a"
    assert loader.get_by_id("non-existent") is None


def test_scan_cache_does_not_reparse_unchanged_yamls(loader, monkeypatch):
    """The per-root cache short-circuits when root mtime hasn't
    changed. Without the cache, every list_all() / get_by_id() call
    re-walks the bundle directory and re-parses every YAML, which is
    slow with hundreds of bundled YAMLs.
    """
    _write_yaml(loader.bundle_root / "pack-cached" / "data_source.yaml",
                _minimal_doc(id="pack-cached"))

    call_count = {"n": 0}
    original_load_one = loader._load_one

    def counting_load_one(*args, **kwargs):
        call_count["n"] += 1
        return original_load_one(*args, **kwargs)

    monkeypatch.setattr(loader, "_load_one", counting_load_one)

    # First call — scan happens, _load_one called once for the bundle YAML.
    loader.list_all()
    assert call_count["n"] == 1
    # Second call — cache hit, no _load_one invocation.
    loader.list_all()
    assert call_count["n"] == 1, (
        "expected cache hit on second list_all(); cache is not working"
    )
    # get_by_id should also be O(1) via the id-index, no re-scan.
    loader.get_by_id("pack-cached")
    loader.get_by_id("pack-cached")
    loader.get_by_id("pack-cached")
    assert call_count["n"] == 1, (
        "get_by_id should hit the cached id-index, not rescan YAMLs"
    )


def test_scan_cache_invalidates_when_user_root_changes(loader):
    """Adding/removing a YAML in user_root bumps the dir mtime, which
    invalidates the per-root cache automatically (plus the explicit
    `invalidate()` call from save_user/delete_user as a 1s-quantization
    safety net)."""
    # Empty roots; cache the empty state
    assert loader.list_all() == []

    # Write a user upload — should call invalidate() internally
    doc = _minimal_doc(id="user-upload-1", origin="user")
    ds, errors = loader.write_user(doc)
    assert errors == [], f"unexpected errors: {errors}"
    assert ds is not None

    # Next list_all should see the new user upload
    all_after = loader.list_all()
    assert len(all_after) == 1
    assert all_after[0].id == "user-upload-1"

    # Delete also invalidates
    assert loader.delete_user("user-upload-1") is True
    all_after_delete = loader.list_all()
    assert all_after_delete == []


def test_get_by_3tuple(loader):
    _write_yaml(loader.bundle_root / "pack-x" / "data_source.yaml",
                _minimal_doc(id="pack-x", vendor="VendorX", product="ProductX"))
    found = loader.get_by_3tuple("ProductX", "ProductXRule", "vendorx_productx_raw")
    assert found is not None
    assert found.id == "pack-x"
    assert loader.get_by_3tuple("X", "Y", "Z") is None


def test_skips_directories_without_yaml(loader):
    """A directory without data_source.yaml is silently skipped."""
    (loader.bundle_root / "stub-dir").mkdir()
    (loader.bundle_root / "stub-dir" / "README.md").write_text("not a yaml")
    sources = loader.list_all()
    assert sources == []


def test_skips_malformed_yaml(loader):
    """A YAML that fails to parse is logged + skipped, not raised."""
    (loader.bundle_root / "broken" / "data_source.yaml").parent.mkdir(parents=True)
    (loader.bundle_root / "broken" / "data_source.yaml").write_text(
        "this is: not\n  - valid: yaml\n   bad indent"
    )
    sources = loader.list_all()
    # Other sources still load
    assert all(s.id != "broken" for s in sources)


# ─── Schema validation ─────────────────────────────────────────────


def test_validate_minimal_doc_passes(loader):
    ok, errors = validate_yaml_doc(_minimal_doc())
    assert ok
    assert errors == []


def test_validate_missing_required_field_fails(loader):
    doc = _minimal_doc()
    del doc["pack_name"]
    ok, errors = validate_yaml_doc(doc)
    assert not ok
    assert any("pack_name" in e for e in errors)


def test_validate_wrong_schema_version_fails(loader):
    doc = _minimal_doc()
    doc["schema_version"] = 99
    ok, errors = validate_yaml_doc(doc)
    assert not ok


def test_validate_enum_field_without_enum_values_fails(loader):
    doc = _minimal_doc(fields=[{"name": "severity", "type": "enum"}])
    ok, errors = validate_yaml_doc(doc)
    assert not ok
    # The schema's allOf rule requires enum_values when type=enum
    assert any("enum_values" in e for e in errors)


def test_validate_regex_field_without_pattern_fails(loader):
    doc = _minimal_doc(fields=[{"name": "code", "type": "regex"}])
    ok, errors = validate_yaml_doc(doc)
    assert not ok


def test_validate_field_with_proper_enum_passes(loader):
    doc = _minimal_doc(fields=[
        {"name": "severity", "type": "enum", "enum_values": ["low", "high"]}
    ])
    ok, errors = validate_yaml_doc(doc)
    assert ok, errors


# ─── Write + delete ────────────────────────────────────────────────


def test_write_user_happy_path(loader):
    doc = _minimal_doc(id="acme-app-001", vendor="AcmeCorp", origin="user")
    ds, errors = loader.write_user(doc)
    assert errors == []
    assert ds is not None
    assert ds.id == "acme-app-001"
    assert ds.origin == "user"
    # File landed on disk
    path = loader.user_root / "acme-app-001" / "data_source.yaml"
    assert path.is_file()
    # Round-trips through list_all
    sources = loader.list_all()
    assert any(s.id == "acme-app-001" for s in sources)


def test_write_user_forces_origin_user(loader):
    """Even if the operator's YAML says origin=bundle, write_user overrides."""
    doc = _minimal_doc(id="forced-user", origin="bundle")
    ds, errors = loader.write_user(doc)
    assert errors == []
    assert ds.origin == "user"


def test_write_user_refuses_bundle_id_collision(loader):
    """Operator can't upload a YAML that would shadow a bundle id."""
    _write_yaml(loader.bundle_root / "fortinet-1" / "data_source.yaml",
                _minimal_doc(id="fortinet-1"))
    doc = _minimal_doc(id="fortinet-1", origin="user")
    ds, errors = loader.write_user(doc)
    assert ds is None
    assert any("reserved" in e.lower() for e in errors)


def test_write_user_rejects_invalid_yaml(loader):
    """Validation errors surface as the errors list."""
    doc = _minimal_doc()
    del doc["vendor"]
    ds, errors = loader.write_user(doc)
    assert ds is None
    assert errors


def test_delete_user_happy_path(loader):
    """delete_user removes the YAML and returns True."""
    doc = _minimal_doc(id="to-be-deleted", origin="user")
    loader.write_user(doc)
    assert loader.delete_user("to-be-deleted") is True
    assert not (loader.user_root / "to-be-deleted").exists()


def test_delete_user_idempotent_when_missing(loader):
    """Deleting non-existent id returns False, doesn't raise."""
    assert loader.delete_user("never-existed") is False


# ─── update_user ────────────────────────────────────────


def test_update_user_happy_path(loader):
    """update_user overwrites an existing user upload; preserves created_at."""
    # Seed with an upload that has a known created_at
    doc = _minimal_doc(id="editable", origin="user")
    doc["created_at"] = "2020-01-01T00:00:00Z"
    ds, errors = loader.write_user(doc)
    assert errors == []
    assert ds is not None

    # Re-load the on-disk YAML to get the actual created_at the loader stamped
    on_disk = loader.get_user("editable")
    original_created = on_disk._source_path.read_text()
    assert "2020-01-01T00:00:00Z" in original_created

    # Edit: change product + description
    updated_doc = _minimal_doc(id="editable", origin="user")
    updated_doc["product"] = "EditedProduct"
    updated_doc["description"] = "Now with feeling"
    # Operator may or may not include created_at in their body; either way
    # the server overrides with on-disk value.
    updated_doc["created_at"] = "2099-12-31T00:00:00Z"  # operator's lie

    ds2, errors2 = loader.update_user("editable", updated_doc)
    assert errors2 == []
    assert ds2 is not None
    assert ds2.product == "EditedProduct"
    assert ds2.description == "Now with feeling"

    # created_at preserved from the on-disk YAML, NOT the operator's body.
    final = (loader.user_root / "editable" / "data_source.yaml").read_text()
    assert "2020-01-01T00:00:00Z" in final
    assert "2099-12-31T00:00:00Z" not in final


def test_update_user_returns_404_when_not_found(loader):
    """update_user on non-existent id returns 'not found' error."""
    doc = _minimal_doc(id="nonexistent", origin="user")
    ds, errors = loader.update_user("nonexistent", doc)
    assert ds is None
    assert any("not found" in e.lower() for e in errors)


def test_update_user_refuses_id_mismatch(loader):
    """PUT is not rename — body id must equal path id."""
    doc = _minimal_doc(id="original", origin="user")
    loader.write_user(doc)

    # Try to PUT with body.id="renamed" against path "original"
    rename_doc = _minimal_doc(id="renamed", origin="user")
    ds, errors = loader.update_user("original", rename_doc)
    assert ds is None
    assert any("id mismatch" in e.lower() for e in errors)


def test_update_user_refuses_invalid_path_id(loader):
    """Path-traversal / slash injection refused at the loader layer too."""
    doc = _minimal_doc(id="../escape", origin="user")
    ds, errors = loader.update_user("../escape", doc)
    assert ds is None
    assert any("invalid id" in e.lower() for e in errors)


def test_update_user_refreshes_updated_at(loader):
    """updated_at is always refreshed to now, regardless of body."""
    doc = _minimal_doc(id="touch-test", origin="user")
    doc["updated_at"] = "2020-01-01T00:00:00Z"
    loader.write_user(doc)

    updated_doc = _minimal_doc(id="touch-test", origin="user")
    updated_doc["updated_at"] = "2020-01-01T00:00:00Z"  # operator-supplied stale
    ds, errors = loader.update_user("touch-test", updated_doc)
    assert errors == []
    final = (loader.user_root / "touch-test" / "data_source.yaml").read_text()
    # Stale operator-supplied updated_at must NOT have been kept
    assert "2020-01-01" not in final.split("updated_at:")[1].split("\n")[0]


def test_update_user_rejects_invalid_yaml(loader):
    """Validation errors propagate as the errors list (no write)."""
    doc = _minimal_doc(id="will-break", origin="user")
    loader.write_user(doc)
    # Now PUT an invalid edit (vendor field stripped)
    bad_doc = _minimal_doc(id="will-break", origin="user")
    del bad_doc["vendor"]
    ds, errors = loader.update_user("will-break", bad_doc)
    assert ds is None
    assert errors


def test_delete_user_refuses_bundle_id(loader):
    """delete_user raises on bundle ids — the operator can't delete what
    they didn't upload."""
    _write_yaml(loader.bundle_root / "protected" / "data_source.yaml",
                _minimal_doc(id="protected"))
    with pytest.raises(ValueError, match="bundled"):
        loader.delete_user("protected")


# ─── to_catalog_row + to_doc ───────────────────────────────────────


def test_to_catalog_row_shape(loader):
    doc = _minimal_doc(
        id="cr-test",
        vendor="TestVendor",
        fields=[
            {"name": "f1", "type": "string", "is_array": False},
            {"name": "_id", "type": "string", "is_meta": True},
        ],
    )
    ds = YamlDataSource.from_doc(
        doc, loader.bundle_root / "cr-test" / "data_source.yaml", "bundle",
    )
    row = ds.to_catalog_row(installed=True)
    # Shape mirrors the legacy catalog row shape so the UI doesn't need to change
    expected_keys = {
        "pack_name", "rule_name", "dataset_name", "supported_modules",
        "pack_description", "currentVersion", "is_rawlog_only",
        "field_count", "non_meta_field_count", "logo_url", "logo_type",
        "installed", "vendor_key", "vendor_display_name",
        "vendor_primary_color", "categories", "origin", "id",
    }
    assert expected_keys.issubset(row.keys())
    assert row["field_count"] == 2
    assert row["non_meta_field_count"] == 1
    assert row["installed"] is True
    assert row["origin"] == "bundle"


def test_to_catalog_row_user_with_inline_logo_uses_inline_route(loader):
    """Any YAML carrying an inline `logo:` block — bundle OR user —
    routes through /inline-logo/<id>, which serves from either root
    (not the per-user /user/<id>/logo path)."""
    doc = _minimal_doc(id="ul-test", origin="user")
    doc["logo"] = {
        "mime_type": "image/svg+xml",
        "data": base64.b64encode(b"<svg></svg>").decode("ascii"),
    }
    ds = YamlDataSource.from_doc(
        doc, loader.user_root / "ul-test" / "data_source.yaml", "user",
    )
    row = ds.to_catalog_row()
    assert "/inline-logo/ul-test" in row["logo_url"]


def test_to_catalog_row_bundle_with_inline_logo_uses_inline_route(loader):
    """Bundle YAMLs that carry an inline `logo:` block also
    route through /inline-logo/<id>, not the legacy vendor route. This
    is the path that lets bundled YAMLs ship self-contained SVGs."""
    doc = _minimal_doc(id="bl-test", origin="bundle")
    doc["logo"] = {
        "mime_type": "image/svg+xml",
        "data": base64.b64encode(b"<svg></svg>").decode("ascii"),
    }
    ds = YamlDataSource.from_doc(
        doc, loader.bundle_root / "bl-test" / "data_source.yaml", "bundle",
    )
    row = ds.to_catalog_row()
    assert "/inline-logo/bl-test" in row["logo_url"]


def test_to_catalog_row_bundle_without_inline_logo_returns_null(loader):
    """Bundle YAMLs WITHOUT an inline `logo:` block return
    `logo_url: None` so the UI renders the placeholder icon directly
    without making a request guaranteed to 404. The legacy
    /logo/<pack_name> route is still served by the MCP, but catalogs
    don't reference it.
    """
    doc = _minimal_doc(id="nl-test", origin="bundle", product="MyPack")
    doc["logo"] = None  # no inline data
    ds = YamlDataSource.from_doc(
        doc, loader.bundle_root / "nl-test" / "data_source.yaml", "bundle",
    )
    row = ds.to_catalog_row()
    assert row["logo_url"] is None


def test_to_catalog_row_user_without_inline_logo_returns_null(loader):
    """Same null-on-no-inline rule for user origin."""
    doc = _minimal_doc(id="nu-test", origin="user")
    doc["logo"] = None
    ds = YamlDataSource.from_doc(
        doc, loader.user_root / "nu-test" / "data_source.yaml", "user",
    )
    row = ds.to_catalog_row()
    assert row["logo_url"] is None


def test_to_doc_round_trip(loader):
    """to_doc strips loader-internal fields + preserves YAML semantics."""
    original = _minimal_doc(id="rt-test", vendor="RTVendor")
    ds = YamlDataSource.from_doc(
        original, loader.bundle_root / "rt-test" / "data_source.yaml", "bundle",
    )
    rendered = ds.to_doc()
    # Loader-internals (_source_path, _source_root) should NOT be in the doc
    assert "_source_path" not in rendered
    assert "_source_root" not in rendered
    # Key fields preserved
    assert rendered["id"] == "rt-test"
    assert rendered["vendor"] == "RTVendor"
    assert rendered["schema_version"] == 1


# ─── `delivery` (syslog | http) ──────────────────────────────


_REAL_BUNDLE = Path(__file__).resolve().parents[2] / "data-sources"


def _real_doc(dirname: str) -> dict:
    import yaml
    return yaml.safe_load((_REAL_BUNDLE / dirname / "data_source.yaml").read_text())


def _ds_from(doc: dict) -> YamlDataSource:
    return YamlDataSource.from_doc(doc, Path("/x/data_source.yaml"), "bundle")


def test_delivery_absent_defaults_to_syslog_and_stays_absent():
    doc = _minimal_doc()
    assert "delivery" not in doc
    ds = _ds_from(doc)
    assert ds.delivery == "syslog"
    # default is omitted from the serialized doc -> existing sources
    # round-trip without gaining a key
    assert "delivery" not in ds.to_doc()


def test_delivery_http_round_trips():
    doc = _minimal_doc()
    doc["delivery"] = "http"
    ds = _ds_from(doc)
    assert ds.delivery == "http"
    rendered = ds.to_doc()
    assert rendered["delivery"] == "http"
    assert _ds_from(rendered).delivery == "http"


def test_delivery_explicit_syslog_is_omitted_on_serialize():
    doc = _minimal_doc()
    doc["delivery"] = "syslog"
    ds = _ds_from(doc)
    assert ds.delivery == "syslog"
    assert "delivery" not in ds.to_doc()


@pytest.mark.parametrize("bad", ["HTTP", "https", "", None, 7, ["http"], {"a": 1}])
def test_delivery_invalid_value_falls_back_to_syslog(bad):
    doc = _minimal_doc()
    doc["delivery"] = bad
    ds = _ds_from(doc)
    assert ds.delivery == "syslog"
    assert "delivery" not in ds.to_doc()


def test_delivery_exposed_in_catalog_row():
    assert _ds_from(_minimal_doc()).to_catalog_row()["delivery"] == "syslog"
    doc = _minimal_doc()
    doc["delivery"] = "http"
    assert _ds_from(doc).to_catalog_row()["delivery"] == "http"


def test_real_syslog_yaml_round_trips_without_delivery_key():
    doc = _real_doc("Okta__OktaModelingRules__okta_sso_raw")
    assert "delivery" not in doc
    first = _ds_from(doc).to_doc()
    assert "delivery" not in first
    # to_doc is a fixed point: serialising twice is identical
    assert _ds_from(first).to_doc() == first


HTTP_YAMLS = [
    # (http dir, syslog sibling dir)
    ("Okta__OktaHttpCollector__okta_sso_raw",
     "Okta__OktaModelingRules__okta_sso_raw"),
    ("ProofpointTAP__ProofpointTAPHttpCollector__proofpoint_tap_raw",
     "ProofpointTAP__ProofpointTAPModelingRules__proofpoint_tap_raw"),
    ("GoogleDrive__GoogleDriveHttpCollector__google_workspace_drive_raw",
     "GoogleDrive__GoogleDrive__google_workspace_drive_raw"),
]


@pytest.mark.parametrize("http_dir,syslog_dir", HTTP_YAMLS)
def test_real_http_yamls_load_as_http_with_distinct_ids(http_dir, syslog_dir):
    from usecase.data_sources_store import compose_data_source_id

    h = _ds_from(_real_doc(http_dir))
    s = _ds_from(_real_doc(syslog_dir))
    assert h.delivery == "http"
    assert s.delivery == "syslog"
    # share pack + dataset, differ only in rule_name -> distinct composite id
    assert (h.pack_name, h.dataset_name) == (s.pack_name, s.dataset_name)
    assert h.rule_name != s.rule_name
    hid = compose_data_source_id(h.pack_name, h.rule_name, h.dataset_name)
    sid = compose_data_source_id(s.pack_name, s.rule_name, s.dataset_name)
    assert hid != sid
    # http sources survive a round trip and validate against the schema
    rendered = h.to_doc()
    assert rendered["delivery"] == "http"
    assert _ds_from(rendered).delivery == "http"
    ok, errors = validate_yaml_doc(rendered)
    assert ok, errors
    assert h.to_catalog_row()["delivery"] == "http"
    assert s.to_catalog_row()["delivery"] == "syslog"


def test_real_loader_serves_http_and_syslog_siblings_separately():
    from usecase.data_sources_yaml_loader import get_data_sources_yaml_loader

    ldr = get_data_sources_yaml_loader()
    http = ldr.get_by_3tuple("Okta", "OktaHttpCollector", "okta_sso_raw")
    sysl = ldr.get_by_3tuple("Okta", "OktaModelingRules", "okta_sso_raw")
    assert http is not None and http.delivery == "http"
    assert sysl is not None and sysl.delivery == "syslog"


# ─── version-store overlay ──────────────────────────────────


def test_version_store_overlays_current(loader, tmp_path):
    """The version store's current snapshot overlays the file source; an
    un-edited source is served unchanged."""
    import yaml

    from usecase import data_source_versions_store as vs
    from usecase.data_sources_store import compose_data_source_id

    _write_yaml(loader.bundle_root / "p" / "data_source.yaml",
                _minimal_doc(id="p", vendor="V", product="Prod"))
    base = loader.get_by_id("p")
    assert base.how_to_use == ""  # file carries none
    cid = compose_data_source_id(base.pack_name, base.rule_name, base.dataset_name)

    store = vs.DataSourceVersionsStore(db_path=tmp_path / "v.db")
    edited = _minimal_doc(id="p", vendor="V", product="Prod")
    edited["how_to_use"] = "OVERLAID FROM STORE"
    store.snapshot(cid, yaml.safe_dump(edited), author="operator")
    vs.set_data_source_versions_store(store)
    try:
        loader.invalidate()
        overlaid = loader.get_by_3tuple(
            base.pack_name, base.rule_name, base.dataset_name
        )
        assert overlaid.how_to_use == "OVERLAID FROM STORE"
        # A second, un-edited source is unaffected.
        _write_yaml(loader.bundle_root / "q" / "data_source.yaml",
                    _minimal_doc(id="q", vendor="W", product="Prod2"))
        loader.invalidate()
        assert loader.get_by_id("q").how_to_use == ""
    finally:
        vs.set_data_source_versions_store(None)
        loader.invalidate()


def test_version_overlay_noop_when_store_unset(loader):
    """No version store wired → loader serves file sources unchanged."""
    from usecase import data_source_versions_store as vs

    vs.set_data_source_versions_store(None)
    _write_yaml(loader.bundle_root / "p" / "data_source.yaml",
                _minimal_doc(id="p", vendor="V", product="Prod"))
    loader.invalidate()
    assert loader.get_by_id("p").how_to_use == ""


# ---------------------------------------------------------------------------
# is_gate must survive the YAML -> payload -> compact chain.
#
# A failure here is invisible: the flag can be present in the YAML and the
# compact projection can know how to keep it, but a payload builder in
# between that copies a FIXED key set silently drops it. The served schema
# would then carry no gate fields, the generator would have nothing to pin,
# and a gated source would emit a random token that ingest discards. Each
# link looks correct in isolation, which is exactly why this needs a test that
# spans the whole chain rather than any single function.
# ---------------------------------------------------------------------------

def test_is_gate_survives_payload_projection_and_compaction():
    import pytest
    # api.data_sources imports fastmcp at module load; skip rather than fail in
    # a dependency-less checkout so this stays a signal, not noise.
    pytest.importorskip("fastmcp")
    from api.data_sources import _compact_schema_payload

    payload = {
        "fields": [
            {"name": "category", "type": "string_short", "is_array": False,
             "is_meta": False, "is_gate": True, "description": "gate",
             "example": "AppServiceHTTPLogs"},
            {"name": "CsHost", "type": "host", "is_array": False,
             "is_meta": False, "is_gate": False, "description": "host",
             "example": "a.example.com"},
        ],
        "logo": "BASE64",
    }
    out = _compact_schema_payload(payload)
    by = {f["name"]: f for f in out["fields"]}

    # the gate field keeps BOTH the flag and the value the generator pins to
    assert by["category"]["is_gate"] is True
    assert by["category"]["example"] == "AppServiceHTTPLogs"

    # a non-gate field still sheds its example, which is the point of compact
    assert "example" not in by["CsHost"]
    assert "is_gate" not in by["CsHost"]

    # the logo is still stripped
    assert "logo" not in out
