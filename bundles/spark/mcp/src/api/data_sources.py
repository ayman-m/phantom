"""Data sources HTTP endpoints.

Operator + agent surface for the data sources store (vendor schemas
extracted from Cortex ModelingRule schema.json files). The extraction
tools read the upstream schemas, the SQLite store persists them, and
this module exposes the REST endpoints plus three MCP tools so the agent
can call data_sources_install / data_sources_list / data_sources_get_schema
from chat.

Endpoints (all require `Authorization: Bearer <MCP_TOKEN>`):

  GET    /api/v1/data-sources                                          → list (with ?filter)
  GET    /api/v1/data-sources/{pack}/{rule}/{dataset}                  → single record
  GET    /api/v1/data-sources/{pack}/{rule}/{dataset}/schema           → single record + fields + xdm mappings
  POST   /api/v1/data-sources/install                                  → install (body: {pack_name, rule_name, dataset_name?})
  DELETE /api/v1/data-sources/{pack}/{rule}/{dataset}                  → uninstall

The composite path uses real slashes rather than url-encoded ids because
Starlette routes natively handle multi-segment path parameters and the
operator-facing reality is "FortiGate / FortiGate_1_3 / fortinet_fortigate_raw"
matches the URL one-to-one — no encoding indirection.

Routing order: `/data-sources/install` is registered BEFORE
`/data-sources/{pack}/{rule}/{dataset}` so the literal "install" segment
doesn't get swallowed as a pack_name. Starlette matches in registration
order.

# How install works server-side

The POST handler does the extraction itself (no two-step round-trip
required from the client) by dynamically loading the cortex-content
connector module from `/app/bundle/connectors/cortex-content/src/`.
The unit tests use the same pattern. The connector's
public functions (`cortex_extract_vendor_schema`,
`cortex_extract_vendor_logo`, `cortex_list_modeling_rules`) don't
require a per-instance container — they hit GitHub's anonymous API
directly via the connector's GitHubClient. So the server can call
them in-process at install time without spinning a connector container
or requiring the operator to pre-install the cortex-content connector
via the marketplace.

If `dataset_name` is provided in the install request, only that
dataset within the rule is installed. If omitted, ALL datasets the
modeling rule defines are installed in one shot (most modeling rules
have a single dataset, but some have multiple).

# Boundary

`POST /install` + `DELETE` are CATALOG mutations — per CLAUDE.md §
Catalog boundary ≠ credential boundary, agent IS allowed to
mutate via the matching MCP tools. The three MCP tools registered at
the bottom of this module (data_sources_install / data_sources_list /
data_sources_get_schema) wrap the same handlers so chat-driven
installs behave identically to REST-driven installs.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from api.auth import require_bearer
from usecase.audit_log import (
    SqliteAuditLog,
    audit_log,
    reset_current_actor,
    set_current_actor,
)
from usecase.data_sources_store import (
    DataSource,
    DataSourceField,
    DataSourcesStore,
    compose_data_source_id,
)
from usecase.data_sources_similarity import find_similar_vendors
from usecase.data_sources_yaml_loader import (
    get_data_sources_yaml_loader,
)

logger = logging.getLogger("Phantom MCP")


# ─── cortex-content connector — dynamic loading ────────────────────
#
# The cortex-content connector lives at
# /app/bundle/connectors/cortex-content/src/ inside the container, OR
# at bundles/spark/connectors/cortex-content/src/ in dev. Its module
# directory name contains a hyphen ("cortex-content"), so it can't be
# imported with a normal `from connectors.cortex-content...` statement.
# Instead we lazy-load via importlib.util under a synthetic package
# name, the same way the unit tests do.
#
# The cortex-content connector's public extraction functions are
# stateless + idempotent + don't require a per-instance container,
# so server-side calls work even when the operator hasn't yet
# installed the cortex-content connector via the marketplace.


_cortex_content_module: Any | None = None
_CORTEX_CONTENT_PKG = "_phantom_data_sources_cortex_content"


def _resolve_cortex_content_src() -> Path:
    """Find the cortex-content connector's src/ directory.

    Tries the container path first (production), then the source-tree
    layout (local dev / tests). Raises FileNotFoundError if neither
    exists, which the install handler surfaces as a clean error
    envelope rather than a 500."""
    candidates = [
        Path("/app/bundle/connectors/cortex-content/src"),
        # From mcp/src/api/data_sources.py walk up to repo root then
        # back down: ../../../connectors/cortex-content/src
        Path(__file__).resolve().parents[2]
        / "connectors"
        / "cortex-content"
        / "src",
        # Dev workspace alternative
        Path(__file__).resolve().parents[4]
        / "connectors"
        / "cortex-content"
        / "src",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    raise FileNotFoundError(
        "cortex-content connector source not found in "
        f"{[str(c) for c in candidates]}"
    )


def _load_cortex_content() -> Any:
    """Lazy-load the cortex-content connector module. Idempotent."""
    global _cortex_content_module
    if _cortex_content_module is not None:
        return _cortex_content_module

    src = _resolve_cortex_content_src()

    pkg = sys.modules.get(_CORTEX_CONTENT_PKG)
    if pkg is None:
        pkg = types.ModuleType(_CORTEX_CONTENT_PKG)
        pkg.__path__ = [str(src)]  # type: ignore[attr-defined]
        sys.modules[_CORTEX_CONTENT_PKG] = pkg

    gh_key = f"{_CORTEX_CONTENT_PKG}._github_client"
    if gh_key not in sys.modules:
        spec_gh = importlib.util.spec_from_file_location(
            gh_key, src / "_github_client.py"
        )
        gh = importlib.util.module_from_spec(spec_gh)
        sys.modules[gh_key] = gh
        spec_gh.loader.exec_module(gh)

    cm_key = f"{_CORTEX_CONTENT_PKG}.connector"
    if cm_key not in sys.modules:
        spec_c = importlib.util.spec_from_file_location(
            cm_key, src / "connector.py"
        )
        cm = importlib.util.module_from_spec(spec_c)
        sys.modules[cm_key] = cm
        spec_c.loader.exec_module(cm)

    _cortex_content_module = sys.modules[cm_key]
    return _cortex_content_module


# ─── Install path: extract → compose → persist ─────────────────────


def _field_from_yaml_record(
    f: dict[str, Any], *, is_meta_default: bool = False,
) -> DataSourceField:
    """Turn one YAML `fields[]` record into the row the store persists.

    The only place a YAML field becomes a `DataSourceField`, so no install
    path can drop an attribute again. Two once did: the YAML install path
    omitted `example`, and the cortex path's YAML branch omitted `is_gate`
    and `enum_values`. A gate field's example is the only value its rule
    accepts, so a freshly installed gated source served an empty gate until
    the next boot's backfill filled it in.

    Values are normalised exactly as `backfill_field_metadata_from_yaml`
    writes them, so an install and a backfill produce identical rows.
    """
    example = f.get("example")
    return DataSourceField(
        name=f["name"],
        type=f.get("type"),
        is_array=bool(f.get("is_array", False)),
        is_meta=bool(f.get("is_meta", is_meta_default)),
        is_gate=bool(f.get("is_gate", False)),
        enum_values=(list(f["enum_values"]) if f.get("enum_values") else None),
        description=(f.get("description") or "").strip(),
        example="" if example is None else str(example),
    )


def _compose_from_user_yaml(
    yaml_ds: Any,  # YamlDataSource (avoid forward-ref dance)
    installed_by: str = "user:operator",
) -> tuple[list[tuple[DataSource, list[DataSourceField]]], dict[str, Any]]:
    """Build install records from a YAML data source.

    Handles both user-uploaded packs (which don't live in the upstream
    catalog) and BUNDLED YAMLs with populated `fields[]`. The YAML's
    `fields[]` is the source of truth in both cases; we lift them into DataSourceField
    rows. logo_url routing depends on origin: user→inline endpoint,
    bundle→vendor_map lookup. Caller decides which path applies.

    Returns the same (composed, meta) shape as
    `_extract_and_compose_data_sources` so the install handlers can
    treat both paths identically downstream.
    """
    is_user = yaml_ds.origin == "user"
    ds_id = compose_data_source_id(
        yaml_ds.pack_name, yaml_ds.rule_name, yaml_ds.dataset_name,
    )
    non_meta_count = len([f for f in yaml_ds.fields if not f.get("is_meta", False)])
    # Logo route: user packs → inline-logo endpoint that streams the
    # yaml's base64 bytes; bundle packs → vendor_map.yaml lookup by pack_name.
    if is_user:
        logo_url: str | None = (
            f"/api/agent/data-sources/user/{yaml_ds.id}/logo"
            if yaml_ds.logo else None
        )
    else:
        logo_url = f"/api/agent/data-sources/logo/{yaml_ds.pack_name}"
    ds = DataSource(
        id=ds_id,
        pack_name=yaml_ds.pack_name,
        rule_name=yaml_ds.rule_name,
        dataset_name=yaml_ds.dataset_name,
        pack_version=yaml_ds.version,
        is_rawlog_only=bool(yaml_ds.is_rawlog_only),
        field_count=len(yaml_ds.fields),
        non_meta_field_count=non_meta_count,
        supported_modules=["xsiam"],  # Bundle packs default xsiam; the catalog
                                      # row keeps the cortex-content-derived
                                      # `supported_modules` separately.
        pack_description=yaml_ds.description,
        logo_url=logo_url,
        logo_type=(yaml_ds.logo or {}).get("mime_type", "").replace("image/", "") or None,
        installed_by=installed_by,
    )
    # Dedup by field name. The YAML schema doesn't enforce unique names,
    # and a duplicate would fail install at the SQLite UNIQUE constraint.
    # Defensive: first occurrence wins. The validator catches this at
    # gate time so the bundled YAMLs stay clean, but the runtime dedup
    # protects operator-uploaded YAMLs too. The YAML `description` is
    # carried into each field record.
    fields_list: list[DataSourceField] = []
    seen_names: set[str] = set()
    for f in yaml_ds.fields:
        name = f.get("name")
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        fields_list.append(_field_from_yaml_record(f))
    meta = {
        "pack_version": yaml_ds.version,
        "pack_description": yaml_ds.description,
        "supported_modules": ["xsiam"],
        "logo_url": ds.logo_url,
        "datasets_in_rule": 1,
        "datasets_installed": 1,
        "origin": yaml_ds.origin,
    }
    return [(ds, fields_list)], meta


def _comparable_fields(fields: list[DataSourceField]) -> dict[str, tuple]:
    """Field rows reduced to what a refresh compares. Enum values are compared
    as strings: the store round-trips them through JSON and returns str."""
    return {
        f.name: (
            f.type, bool(f.is_array), bool(f.is_meta), bool(f.is_gate),
            tuple(str(v) for v in (f.enum_values or ())),
            f.description or "", f.example or "",
        )
        for f in fields
    }


def refresh_installed_from_bundle() -> dict[str, Any]:
    """Sync installed data sources to their effective catalog schema at boot.

    The invariant: an installed source's stored schema equals its *effective*
    catalog YAML — the bundled `data_source.yaml`, overlaid with any operator
    edit (the version store's current version) — unless it is pinned.

    Installing a source copies its schema into data_sources.db, and nothing
    reconciled it afterwards. Upgrades keep that volume, so a corrected bundled
    schema never reached an already-installed source, and an operator edit
    reached the catalog overlay but not the installed rows the agent
    generates from.

    Runs once at boot, after the store, the field backfill and the version
    store are wired. The YAML loader's `list_all()` is overlay-aware, so for an
    edited source it already returns the edited effective YAML. For every
    installed bundled source it composes the rows `data_sources_install` would
    write, via the same `_compose_from_user_yaml`, and compares them with the
    stored rows:

      * pinned (is_pinned=1): skipped and reported. A pin is an explicit choice
        to stay on a specific version; automatic sync leaves it alone.
      * otherwise, on any difference: field rows replaced in place. This applies
        both a newer bundle (unedited source) and a pending operator edit (edited
        source). installed_at, installed_by and the pin are kept — a sync is not
        a reinstall.

    Records one audit event (visible in /observability/events) when anything was
    synced, skipped or failed; a boot with nothing to do records none. Never
    raises: one bad source is reported and the rest still sync.

    A source edited via `data_sources_edit` is also synced immediately, at edit
    time, by `_resync_installed_schema`; this boot pass covers sources edited
    before that path existed. An edit's v1 "bundle-baseline" is frozen at first
    edit, so an edited source does not track later bundle changes (roll back to
    pick up the current bundle first).
    """
    from usecase.audit_log import audit_log
    from usecase.data_sources_store import get_data_sources_store

    summary: dict[str, Any] = {
        "refreshed": [], "skipped_pinned": [], "failed": [], "unchanged": 0,
    }
    store = get_data_sources_store()
    if store is None:
        return summary
    try:
        bundled = {
            compose_data_source_id(y.pack_name, y.rule_name, y.dataset_name): y
            for y in get_data_sources_yaml_loader().list_all()
            if y.origin == "bundle"
        }
    except Exception:  # noqa: BLE001
        logger.exception("data source sync: could not load the catalog YAML")
        return summary

    for installed in store.list():
        yaml_ds = bundled.get(installed.id)
        if yaml_ds is None:
            continue  # not a bundled source (cortex-extracted or user upload)
        try:
            composed, _meta = _compose_from_user_yaml(
                yaml_ds, installed_by=installed.installed_by or "agent",
            )
            ds, fields = composed[0]
            current = store.get_with_schema(installed.id)
            stored = _comparable_fields(current.fields if current else [])
            wanted = _comparable_fields(fields)
            if stored == wanted:
                summary["unchanged"] += 1
                continue
            if installed.is_pinned:
                summary["skipped_pinned"].append(installed.id)
                logger.warning(
                    "data source %s: catalog schema differs from the installed "
                    "one, but the source is pinned to %s — not synced",
                    installed.id, installed.pinned_version,
                )
                continue
            store.replace_schema(ds, fields)
            summary["refreshed"].append(installed.id)
            changed = sum(1 for n in wanted.keys() & stored.keys() if wanted[n] != stored[n])
            logger.info(
                "data source %s synced to the catalog schema: +%d / -%d fields, %d changed",
                installed.id, len(wanted.keys() - stored.keys()),
                len(stored.keys() - wanted.keys()), changed,
            )
        except Exception:  # noqa: BLE001
            summary["failed"].append(installed.id)
            logger.exception("data source %s: sync to the catalog schema failed", installed.id)

    if any(summary[k] for k in ("refreshed", "skipped_pinned", "failed")):
        audit = audit_log()
        if audit is not None:
            audit.record(
                "data_sources_refreshed",
                target="data-sources",
                status="failure" if summary["failed"] else "success",
                actor="system",
                trigger="boot",
                metadata=summary,
            )
    return summary


def _yaml_field_records(
    pack_name: str, rule_name: str, dataset_name: str,
) -> list[dict[str, Any]] | None:
    """Look up the bundled YAML for this pack/rule/dataset
    triple and return its full `fields[]` list (each entry: name, type,
    is_array, is_meta, description, example, …).

    Returns None when no YAML exists (caller falls back to cortex
    schema). Returns the full list — including dotted-path leaves like
    `audit.user.email` — when the YAML is present. The YAML is the
    canonical wire-format spec for bundled packs; the
    cortex schema.json is incomplete (top-level columns as strings, no
    leaves, no examples) and must not win when both are present.

    YAML wins for bundled packs: overlaying only descriptions on top of
    cortex-derived fields would drop composite types (`audit` would come
    back as `string` because cortex says so) and never surface examples
    or leaves.
    """
    try:
        from usecase.data_sources_yaml_loader import (
            get_data_sources_yaml_loader,
        )
        loader = get_data_sources_yaml_loader()
        yaml_ds = loader.get_by_3tuple(pack_name, rule_name, dataset_name)
        if yaml_ds is None:
            return None
        # yaml_ds.fields is the raw list from the YAML file. Return a
        # defensive copy so callers can't mutate the loader's cache.
        return [dict(f) for f in (yaml_ds.fields or []) if isinstance(f, dict)]
    except Exception as exc:  # noqa: BLE001
        logger.debug("yaml field-record lookup failed: %s", exc)
        return None


async def _extract_and_compose_data_sources(
    pack_name: str,
    rule_name: str,
    dataset_name: str | None = None,
    installed_by: str = "user:operator",
) -> tuple[list[tuple[DataSource, list[DataSourceField]]], dict[str, Any]]:
    """Run the extraction + compose DataSource objects.

    Returns (composed, meta). `composed` is a list of (DataSource, fields)
    tuples — one entry per dataset in the modeling rule (or just the one
    matching `dataset_name` if provided). `meta` carries info useful for
    the response (pack_metadata, logo_info) so callers can render warning
    messages when the install is partial / degenerate.

    Raises ValueError on missing pack/rule/dataset; KeyError on extraction
    error. Callers translate to 4xx/5xx as appropriate.
    """
    cortex = _load_cortex_content()

    # Pack metadata for description, currentVersion, supportedModules
    client = cortex._get_client()
    try:
        pack_meta = client.get_file_json(
            f"Packs/{pack_name}/pack_metadata.json"
        )
    except Exception as exc:
        raise ValueError(
            f"pack '{pack_name}' has no pack_metadata.json: {exc}"
        ) from exc
    if not isinstance(pack_meta, dict):
        pack_meta = {}

    pack_version = pack_meta.get("currentVersion")
    pack_description = pack_meta.get("description")
    supported_modules = pack_meta.get("supportedModules") or []
    if not isinstance(supported_modules, list):
        supported_modules = []

    # Vendor logo (best-effort — None is acceptable)
    logo_url: str | None = None
    logo_type: str | None = None
    try:
        logo_resp = await cortex.cortex_extract_vendor_logo(pack_name=pack_name)
        if isinstance(logo_resp, dict) and logo_resp.get("ok"):
            logo_url = logo_resp.get("logo_url")
            logo_type = logo_resp.get("logo_type")
    except Exception as exc:  # noqa: BLE001
        logger.debug("logo extraction failed for %s: %s", pack_name, exc)

    # Schema extraction
    schema_resp = await cortex.cortex_extract_vendor_schema(
        pack_name=pack_name, rule_name=rule_name
    )
    if not isinstance(schema_resp, dict) or not schema_resp.get("ok"):
        msg = (
            schema_resp.get("error", "unknown error")
            if isinstance(schema_resp, dict)
            else "non-dict response"
        )
        raise ValueError(
            f"schema extraction failed for {pack_name}/{rule_name}: {msg}"
        )

    all_datasets = schema_resp.get("datasets", {})
    if not all_datasets:
        raise ValueError(
            f"{pack_name}/{rule_name} has no datasets in its schema.json"
        )

    # Filter to requested dataset if specified
    if dataset_name is not None:
        if dataset_name not in all_datasets:
            raise ValueError(
                f"dataset '{dataset_name}' not found in "
                f"{pack_name}/{rule_name}; available: {list(all_datasets)}"
            )
        target_datasets = {dataset_name: all_datasets[dataset_name]}
    else:
        target_datasets = all_datasets

    composed: list[tuple[DataSource, list[DataSourceField]]] = []
    for ds_name, ds_info in target_datasets.items():
        ds_id = compose_data_source_id(pack_name, rule_name, ds_name)
        ds = DataSource(
            id=ds_id,
            pack_name=pack_name,
            rule_name=rule_name,
            dataset_name=ds_name,
            pack_version=pack_version,
            is_rawlog_only=bool(ds_info.get("is_rawlog_only", False)),
            field_count=int(ds_info.get("field_count", 0)),
            non_meta_field_count=int(ds_info.get("non_meta_field_count", 0)),
            supported_modules=supported_modules,
            pack_description=pack_description,
            logo_url=logo_url,
            logo_type=logo_type,
            installed_by=installed_by,
        )
        # YAML-canonical for bundled packs. The bundled
        # data_source.yaml is the authoritative wire-format spec: full
        # field record (name, type incl. `json`, is_array, description,
        # example) PLUS dotted-path leaves the cortex schema doesn't
        # know about. Cortex schema.json is the fallback only when no
        # YAML exists. (Overlaying only descriptions on cortex-derived
        # fields would drop composite types, examples and every leaf.)
        meta_fields = getattr(cortex, "_META_SCHEMA_FIELDS", set())
        yaml_records = _yaml_field_records(pack_name, rule_name, ds_name)
        if yaml_records is not None:
            # Path A — YAML wins.
            fields_list = [
                # is_meta from YAML when set; fall back to the cortex
                # classifier so legacy YAMLs without is_meta still get
                # meta-fields tagged correctly.
                _field_from_yaml_record(
                    f, is_meta_default=f["name"] in meta_fields,
                )
                for f in yaml_records
                if "name" in f
            ]
        else:
            # Path B — fall back to cortex schema (packs without a YAML).
            fields_list = [
                DataSourceField(
                    name=f["name"],
                    type=f.get("type"),
                    is_array=bool(f.get("is_array", False)),
                    is_meta=(f["name"] in meta_fields),
                    description="",
                    example="",
                )
                for f in ds_info.get("fields", [])
            ]
        composed.append((ds, fields_list))

    meta = {
        "pack_version": pack_version,
        "pack_description": pack_description,
        "supported_modules": supported_modules,
        "logo_url": logo_url,
        "datasets_in_rule": len(all_datasets),
        "datasets_installed": len(target_datasets),
    }
    return composed, meta


def _live_field_counts_by_id() -> dict[str, tuple[int, int]]:
    """Map COMPOSITE data-source id ("pack/rule/dataset", via
    compose_data_source_id) → (field_count, non_meta_field_count) read live
    from the YAML loader (the source of truth).

    The installed store keeps a snapshot of these counts stamped at install
    time; it drifts when the bundled YAML is enriched on a later image. The
    list endpoint overlays this live map so the InstalledCard badge matches
    the drawer + Browse. Keyed by the composite id so it matches the store's
    `r.id` — the loader's `y.id` is the SHORT id ("ServiceNow") and never
    matched, which is the keying bug this map exists to avoid.
    """
    loader = get_data_sources_yaml_loader()
    out: dict[str, tuple[int, int]] = {}
    for y in loader.list_all():
        cid = compose_data_source_id(y.pack_name, y.rule_name, y.dataset_name)
        out[cid] = (
            len(y.fields),
            sum(1 for f in y.fields
                if isinstance(f, dict) and not f.get("is_meta", False)),
        )
    return out


def _sync_field_counts_to_fields(payload: dict) -> None:
    """Recompute `field_count` + `non_meta_field_count` from the
    payload's OWN `fields[]` array, so the drawer's stat tiles always match
    the field table rendered below them (and the catalog badge).

    The schema endpoint builds `fields[]` from the current source, but the
    scalar counts would otherwise come from a different, stale source: the SQLite
    `data_sources.field_count` column (install-time snapshot) on the installed
    path, and the cortex-baked `ds_info` count on the preview path. So the tile
    showed e.g. 25 while the table listed 45. Deriving the scalars from the
    very array we're returning makes tile == table == catalog, unconditionally.
    """
    flds = payload.get("fields") or []
    payload["field_count"] = len(flds)
    payload["non_meta_field_count"] = sum(
        1 for f in flds if isinstance(f, dict) and not f.get("is_meta", False)
    )


def _resync_installed_schema(ds_id: str) -> bool:
    """Sync an installed source's stored schema to the effective catalog YAML.

    `data_sources_get_schema` serves an installed source from data_sources.db,
    not from the YAML, so an operator edit (which writes only the version-store
    overlay) never reached the schema the agent generates from. Called after an
    edit or a rollback: if the source is installed, re-compose its rows from the
    now-current effective YAML (the loader is overlay-aware and has been
    invalidated by the caller) and replace them in place.

    An explicit edit outranks a pin, so this syncs regardless of is_pinned — the
    pin only gates the automatic boot sync. No-op (returns False) when the source
    is not installed or the store is unwired.
    """
    from usecase.data_sources_store import get_data_sources_store

    store = get_data_sources_store()
    if store is None or not store.is_installed(ds_id):
        return False
    parts = ds_id.split("/")
    if len(parts) != 3:
        return False
    yaml_ds = get_data_sources_yaml_loader().get_by_3tuple(*parts)
    if yaml_ds is None:
        return False
    installed = store.get(ds_id)
    composed, _meta = _compose_from_user_yaml(
        yaml_ds, installed_by=(installed.installed_by if installed else "agent") or "agent",
    )
    ds, fields = composed[0]
    return store.replace_schema(ds, fields)


def _apply_edit(
    pack_name: str,
    rule_name: str,
    dataset_name: str,
    *,
    how_to_use: str | None = None,
    fields: list[dict] | None = None,
    note: str | None = None,
    author: str,
) -> dict:
    """Edit a data source, creating a version.

    Shared by the REST edit endpoint (author="operator") and the
    `data_sources_edit` agent tool (author="agent"). Composes the patch onto
    the *current* content (the overlay-current if already edited, else the
    file), validates against data_source.schema.json + field-name uniqueness,
    snapshots the original as v1 (bundle-baseline) on first edit, then the
    edit as the new current. Returns {"ok", "version", "data_source_id"} or
    {"ok": False, "error"}. No file on disk is mutated.
    """
    import yaml as _yaml

    from usecase.data_source_versions_store import get_data_source_versions_store
    from usecase.data_sources_yaml_loader import (
        get_data_sources_yaml_loader,
        validate_yaml_doc,
    )

    store = get_data_source_versions_store()
    if store is None:
        return {"ok": False, "error": "version store not initialized"}
    loader = get_data_sources_yaml_loader()
    ds_id = compose_data_source_id(pack_name, rule_name, dataset_name)
    cur = loader.get_by_3tuple(pack_name, rule_name, dataset_name)
    if cur is None:
        return {"ok": False, "error": f"data source not found: {ds_id}"}

    original_doc = cur.to_doc()   # pre-edit state (fresh dict)
    doc = cur.to_doc()            # the dict we patch
    if how_to_use is not None:
        doc["how_to_use"] = how_to_use
    if fields is not None:
        if not isinstance(fields, list) or not all(isinstance(f, dict) for f in fields):
            return {"ok": False, "error": "fields must be a list of objects"}
        names = [f.get("name") for f in fields]
        if any(not n for n in names):
            return {"ok": False, "error": "every field needs a non-empty name"}
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            return {"ok": False, "error": f"duplicate field names: {dupes}"}
        doc["fields"] = fields

    ok, errors = validate_yaml_doc(doc)
    if not ok:
        return {"ok": False, "error": f"schema validation failed: {errors[0] if errors else 'invalid'}"}

    def _dump(d: dict) -> str:
        return _yaml.safe_dump(
            d, sort_keys=False, default_flow_style=False, allow_unicode=True, width=100
        )

    if not store.has_versions(ds_id):
        store.snapshot(ds_id, _dump(original_doc), author="bundle-baseline", note="original")
    new = store.snapshot(ds_id, _dump(doc), author=author, note=note)
    loader.invalidate()
    # The edit reaches only the catalog overlay above; push it into the
    # installed store too, so the schema the agent generates from matches.
    synced = _resync_installed_schema(ds_id)
    return {
        "ok": True, "version": new["version"], "data_source_id": ds_id,
        "installed_schema_synced": synced,
    }


def _apply_rollback(
    pack_name: str,
    rule_name: str,
    dataset_name: str,
    *,
    version: int,
    author: str,
) -> dict:
    """Roll a data source back to a prior version.

    Non-destructive: copies version `version`'s snapshot forward as a new
    current version; the intervening versions stay in history (roll-forward
    always works). Shared by the REST rollback route (author="operator") and
    the `data_sources_rollback` agent tool (author="agent"). Returns
    {"ok", "version", "data_source_id"} or {"ok": False, "error"}.
    """
    from usecase.data_source_versions_store import get_data_source_versions_store
    from usecase.data_sources_yaml_loader import get_data_sources_yaml_loader

    store = get_data_source_versions_store()
    if store is None:
        return {"ok": False, "error": "version store not initialized"}
    ds_id = compose_data_source_id(pack_name, rule_name, dataset_name)
    if not store.has_versions(ds_id):
        return {"ok": False, "error": f"no versions to roll back for {ds_id}"}
    try:
        new = store.rollback(ds_id, int(version), author=author)
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}
    get_data_sources_yaml_loader().invalidate()
    # A rollback changes the effective YAML; sync the installed store too.
    synced = _resync_installed_schema(ds_id)
    return {
        "ok": True, "version": new["version"], "data_source_id": ds_id,
        "installed_schema_synced": synced,
    }


def _resolve_export_content(
    pack_name: str,
    rule_name: str,
    dataset_name: str,
    *,
    version: int | str | None = None,
) -> tuple[str | None, str, str | None]:
    """Resolve the YAML content to export, version-aware.

    Returns (content, filename, error):
      • version given → that version's yaml_snapshot verbatim, filename
        "{dataset}.v{n}.yaml". Unknown version → (None, "", "version_not_found").
      • version None + the source has edit history → the CURRENT version's
        snapshot (matches the drawer's overlay), filename "{dataset}.yaml".
      • version None + never edited → the pristine file on disk (today's
        behavior), filename "{dataset}.yaml". Missing → (None, "", "not_found");
        read error → (None, "", "read_failed").
    """
    from usecase.data_source_versions_store import get_data_source_versions_store
    from usecase.data_sources_yaml_loader import get_data_sources_yaml_loader

    ds_id = compose_data_source_id(pack_name, rule_name, dataset_name)
    store = get_data_source_versions_store()

    if version is not None:
        try:
            vnum = int(version)
        except (TypeError, ValueError):
            return None, "", "version_not_found"
        row = store.get_version(ds_id, vnum) if store is not None else None
        if row is None:
            return None, "", "version_not_found"
        return row["yaml_snapshot"], f"{dataset_name}.v{vnum}.yaml", None

    # Default = current. If the source has been edited, the current version
    # snapshot IS the canonical content (the overlay the drawer shows).
    if store is not None and store.has_versions(ds_id):
        cur = store.get_current(ds_id)
        if cur is not None:
            return cur["yaml_snapshot"], f"{dataset_name}.yaml", None

    # Never edited → read the pristine file on disk.
    try:
        loader = get_data_sources_yaml_loader()
        yaml_ds = loader.get_by_3tuple(pack_name, rule_name, dataset_name)
    except Exception:  # noqa: BLE001
        logger.exception("export lookup failed for %s/%s/%s", pack_name, rule_name, dataset_name)
        return None, "", "read_failed"
    if yaml_ds is None or yaml_ds._source_path is None:
        return None, "", "not_found"
    try:
        return yaml_ds._source_path.read_text(encoding="utf-8"), f"{dataset_name}.yaml", None
    except Exception:  # noqa: BLE001
        logger.exception("export read failed for %s", yaml_ds._source_path)
        return None, "", "read_failed"


def _yaml_ds_to_schema_payload(yaml_ds, ds_id: str, *, is_preview: bool) -> dict:
    """Build a drawer/schema payload from a bundled/user YamlDataSource.

    The bundled YAML is the source of truth (same as the catalog), so the
    schema surfaces can serve ANY catalog source — including a 2nd dataset
    under one pack+rule that cortex-content's schema.json doesn't enumerate
    (e.g. okta_sso_raw). Mirrors the catalog-row columns + adds the rendered
    `fields[]`, `how_to_use`, and the composite id (the surfaces key on the
    composite, while the YAML's `id` is the short pack slug).
    """
    row = yaml_ds.to_catalog_row(installed=not is_preview)
    fields = [
        {
            "name": f["name"],
            "type": f.get("type"),
            "is_array": bool(f.get("is_array", False)),
            "is_meta": bool(f.get("is_meta", False)),
            "is_gate": bool(f.get("is_gate", False)),
            "enum_values": (f.get("enum_values") or None),
            "description": (f.get("description") or "").strip(),
            "example": "" if f.get("example") is None else str(f.get("example")),
        }
        for f in (yaml_ds.fields or [])
        if isinstance(f, dict) and f.get("name")
    ]
    row.update(
        {
            "id": ds_id,
            "pack_version": yaml_ds.version,
            "how_to_use": yaml_ds.how_to_use,
            "fields": fields,
            "is_preview": is_preview,
            # Explicit (also present via to_catalog_row): "syslog" | "http".
            "delivery": yaml_ds.delivery,
        }
    )
    return row


def _enrich_with_vendor_meta(payload: dict, ds_id: str) -> None:
    """Populate `vendor_key`, `vendor_display_name`,
    `vendor_logo_url`, and `use_cases` on a payload dict, sourced from
    the YAML loader. Also sets `origin` so the UI's
    DetailDrawer can render an Edit button for user uploads. Mutates
    the dict in place. No-op if the YAML for the given ds_id can't be
    resolved (defensive — preserves the payload's existing logo_url).
    """
    try:
        loader = get_data_sources_yaml_loader()
        # Look up via the 3-tuple (pack/rule/dataset), parsed from the
        # canonical ds_id format. `get_by_id(ds_id)` keys on the YAML's
        # `id:` field (often just the pack short name like "ServiceNow"),
        # so it would never match the `compose_data_source_id` output
        # ("pack/rule/dataset") the schema endpoint passes, and the
        # early-return below would skip `how_to_use` entirely.
        parts = ds_id.split("/", 2)
        if len(parts) == 3:
            ds = loader.get_by_3tuple(parts[0], parts[1], parts[2])
        else:
            ds = loader.get_by_id(ds_id)  # backward-compat for callers
                                          # that pass the YAML's short id
        if ds is None:
            payload.setdefault("vendor_logo_url", payload.get("logo_url"))
            payload.setdefault("use_cases", [])
            payload.setdefault("origin", "bundle")
            payload.setdefault("delivery", "syslog")
            payload.setdefault("how_to_use", "")  # empty string, not
                                                  # `undefined`, for the UI.
            return
        from usecase.data_sources_yaml_loader import _slugify
        vk = _slugify(ds.vendor).lower()
        # vendor_logo_url: pick the first YAML of this vendor that
        # carries an inline logo, mirroring the VendorCard logic.
        # Cheaper than re-scanning all_yamls — the loader's id-index
        # cache makes this fast.
        vendor_logo_url = ds._compute_logo_url()  # noqa: SLF001
        if vendor_logo_url is None:
            # Fall back to scanning siblings of the same vendor.
            for other in loader.list_all():
                if _slugify(other.vendor).lower() == vk and other.logo:
                    vendor_logo_url = other._compute_logo_url()  # noqa: SLF001
                    if vendor_logo_url:
                        break
        payload["vendor_key"] = vk
        payload["vendor_display_name"] = ds.vendor
        payload["vendor_logo_url"] = vendor_logo_url or payload.get("logo_url")
        payload["use_cases"] = list(ds.use_cases or [])
        # Origin lookup for the UI Edit affordance.
        payload["origin"] = ds.origin
        # Also surface the YAML id so the UI Edit handler
        # can call PUT /user/{id} without re-deriving it.
        payload["id"] = ds.id
        # Overlay operator-facing simulation guidance from
        # the YAML. Bundled YAMLs carry this for vendor-specific quirks
        # (multi-dataset handling, CEF-wrap notes, MTU/MR ceiling, MR
        # filter requirements). The data_sources_store column does NOT
        # carry this — install-time tables track schemas, not docs.
        # YAML is the canonical source of operator simulation guidance
        # (same YAML-canonical pattern as fields[]).
        payload["how_to_use"] = ds.how_to_use or ""
        # delivery lives only in the YAML (the install store has no
        # column for it), so overlay it here for the installed-drawer path.
        payload["delivery"] = ds.delivery
    except Exception as exc:
        logger.debug("vendor-meta enrichment failed for %s: %s", ds_id, exc)
        payload.setdefault("vendor_logo_url", payload.get("logo_url"))
        payload.setdefault("use_cases", [])
        payload.setdefault("origin", "bundle")
        payload.setdefault("how_to_use", "")
        payload.setdefault("delivery", "syslog")


# ─── REST handler registration ─────────────────────────────────────


def register_data_sources_routes(
    mcp: FastMCP,
    store: DataSourcesStore,
    audit: SqliteAuditLog,
) -> None:
    """Register /api/v1/data-sources/* routes.

    Order matters: register literal `/install` before the
    multi-segment {pack}/{rule}/{dataset} catch-all so install isn't
    matched as a pack_name."""

    @mcp.custom_route(
        "/api/v1/data-sources/logo/{pack_name}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_vendor_logo(request: Request):
        """Serve a theme-aware vendor logo as SVG.

        Resolution path:
          1. Look up pack_name in baked/vendor_map.yaml → vendor_key.
          2. Serve baked/vendor_svgs/<vendor_key>_<theme>.svg.
          3. Fallback chain (for backwards compat during R1 transition):
             - Pack's own <int>_image_<theme>.svg (per-pack override)
             - Legacy <int>_dark.svg or <int>_image.png if vendor_map missing
             - Author_image.png

        Query params:
          ?theme=light  (default; light-theme variant — brand color on light bg)
          ?theme=dark   (dark-theme variant — lightened/inverted)

        Returns 404 when neither pack nor logo is found.
        """
        from starlette.responses import FileResponse

        if (resp := require_bearer(request)) is not None:
            return resp
        pack_name = request.path_params["pack_name"]
        # Defensive — refuse path traversal
        if "/" in pack_name or ".." in pack_name or pack_name.startswith("."):
            return JSONResponse({"error": "invalid pack_name"}, status_code=400)

        theme = request.query_params.get("theme", "light")
        if theme not in ("light", "dark"):
            return JSONResponse({"error": "theme must be 'light' or 'dark'"}, status_code=400)

        try:
            cortex = _load_cortex_content()
        except FileNotFoundError as exc:
            return JSONResponse(
                {"error": f"cortex-content connector source missing: {exc}"},
                status_code=500,
            )
        # Resolve the baked root via the connector's helper
        baked_mod_name = cortex.__name__.rsplit(".", 1)[0] + "._baked_client"
        baked_mod = sys.modules.get(baked_mod_name)
        if baked_mod is None:
            spec = importlib.util.spec_from_file_location(
                baked_mod_name,
                str(_resolve_cortex_content_src() / "_baked_client.py"),
            )
            baked_mod = importlib.util.module_from_spec(spec)
            sys.modules[baked_mod_name] = baked_mod
            spec.loader.exec_module(baked_mod)
        if not baked_mod.is_baked_available():
            return JSONResponse(
                {"error": "baked catalog not available; rebuild image with `python3 scripts/refresh_cortex_baked_catalog.py`"},
                status_code=503,
            )
        root = baked_mod.baked_root_path()
        pack_dir = root / "Packs" / pack_name
        if not pack_dir.is_dir():
            return JSONResponse(
                {"error": f"pack '{pack_name}' not in baked catalog"},
                status_code=404,
            )

        cache_headers = {"Cache-Control": "public, max-age=86400, immutable"}

        # Priority 1 — per-pack override (R3+ operator uploads land here)
        integrations_dir = pack_dir / "Integrations"
        if integrations_dir.is_dir():
            for int_subdir in sorted(integrations_dir.iterdir()):
                if not int_subdir.is_dir():
                    continue
                int_name = int_subdir.name
                override = int_subdir / f"{int_name}_image_{theme}.svg"
                if override.is_file():
                    return FileResponse(
                        path=str(override),
                        media_type="image/svg+xml",
                        headers=cache_headers,
                    )

        # Priority 2 — vendor_map.yaml resolution (the main path)
        vendor_map_path = root / "vendor_map.yaml"
        if vendor_map_path.is_file():
            try:
                import yaml
                vmap = yaml.safe_load(vendor_map_path.read_text())
                # Find which vendor owns this pack
                for vk, info in (vmap.get("vendors") or {}).items():
                    if pack_name in (info.get("packs") or []):
                        vendor_svg = root / "vendor_svgs" / f"{vk}_{theme}.svg"
                        if vendor_svg.is_file():
                            return FileResponse(
                                path=str(vendor_svg),
                                media_type="image/svg+xml",
                                headers=cache_headers,
                            )
                        break  # pack found in this vendor, but SVG missing — fall through
            except Exception as exc:
                logger.debug("vendor_map.yaml resolution failed for %s: %s", pack_name, exc)

        # Priority 3 — per-integration image-file fallback
        if integrations_dir.is_dir():
            for int_subdir in sorted(integrations_dir.iterdir()):
                if not int_subdir.is_dir():
                    continue
                int_name = int_subdir.name
                legacy_dark = int_subdir / f"{int_name}_dark.svg"
                legacy_png = int_subdir / f"{int_name}_image.png"
                if legacy_dark.is_file():
                    return FileResponse(
                        path=str(legacy_dark),
                        media_type="image/svg+xml",
                        headers=cache_headers,
                    )
                if legacy_png.is_file():
                    return FileResponse(
                        path=str(legacy_png),
                        media_type="image/png",
                        headers=cache_headers,
                    )

        author_png = pack_dir / "Author_image.png"
        if author_png.is_file():
            return FileResponse(
                path=str(author_png),
                media_type="image/png",
                headers=cache_headers,
            )

        return JSONResponse(
            {"error": f"no logo baked for pack '{pack_name}'"},
            status_code=404,
        )

    # Process-level cache for vendor primary_color lookup.
    # vendor_map.yaml stays the source of truth for VENDOR-level metadata
    # (display_name, primary_color); the per-source YAMLs are the source
    # of truth for PER-SOURCE metadata (pack/rule/dataset/categories/logo).
    # This cache only flattens vendor_name → primary_color so the catalog
    # response can paint the UI's gradient.
    _COLOR_CACHE: dict[str, str] = {}

    def _build_vendor_color_cache() -> dict[str, str]:
        """{vendor_display_name: primary_color_hex} from vendor_map.yaml.

        Returns {} when vendor_map.yaml is unavailable. Bundle rows then
        fall back to the default gray; the UI still renders, just without
        the brand gradient. User-uploaded rows always use the default
        (operator-vendor branding is not supported).
        """
        nonlocal _COLOR_CACHE
        if _COLOR_CACHE:
            return _COLOR_CACHE
        try:
            cortex = _load_cortex_content()
        except FileNotFoundError:
            return _COLOR_CACHE
        baked_mod_name = cortex.__name__.rsplit(".", 1)[0] + "._baked_client"
        baked_mod = sys.modules.get(baked_mod_name)
        if baked_mod is None:
            spec = importlib.util.spec_from_file_location(
                baked_mod_name,
                str(_resolve_cortex_content_src() / "_baked_client.py"),
            )
            baked_mod = importlib.util.module_from_spec(spec)
            sys.modules[baked_mod_name] = baked_mod
            spec.loader.exec_module(baked_mod)
        if not baked_mod.is_baked_available():
            return _COLOR_CACHE
        vmap_path = baked_mod.baked_root_path() / "vendor_map.yaml"
        if not vmap_path.is_file():
            return _COLOR_CACHE
        try:
            import yaml as _yaml
            vmap = _yaml.safe_load(vmap_path.read_text()) or {}
            for vk, info in (vmap.get("vendors") or {}).items():
                display = info.get("display_name", vk)
                color = info.get("primary_color", "#5F6368")
                _COLOR_CACHE[display] = color
        except Exception as exc:
            logger.debug("vendor color cache build failed: %s", exc)
        return _COLOR_CACHE

    @mcp.custom_route(
        "/api/v1/data-sources/catalog",
        methods=["GET"],
        include_in_schema=False,
    )
    async def catalog_data_sources(request: Request) -> JSONResponse:
        """Browse-view source — returns the rolled-up catalog of
        available data sources from per-source YAMLs.

        Loads YAMLs from BOTH the bundled root (`/app/bundle/data-sources/`)
        and the user-uploaded root (`/app/data/user_data_sources/`),
        joins them into one list. Bundle wins on id collision.

        Query params:
          xsiam_only   - "1" / "true" / "yes" → only XSIAM-tagged packs.
                         Default true (no-op — bundled YAMLs are xsiam-only).
          include_rawlog - "1" / "true" / "yes" → include rawlog-only
                           rules in the rows. Default false (the UI
                           focuses on structured packs first).
          pack_limit   - integer cap on row count.
                         0 (default) = all.
          origin       - "bundle" | "user" → filter to one origin only.
                         Default unset = both.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        q = request.query_params
        xsiam_only_raw = q.get("xsiam_only", "true").lower()
        xsiam_only = xsiam_only_raw in ("1", "true", "yes")
        include_rawlog = q.get("include_rawlog", "false").lower() in (
            "1", "true", "yes",
        )
        origin_filter = q.get("origin")
        if origin_filter not in (None, "bundle", "user"):
            return JSONResponse(
                {"error": "origin must be 'bundle' or 'user' when set"},
                status_code=400,
            )
        try:
            pack_limit = int(q.get("pack_limit", "0"))
        except ValueError:
            return JSONResponse(
                {"error": "pack_limit must be an integer"}, status_code=400,
            )

        try:
            loader = get_data_sources_yaml_loader()
            all_sources = loader.list_all()
        except Exception as exc:  # noqa: BLE001
            logger.exception("YAML loader failed")
            return JSONResponse(
                {"error": f"data sources catalog load failed: {exc}"},
                status_code=500,
            )

        # Build the install-overlay set ONCE per request (sqlite read)
        installed_ids = {ds.id for ds in store.list()}
        color_cache = _build_vendor_color_cache()

        rows: list[dict[str, Any]] = []
        for y in all_sources:
            if origin_filter and y.origin != origin_filter:
                continue
            if not include_rawlog and y.is_rawlog_only:
                continue
            installed = (
                compose_data_source_id(y.pack_name, y.rule_name, y.dataset_name)
                in installed_ids
            )
            row = y.to_catalog_row(installed=installed)
            # Override primary_color from vendor_map.yaml for bundle rows
            if y.origin == "bundle":
                row["vendor_primary_color"] = color_cache.get(y.vendor, "#5F6368")
            rows.append(row)

        if pack_limit > 0:
            rows = rows[:pack_limit]

        # vendor_logo_url enrichment. The InstalledCard + per-row install
        # button use the VENDOR's logo, not whatever per-pack logo each
        # row happens to carry (siblings like F5ASM / F5LTM / F5APM would
        # otherwise each show a different per-pack mark, sometimes
        # white-on-white from the baked SVGs).
        #
        # Compute vendor_logo_url = the first row's logo_url that's
        # non-null, per vendor_key. Mirrors the VendorCard picker. Set on EVERY row so all consumers (Browse vendor
        # card, Installed card, expanded-pack-row card, drawer) share
        # the same vendor logo.
        vendor_logo: dict[str, str | None] = {}
        for r in rows:
            vk = r.get("vendor_key") or r.get("pack_name") or ""
            if vk not in vendor_logo and r.get("logo_url"):
                vendor_logo[vk] = r["logo_url"]
        for r in rows:
            vk = r.get("vendor_key") or r.get("pack_name") or ""
            r["vendor_logo_url"] = vendor_logo.get(vk) or r.get("logo_url")

        return JSONResponse({
            "ok": True,
            "rows": rows,
            "row_count": len(rows),
            "filter": {
                "xsiam_only": xsiam_only,
                "include_rawlog": include_rawlog,
                "origin": origin_filter,
                "pack_limit": pack_limit,
            },
        })

    @mcp.custom_route(
        "/api/v1/data-sources",
        methods=["GET"],
        include_in_schema=False,
    )
    async def list_data_sources(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        q = request.query_params
        filter_ = q.get("filter") or None
        rows = store.list(filter=filter_)

        # Enrich installed rows with vendor_key + use_cases +
        # vendor_logo_url so the InstalledCard can render the vendor's
        # logo (instead of the per-pack one) and the use-case pills.
        # The store's DataSource model carries only the per-pack
        # snapshot; vendor metadata lives in the YAML loader. Cross-
        # reference once + cache per-vendor-logo.
        loader = get_data_sources_yaml_loader()
        all_yamls = loader.list_all()
        # vendor_key (slugified vendor name) → (vendor_display, logo_url, use_cases)
        # Pick the first YAML per vendor that has an inline logo for the
        # vendor_logo_url; same picker rule as catalog endpoint.
        vendor_meta: dict[str, dict[str, Any]] = {}
        for y in all_yamls:
            from usecase.data_sources_yaml_loader import _slugify
            vk = _slugify(y.vendor).lower()
            existing = vendor_meta.setdefault(vk, {
                "vendor_display_name": y.vendor,
                "vendor_logo_url": None,
                "use_cases": [],
            })
            if not existing["vendor_logo_url"]:
                row_logo = y._compute_logo_url()  # noqa: SLF001
                if row_logo:
                    existing["vendor_logo_url"] = row_logo
            # use_cases: dedupe across packs (most vendors are stable).
            for uc in (y.use_cases or []):
                if uc not in existing["use_cases"]:
                    existing["use_cases"].append(uc)

        # Per-installed-row lookup maps so each row can resolve its vendor_key,
        # origin, and live field counts. Keyed by the COMPOSITE id
        # (compose_data_source_id = "pack/rule/dataset") to match the store's
        # `r.id`. Origin (bundle vs user) drives the UI's Edit affordance.
        # The YAML loader's `y.id` is the SHORT id (e.g. "ServiceNow") and
        # never matches `r.id`; keying these maps by it would make the
        # vendor_key/origin/field-count overlays silently fall through to
        # the else-branch, leaving InstalledCards with no vendor logo /
        # display name / use-cases and a defaulted origin.
        pack_to_vendor_key: dict[str, str] = {}
        pack_to_origin: dict[str, str] = {}
        pack_to_delivery: dict[str, str] = {}
        for y in all_yamls:
            from usecase.data_sources_yaml_loader import _slugify
            cid = compose_data_source_id(y.pack_name, y.rule_name, y.dataset_name)
            pack_to_vendor_key[cid] = _slugify(y.vendor).lower()
            pack_to_origin[cid] = y.origin
            pack_to_delivery[cid] = y.delivery
        # Live field counts via the shared, unit-tested helper.
        pack_to_counts = _live_field_counts_by_id()

        enriched = []
        for r in rows:
            d = r.to_dict()
            vk = pack_to_vendor_key.get(r.id)
            if vk and vk in vendor_meta:
                meta = vendor_meta[vk]
                d["vendor_key"] = vk
                d["vendor_display_name"] = meta["vendor_display_name"]
                d["vendor_logo_url"] = meta["vendor_logo_url"] or d.get("logo_url")
                d["use_cases"] = list(meta["use_cases"])
            else:
                # Defensive — no YAML found (rare); fall back to per-row data.
                d["vendor_logo_url"] = d.get("logo_url")
                d["use_cases"] = []
            # Origin lookup. Default to "bundle" for any installed row
            # missing from the YAML map (defensive; should not happen).
            d["origin"] = pack_to_origin.get(r.id, "bundle")
            # Delivery overlay (YAML-only attribute; default syslog).
            d["delivery"] = pack_to_delivery.get(r.id, "syslog")
            # Overlay live field counts (snapshot in the store drifts
            # when the bundle YAML is enriched post-install). No-op if the row
            # has no YAML match (defensive; leaves the snapshot value).
            if r.id in pack_to_counts:
                d["field_count"], d["non_meta_field_count"] = pack_to_counts[r.id]
            enriched.append(d)

        return JSONResponse(
            {
                "data_sources": enriched,
                "count": len(enriched),
                "filter": filter_,
            }
        )

    @mcp.custom_route(
        "/api/v1/data-sources/install",
        methods=["POST"],
        include_in_schema=False,
    )
    async def install_data_source(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            body = await _json_body(request)
            if isinstance(body, JSONResponse):
                return body
            pack_name = body.get("pack_name")
            rule_name = body.get("rule_name")
            dataset_name = body.get("dataset_name")  # optional
            if not pack_name or not rule_name:
                return JSONResponse(
                    {"error": "pack_name and rule_name are required"},
                    status_code=400,
                )
            if not isinstance(pack_name, str) or not isinstance(rule_name, str):
                return JSONResponse(
                    {"error": "pack_name and rule_name must be strings"},
                    status_code=400,
                )
            if dataset_name is not None and not isinstance(dataset_name, str):
                return JSONResponse(
                    {"error": "dataset_name must be a string when provided"},
                    status_code=400,
                )

            # User-uploaded packs install from their YAML directly (no
            # cortex-content extraction; the YAML's fields[] is the source
            # of truth). BUNDLED packs whose YAML has populated `fields[]`
            # also install from the YAML; otherwise the curated fields shown
            # in the catalog browse view would go away the moment the
            # operator hits Install (the cortex-content extraction path
            # drops them).
            # Selection rule:
            #   * user YAML found → install from YAML
            #   * bundle YAML found AND has populated fields[] → install from YAML
            #   * otherwise → fall back to cortex-content extraction
            try:
                yaml_loader = get_data_sources_yaml_loader()
                yaml_ds = None
                if dataset_name is not None:
                    candidate = yaml_loader.get_by_3tuple(
                        pack_name, rule_name, dataset_name,
                    )
                    if candidate is not None:
                        prefer_yaml = (
                            candidate.origin == "user"
                            or bool(candidate.fields)
                        )
                        if prefer_yaml:
                            yaml_ds = candidate
                if yaml_ds is not None:
                    composed, meta = _compose_from_user_yaml(
                        yaml_ds, installed_by="user:operator",
                    )
                else:
                    composed, meta = await _extract_and_compose_data_sources(
                        pack_name=pack_name,
                        rule_name=rule_name,
                        dataset_name=dataset_name,
                        installed_by="user:operator",
                    )
            except FileNotFoundError as exc:
                return JSONResponse(
                    {"error": f"cortex-content connector source missing: {exc}"},
                    status_code=500,
                )
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=404)

            installed_ids: list[str] = []
            total_fields = 0
            for ds, fields in composed:
                store.install(ds, fields=fields)
                installed_ids.append(ds.id)
                total_fields += len(fields)
                audit.record(
                    action="data_source_install",
                    target=f"data_source:{ds.id}",
                    status="success",
                    metadata={
                        "pack_name": ds.pack_name,
                        "rule_name": ds.rule_name,
                        "dataset_name": ds.dataset_name,
                        "field_count": ds.field_count,
                        "is_rawlog_only": ds.is_rawlog_only,
                        "pack_version": ds.pack_version,
                    },
                )

            return JSONResponse(
                {
                    "ok": True,
                    "data_source_ids": installed_ids,
                    "fields_count": total_fields,
                    "datasets_installed": meta["datasets_installed"],
                    "datasets_in_rule": meta["datasets_in_rule"],
                    "pack_version": meta["pack_version"],
                },
                status_code=201,
            )
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/data-sources/{pack_name}/{rule_name}/{dataset_name}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_data_source(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        ds_id = compose_data_source_id(
            request.path_params["pack_name"],
            request.path_params["rule_name"],
            request.path_params["dataset_name"],
        )
        ds = store.get(ds_id)
        if ds is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"data_source": ds.to_dict()})

    @mcp.custom_route(
        "/api/v1/data-sources/{pack_name}/{rule_name}/{dataset_name}/schema",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_data_source_schema(request: Request) -> JSONResponse:
        """Return the data source's schema for the drawer view.

        Resolution path:
          1. Installed store (sqlite) — for packs already installed
          2. Preview from cortex-content baked tree — for uninstalled
             packs the operator clicks to preview before deciding to
             install. Returns the same shape with `is_preview: true`
             flag so the UI can render an Install CTA.

        Both paths normalize logo_url to the route's /logo/<pack> URL
        so the drawer's vendor icon resolves via vendor_map.yaml even
        for uninstalled packs.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        pack_name = request.path_params["pack_name"]
        rule_name = request.path_params["rule_name"]
        dataset_name = request.path_params["dataset_name"]
        ds_id = compose_data_source_id(pack_name, rule_name, dataset_name)

        # Path 1 — installed store
        expanded = store.get_with_schema(ds_id)
        if expanded is not None:
            payload = expanded.to_dict()
            # Normalize logo_url to the route so vendor_map.yaml
            # resolution kicks in (the stored value may be stale from
            # install time).
            payload["logo_url"] = f"/api/agent/data-sources/logo/{pack_name}"
            payload["logo_type"] = "svg"
            payload["is_preview"] = False
            # Also resolve vendor_logo_url + use_cases via the YAML loader
            # so the drawer header carries the vendor logo (not a per-pack
            # one). Drawer JS prefers `vendor_logo_url` per row.
            _enrich_with_vendor_meta(payload, ds_id)
            _sync_field_counts_to_fields(payload)  # tile == table
            return JSONResponse({"data_source": payload})

        # Path 1.5 — bundled/user YAML (source of truth). Covers
        # uninstalled sources that have a YAML but that cortex-content's
        # schema.json doesn't enumerate (e.g. a 2nd dataset under one
        # pack+rule like okta_sso_raw). The catalog already lists these via
        # the YAML loader; the drawer must resolve them the same way before
        # falling back to cortex.
        yaml_ds = get_data_sources_yaml_loader().get_by_3tuple(
            pack_name, rule_name, dataset_name
        )
        if yaml_ds is not None:
            payload = _yaml_ds_to_schema_payload(yaml_ds, ds_id, is_preview=True)
            payload["logo_url"] = f"/api/agent/data-sources/logo/{pack_name}"
            payload["logo_type"] = "svg"
            _enrich_with_vendor_meta(payload, ds_id)
            _sync_field_counts_to_fields(payload)  # tile == table
            return JSONResponse({"data_source": payload})

        # Path 2 — preview from baked cortex-content (uninstalled)
        try:
            composed, _meta = await _extract_and_compose_data_sources(
                pack_name=pack_name,
                rule_name=rule_name,
                dataset_name=dataset_name,
                installed_by="preview:operator",
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:  # noqa: BLE001
            logger.exception("schema preview failed for %s", ds_id)
            return JSONResponse({"error": f"preview failed: {exc}"}, status_code=500)

        if not composed:
            return JSONResponse({"error": "no datasets in pack"}, status_code=404)
        ds, fields = composed[0]
        ds_payload = ds.to_dict()
        ds_payload["logo_url"] = f"/api/agent/data-sources/logo/{pack_name}"
        ds_payload["logo_type"] = "svg"
        ds_payload["fields"] = [
            {
                "name": f.name,
                "type": f.type,
                "is_array": f.is_array,
                "is_meta": f.is_meta,
                "is_gate": getattr(f, "is_gate", False),
                "enum_values": getattr(f, "enum_values", None),
                "description": f.description,
                # Surface example on the preview path so the drawer's
                # Example column populates for uninstalled bundled packs
                # (matching the installed path's shape).
                "example": f.example,
            }
            for f in fields
        ]
        # The schema carries no xdm_mappings. Data sources are
        # vendor-neutral specs; XDM is Cortex-specific and downstream of
        # the wire format.
        ds_payload["is_preview"] = True
        # Same vendor enrichment for the preview path.
        _enrich_with_vendor_meta(ds_payload, ds_id)
        _sync_field_counts_to_fields(ds_payload)  # tile == table
        return JSONResponse({"data_source": ds_payload})

    @mcp.custom_route(
        "/api/v1/data-sources/{pack_name}/{rule_name}/{dataset_name}/edit",
        methods=["PUT"],
        include_in_schema=False,
    )
    async def edit_data_source(request: Request) -> JSONResponse:
        """Edit a data source (how_to_use + schema columns), creating a
        version. On first edit the original is snapshotted as v1; the loader
        then serves the new current as an overlay (the file on disk is never
        mutated). Body (all optional): {"how_to_use": "...", "fields": [...],
        "note": "..."}.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        body = await _json_body(request)
        if isinstance(body, JSONResponse):
            return body
        actor_token = set_current_actor("user:operator")
        try:
            result = _apply_edit(
                request.path_params["pack_name"],
                request.path_params["rule_name"],
                request.path_params["dataset_name"],
                how_to_use=body.get("how_to_use"),
                fields=body.get("fields"),
                note=body.get("note"),
                author="operator",
            )
            return JSONResponse(result, status_code=200 if result.get("ok") else 400)
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/data-sources/{pack_name}/{rule_name}/{dataset_name}/versions",
        methods=["GET"],
        include_in_schema=False,
    )
    async def list_data_source_versions(request: Request) -> JSONResponse:
        """List a data source's version history (metadata only; the
        full yaml_snapshot is omitted here — fetch one via .../versions/{n}).
        Returns {"ok": True, "versions": [{version, author, note, created_at,
        is_current}], "data_source_id": id}. Empty list if never edited.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        from usecase.data_source_versions_store import get_data_source_versions_store

        ds_id = compose_data_source_id(
            request.path_params["pack_name"],
            request.path_params["rule_name"],
            request.path_params["dataset_name"],
        )
        store = get_data_source_versions_store()
        rows = store.list_versions(ds_id) if store is not None else []
        versions = [
            {
                "version": r["version"],
                "author": r["author"],
                "note": r["note"],
                "created_at": r["created_at"],
                "is_current": bool(r["is_current"]),
            }
            for r in rows
        ]
        return JSONResponse({"ok": True, "versions": versions, "data_source_id": ds_id})

    @mcp.custom_route(
        "/api/v1/data-sources/{pack_name}/{rule_name}/{dataset_name}/versions/{version}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_data_source_version(request: Request) -> JSONResponse:
        """Fetch one version's full content (incl. yaml_snapshot).
        404 if the version doesn't exist for this source.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        from usecase.data_source_versions_store import get_data_source_versions_store

        ds_id = compose_data_source_id(
            request.path_params["pack_name"],
            request.path_params["rule_name"],
            request.path_params["dataset_name"],
        )
        try:
            version = int(request.path_params["version"])
        except (TypeError, ValueError):
            return JSONResponse({"ok": False, "error": "version must be an integer"}, status_code=400)
        store = get_data_source_versions_store()
        row = store.get_version(ds_id, version) if store is not None else None
        if row is None:
            return JSONResponse(
                {"ok": False, "error": f"version {version} not found for {ds_id}"},
                status_code=404,
            )
        return JSONResponse({"ok": True, "version": dict(row)})

    @mcp.custom_route(
        "/api/v1/data-sources/{pack_name}/{rule_name}/{dataset_name}/rollback",
        methods=["POST"],
        include_in_schema=False,
    )
    async def rollback_data_source(request: Request) -> JSONResponse:
        """Roll a data source back to a prior version. Body:
        {"version": k}. Non-destructive: copies vK forward as a new current
        version; history is preserved. 400 on unknown version / no history.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        body = await _json_body(request)
        if isinstance(body, JSONResponse):
            return body
        if "version" not in body:
            return JSONResponse({"ok": False, "error": "body must include 'version'"}, status_code=400)
        actor_token = set_current_actor("user:operator")
        try:
            result = _apply_rollback(
                request.path_params["pack_name"],
                request.path_params["rule_name"],
                request.path_params["dataset_name"],
                version=body["version"],
                author="operator",
            )
            return JSONResponse(result, status_code=200 if result.get("ok") else 400)
        finally:
            reset_current_actor(actor_token)

    @mcp.custom_route(
        "/api/v1/data-sources/{pack_name}/{rule_name}/{dataset_name}/export",
        methods=["GET"],
        include_in_schema=False,
    )
    async def export_data_source_yaml(request: Request) -> Response:
        """Download a data source's `data_source.yaml`.

        Version-aware:
          - `?version=n` → that version's snapshot verbatim
            (filename `{dataset}.v{n}.yaml`). 404 if the version is unknown.
          - default (no param) → the CURRENT content: the latest edited
            version's snapshot if the source has history, else the pristine
            file on disk (filename `{dataset}.yaml`).

        For unedited sources this is the raw on-disk YAML (operator-authored
        comments, ordering, whitespace preserved). For edited sources it is
        the version snapshot (canonical re-serialized YAML), matching what
        the drawer + the loader overlay serve. Useful for forking a pack,
        sharing a schema out-of-band, or backing up before a refresh.

        Bearer-auth gated like the rest of the data-sources surface.
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        content, filename, error = _resolve_export_content(
            request.path_params["pack_name"],
            request.path_params["rule_name"],
            request.path_params["dataset_name"],
            version=request.query_params.get("version"),
        )
        if error in ("not_found", "version_not_found"):
            return JSONResponse({"error": error}, status_code=404)
        if error is not None or content is None:
            return JSONResponse({"error": error or "read_failed"}, status_code=500)
        return Response(
            content,
            media_type="application/x-yaml; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    @mcp.custom_route(
        "/api/v1/data-sources/{pack_name}/{rule_name}/{dataset_name}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def uninstall_data_source(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        actor_token = set_current_actor("user:operator")
        try:
            ds_id = compose_data_source_id(
                request.path_params["pack_name"],
                request.path_params["rule_name"],
                request.path_params["dataset_name"],
            )
            existed = store.uninstall(ds_id)
            if existed:
                audit.record(
                    action="data_source_uninstall",
                    target=f"data_source:{ds_id}",
                    status="success",
                    metadata={"data_source_id": ds_id},
                )
                return JSONResponse({"ok": True, "deleted": True})
            return JSONResponse(
                {"ok": True, "deleted": False, "error": "not found"},
                status_code=404,
            )
        finally:
            reset_current_actor(actor_token)

    # ─── user-uploaded data sources ───────────────────────────────────
    #
    # Operator-uploadable data sources: matching shape to bundled
    # (same data_source.yaml schema) but writable + delete-able. The
    # upload flow is two-step:
    #
    #   1. POST /user/preview  → validate YAML + run similarity check
    #                            against known vendors. Returns the
    #                            yaml_hash as an accept_token so commit
    #                            can verify the operator previewed the
    #                            exact bytes they're committing.
    #   2. POST /user          → commit; takes the yaml + accept_token +
    #                            vendor_choice ("create_new" or
    #                            "group_under" + group_vendor). Writes
    #                            to /app/data/user_data_sources/<id>/.
    #
    # Routing order: literal `/user/preview` registered BEFORE
    # `/user/{id}` so the catch-all doesn't swallow "preview" as an id.
    # (Same pattern as the `install` literal up top.)

    @mcp.custom_route(
        "/api/v1/data-sources/user/preview",
        methods=["POST"],
        include_in_schema=False,
    )
    async def preview_user_upload(request: Request) -> JSONResponse:
        """Validate an uploaded data_source.yaml + run vendor similarity check.

        Body shape:
          { "yaml": "<full yaml content as string>" }
          OR
          { "doc":  { ...parsed yaml dict... } }

        Response on validation pass:
          {
            "ok": true,
            "uploaded_vendor": "AcmeCrop",
            "similarity_matches": [
              {"vendor": "AcmeCorp", "similarity": "levenshtein", "distance": 1},
              ...
            ],
            "accept_token": "<sha256 of canonical yaml>",
            "id": "<doc.id>",
          }

        Response on validation fail:
          { "ok": false, "errors": ["categories[0]: must be string", ...] }
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        body = await _json_body(request)
        if isinstance(body, JSONResponse):
            return body

        # Accept either pre-parsed `doc` or raw `yaml` text
        doc = body.get("doc")
        yaml_text = body.get("yaml")
        if doc is None and yaml_text is None:
            return JSONResponse(
                {"ok": False, "error": "body must contain `yaml` (string) or `doc` (object)"},
                status_code=400,
            )
        if doc is None:
            try:
                import yaml as _yaml
                doc = _yaml.safe_load(yaml_text)
            except Exception as exc:
                return JSONResponse(
                    {"ok": False, "error": f"YAML parse failed: {exc}"},
                    status_code=400,
                )
        if not isinstance(doc, dict):
            return JSONResponse(
                {"ok": False, "error": "yaml content must parse to a dict"},
                status_code=400,
            )

        # Validate via the loader (schema check)
        from usecase.data_sources_yaml_loader import validate_yaml_doc
        ok, errors = validate_yaml_doc(doc)
        if not ok:
            return JSONResponse(
                {"ok": False, "errors": errors},
                status_code=400,
            )

        # Compute accept_token = sha256 of canonical yaml bytes. The
        # client must re-send the exact same yaml at commit. No secret —
        # the operator is already bearer-authenticated; this is sanity-
        # check that preview-and-commit see the same bytes.
        import hashlib
        canonical = _canonical_yaml_bytes(doc)
        accept_token = hashlib.sha256(canonical).hexdigest()

        # Similarity check against known vendors
        loader = get_data_sources_yaml_loader()
        known_vendor_set = {ds.vendor for ds in loader.list_all() if ds.vendor}
        matches = find_similar_vendors(
            doc.get("vendor", ""), sorted(known_vendor_set),
        )

        # Also flag bundle id collision so the UI can surface it
        bundle_collision = (
            (loader.bundle_root / doc.get("id", "")).exists()
            if doc.get("id") else False
        )

        return JSONResponse({
            "ok": True,
            "uploaded_vendor": doc.get("vendor", ""),
            "uploaded_id": doc.get("id", ""),
            "similarity_matches": [m.to_dict() for m in matches],
            "bundle_collision": bundle_collision,
            "accept_token": accept_token,
        })

    @mcp.custom_route(
        "/api/v1/data-sources/user",
        methods=["POST"],
        include_in_schema=False,
    )
    async def commit_user_upload(request: Request) -> JSONResponse:
        """Commit a previewed YAML upload to /app/data/user_data_sources/.

        Body shape:
          {
            "yaml": "<full yaml content as string>",  # OR doc:
            "doc": { ...parsed... },
            "accept_token": "<from preview>",
            "vendor_choice": "create_new" | "group_under",  # metadata only
          }

        The `vendor_choice` is metadata-only at commit time — the
        operator pre-applies grouping client-side (rewriting the YAML's
        vendor field BEFORE preview) so the preview's similarity-check
        result + accept_token reflect the final form. If group_under is
        selected mid-flow, the client RE-PREVIEWS with the rewritten
        YAML before commit. Server-side rewriting would invalidate the
        accept_token, so we keep it client-side.

        Response:
          { "ok": true, "id": "<doc.id>", "data_source": {...row...} }
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        body = await _json_body(request)
        if isinstance(body, JSONResponse):
            return body
        actor_token_ctx = set_current_actor("user:operator")
        try:
            doc = body.get("doc")
            yaml_text = body.get("yaml")
            if doc is None and yaml_text is None:
                return JSONResponse(
                    {"ok": False, "error": "body must contain `yaml` or `doc`"},
                    status_code=400,
                )
            if doc is None:
                try:
                    import yaml as _yaml
                    doc = _yaml.safe_load(yaml_text)
                except Exception as exc:
                    return JSONResponse(
                        {"ok": False, "error": f"YAML parse failed: {exc}"},
                        status_code=400,
                    )
            if not isinstance(doc, dict):
                return JSONResponse(
                    {"ok": False, "error": "yaml content must parse to a dict"},
                    status_code=400,
                )

            accept_token = body.get("accept_token")
            if not accept_token or not isinstance(accept_token, str):
                return JSONResponse(
                    {"ok": False, "error": "accept_token required (call /user/preview first)"},
                    status_code=400,
                )
            vendor_choice = body.get("vendor_choice", "create_new")
            if vendor_choice not in ("create_new", "group_under"):
                return JSONResponse(
                    {"ok": False, "error": "vendor_choice must be 'create_new' or 'group_under'"},
                    status_code=400,
                )

            # Token verification — operator must commit the EXACT bytes
            # they previewed. group_under rewriting (if any) happened
            # client-side BEFORE preview, so the token covers the final
            # form. A mismatch here means either the YAML was modified
            # between preview and commit OR the client forgot to
            # re-preview after a group_under choice.
            import hashlib
            canonical = _canonical_yaml_bytes(doc)
            recomputed = hashlib.sha256(canonical).hexdigest()
            if recomputed != accept_token:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "accept_token mismatch — the YAML differs from the previewed bytes. Re-run /user/preview with the current YAML and retry.",
                    },
                    status_code=409,
                )

            # Write
            loader = get_data_sources_yaml_loader()
            ds, errors = loader.write_user(doc)
            if ds is None:
                return JSONResponse(
                    {"ok": False, "errors": errors},
                    status_code=400,
                )

            audit.record(
                action="data_source_user_upload",
                target=f"data_source:{ds.id}",
                status="success",
                metadata={
                    "id": ds.id,
                    "vendor": ds.vendor,
                    "product": ds.product,
                    "vendor_choice": vendor_choice,
                    "field_count": len(ds.fields),
                },
            )

            return JSONResponse(
                {
                    "ok": True,
                    "id": ds.id,
                    "data_source": ds.to_catalog_row(installed=False),
                },
                status_code=201,
            )
        finally:
            reset_current_actor(actor_token_ctx)

    @mcp.custom_route(
        "/api/v1/data-sources/user",
        methods=["GET"],
        include_in_schema=False,
    )
    async def list_user_uploads(request: Request) -> JSONResponse:
        """List operator-uploaded data sources (no bundle entries)."""
        if (resp := require_bearer(request)) is not None:
            return resp
        loader = get_data_sources_yaml_loader()
        user_sources = loader.list_user()
        installed_ids = {ds.id for ds in store.list()}
        rows = [
            y.to_catalog_row(
                installed=(
                    compose_data_source_id(y.pack_name, y.rule_name, y.dataset_name)
                    in installed_ids
                )
            )
            for y in user_sources
        ]
        return JSONResponse(
            {"ok": True, "rows": rows, "row_count": len(rows)},
        )

    @mcp.custom_route(
        "/api/v1/data-sources/user/{id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_user_upload(request: Request) -> JSONResponse:
        """Return one user-uploaded data source's full YAML doc."""
        if (resp := require_bearer(request)) is not None:
            return resp
        ds_id = request.path_params["id"]
        if "/" in ds_id or ".." in ds_id or ds_id.startswith("."):
            return JSONResponse({"ok": False, "error": "invalid id"}, status_code=400)
        loader = get_data_sources_yaml_loader()
        ds = loader.get_user(ds_id)
        if ds is None:
            return JSONResponse(
                {"ok": False, "error": f"user data source '{ds_id}' not found"},
                status_code=404,
            )
        installed_ids = {row.id for row in store.list()}
        row = ds.to_catalog_row(
            installed=(
                compose_data_source_id(ds.pack_name, ds.rule_name, ds.dataset_name)
                in installed_ids
            )
        )
        return JSONResponse({"ok": True, "data_source": row, "doc": ds.to_doc()})

    @mcp.custom_route(
        "/api/v1/data-sources/user/{id}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def delete_user_upload(request: Request) -> JSONResponse:
        """Remove a user-uploaded data source from disk.

        Also uninstalls from data_sources_store if installed (cascade —
        an uninstalled-but-deleted source would orphan worker references).
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        ds_id = request.path_params["id"]
        if "/" in ds_id or ".." in ds_id or ds_id.startswith("."):
            return JSONResponse({"ok": False, "error": "invalid id"}, status_code=400)
        actor_token_ctx = set_current_actor("user:operator")
        try:
            loader = get_data_sources_yaml_loader()
            ds = loader.get_user(ds_id)
            try:
                deleted = loader.delete_user(ds_id)
            except ValueError as exc:
                return JSONResponse(
                    {"ok": False, "error": str(exc)},
                    status_code=409,
                )
            if not deleted:
                return JSONResponse(
                    {"ok": False, "error": f"user data source '{ds_id}' not found"},
                    status_code=404,
                )
            # Cascade-uninstall from data_sources_store if present
            if ds is not None:
                store_id = compose_data_source_id(ds.pack_name, ds.rule_name, ds.dataset_name)
                store.uninstall(store_id)
            audit.record(
                action="data_source_user_delete",
                target=f"data_source:{ds_id}",
                status="success",
                metadata={"id": ds_id},
            )
            return JSONResponse({"ok": True, "deleted": True, "id": ds_id})
        finally:
            reset_current_actor(actor_token_ctx)

    @mcp.custom_route(
        "/api/v1/data-sources/user/{id}",
        methods=["PUT"],
        include_in_schema=False,
    )
    async def update_user_upload(request: Request) -> JSONResponse:
        """Edit an existing user-uploaded YAML.

        Body shape (same as POST /user, plus the path-id is the canonical id):
          {
            "yaml": "<full yaml content as string>",  # OR doc:
            "doc": { ...parsed... },
            "accept_token": "<from /user/preview>",
            "vendor_choice": "create_new" | "group_under",
          }

        The path id MUST match the body's `id` — PUT is not rename. To
        rename, delete + re-upload with the new id.

        accept_token semantics are identical to POST: the operator must
        have just previewed the exact bytes they're committing. A
        mismatch ⇒ HTTP 409 (re-preview + retry).

        Successful update:
          { "ok": true, "id": "<id>", "data_source": {...catalog row...} }
          status 200

        Errors:
          404 — path id has no user upload on disk
          400 — body shape invalid
          409 — accept_token mismatch OR path/body id mismatch
        """
        if (resp := require_bearer(request)) is not None:
            return resp
        ds_id = request.path_params["id"]
        if "/" in ds_id or ".." in ds_id or ds_id.startswith("."):
            return JSONResponse({"ok": False, "error": "invalid id"}, status_code=400)

        body = await _json_body(request)
        if isinstance(body, JSONResponse):
            return body
        actor_token_ctx = set_current_actor("user:operator")
        try:
            doc = body.get("doc")
            yaml_text = body.get("yaml")
            if doc is None and yaml_text is None:
                return JSONResponse(
                    {"ok": False, "error": "body must contain `yaml` or `doc`"},
                    status_code=400,
                )
            if doc is None:
                try:
                    import yaml as _yaml
                    doc = _yaml.safe_load(yaml_text)
                except Exception as exc:
                    return JSONResponse(
                        {"ok": False, "error": f"YAML parse failed: {exc}"},
                        status_code=400,
                    )
            if not isinstance(doc, dict):
                return JSONResponse(
                    {"ok": False, "error": "yaml content must parse to a dict"},
                    status_code=400,
                )

            accept_token = body.get("accept_token")
            if not accept_token or not isinstance(accept_token, str):
                return JSONResponse(
                    {"ok": False, "error": "accept_token required (call /user/preview first)"},
                    status_code=400,
                )
            vendor_choice = body.get("vendor_choice", "create_new")
            if vendor_choice not in ("create_new", "group_under"):
                return JSONResponse(
                    {"ok": False, "error": "vendor_choice must be 'create_new' or 'group_under'"},
                    status_code=400,
                )

            # Token verification — see POST /user for rationale.
            import hashlib
            canonical = _canonical_yaml_bytes(doc)
            recomputed = hashlib.sha256(canonical).hexdigest()
            if recomputed != accept_token:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "accept_token mismatch — the YAML differs from the previewed bytes. Re-run /user/preview with the current YAML and retry.",
                    },
                    status_code=409,
                )

            # Capture old state for the audit log diff.
            loader = get_data_sources_yaml_loader()
            old_ds = loader.get_user(ds_id)
            if old_ds is None:
                return JSONResponse(
                    {"ok": False, "error": f"user data source '{ds_id}' not found"},
                    status_code=404,
                )

            ds, errors = loader.update_user(ds_id, doc)
            if ds is None:
                # Distinguish 404 (not found) from 409 (id mismatch) from
                # 400 (validation). update_user returns errors with
                # specific phrasings; route those back to status codes.
                joined = "; ".join(errors)
                if "not found" in joined.lower():
                    return JSONResponse({"ok": False, "errors": errors}, status_code=404)
                if "id mismatch" in joined.lower() or "reserved by a bundled" in joined.lower():
                    return JSONResponse({"ok": False, "errors": errors}, status_code=409)
                return JSONResponse({"ok": False, "errors": errors}, status_code=400)

            audit.record(
                action="data_source_user_edit",
                target=f"data_source:{ds.id}",
                status="success",
                metadata={
                    "id": ds.id,
                    "vendor": ds.vendor,
                    "product": ds.product,
                    "vendor_choice": vendor_choice,
                    "field_count": len(ds.fields),
                    "old_field_count": len(old_ds.fields),
                    "old_vendor": old_ds.vendor,
                },
            )

            # Re-check install state — the source's id is stable across
            # edit (PUT-as-rename is refused) so install state is
            # preserved; mirror POST's reporting shape.
            installed_ids = {row.id for row in store.list()}
            row = ds.to_catalog_row(
                installed=(
                    compose_data_source_id(ds.pack_name, ds.rule_name, ds.dataset_name)
                    in installed_ids
                )
            )
            return JSONResponse(
                {"ok": True, "id": ds.id, "data_source": row},
                status_code=200,
            )
        finally:
            reset_current_actor(actor_token_ctx)

    @mcp.custom_route(
        "/api/v1/data-sources/user/{id}/logo",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_user_logo(request: Request):
        """Stream the inline base64 logo from a user-uploaded YAML.

        Returns the raw decoded bytes with the YAML's declared mime_type.
        404 when the source exists but has no logo, OR the source itself
        doesn't exist (both cases roll up to a missing logo from the UI's
        perspective).
        """
        from starlette.responses import Response
        import base64

        if (resp := require_bearer(request)) is not None:
            return resp
        ds_id = request.path_params["id"]
        if "/" in ds_id or ".." in ds_id or ds_id.startswith("."):
            return JSONResponse({"error": "invalid id"}, status_code=400)
        loader = get_data_sources_yaml_loader()
        ds = loader.get_user(ds_id)
        if ds is None or ds.logo is None:
            return JSONResponse(
                {"error": f"no logo for user source '{ds_id}'"},
                status_code=404,
            )
        try:
            data = base64.b64decode(ds.logo.get("data", ""))
        except Exception as exc:
            return JSONResponse(
                {"error": f"invalid base64 logo: {exc}"},
                status_code=500,
            )
        return Response(
            content=data,
            media_type=ds.logo.get("mime_type", "image/svg+xml"),
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @mcp.custom_route(
        "/api/v1/data-sources/inline-logo/{id}",
        methods=["GET"],
        include_in_schema=False,
    )
    async def get_inline_logo(request: Request):
        """Stream the inline base64 logo from EITHER root.

        Symmetric to `get_user_logo` but looks the YAML up via
        `loader.get_by_id()`, which searches both bundle and user roots
        (bundle wins on id collision per `list_all()` rules). This is
        the new path that `_compute_logo_url` returns whenever a YAML
        carries an inline `logo:` block — bundle YAMLs can now ship
        embedded SVGs without touching the baked vendor_map / vendor_svgs
        tree.

        404 when the source exists but has no logo OR doesn't exist at
        all.
        """
        from starlette.responses import Response
        import base64

        if (resp := require_bearer(request)) is not None:
            return resp
        ds_id = request.path_params["id"]
        if "/" in ds_id or ".." in ds_id or ds_id.startswith("."):
            return JSONResponse({"error": "invalid id"}, status_code=400)
        loader = get_data_sources_yaml_loader()
        ds = loader.get_by_id(ds_id)
        if ds is None or ds.logo is None:
            return JSONResponse(
                {"error": f"no inline logo for data source '{ds_id}'"},
                status_code=404,
            )
        try:
            data = base64.b64decode(ds.logo.get("data", ""))
        except Exception as exc:
            return JSONResponse(
                {"error": f"invalid base64 logo: {exc}"},
                status_code=500,
            )
        return Response(
            content=data,
            media_type=ds.logo.get("mime_type", "image/svg+xml"),
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )


# ─── MCP tools (agent-callable) ─────────────────────────────────────
#
# These are CATALOG operations per CLAUDE.md § Catalog boundary —
# the agent IS allowed to mutate via these.


async def data_sources_list(filter: str | dict | None = None) -> dict[str, Any]:
    """List installed data sources (vendor schemas).

    Args:
        filter: Optional case-insensitive substring matched against
            pack_name OR dataset_name OR rule_name OR pack_description.
            When None, returns all installed data sources sorted by
            pack_name then dataset_name.

    Returns:
        {
          ok: bool,
          data_sources: [{id, pack_name, rule_name, dataset_name,
                          field_count, non_meta_field_count,
                          is_rawlog_only, logo_url, ...}],
          count: int,
        }
    """
    from usecase.data_sources_store import get_data_sources_store

    store = get_data_sources_store()
    if store is None:
        return {"ok": False, "error": "data sources store not initialized"}
    if not isinstance(filter, str):  # a model sends {} for an optional string; treat it as no filter
        filter = None
    rows = store.list(filter=filter)
    return {
        "ok": True,
        "data_sources": [r.to_dict() for r in rows],
        "count": len(rows),
        "filter": filter,
    }


# The log-simulation worker's `schema_override` consumes ONLY
# name/type/isArray/isMeta (xlog createDataWorker normalizes just those —
# bundles/spark/connectors/xlog/src/workers.py ~L521-526); per-field
# `description` + `example` are UI/docs metadata the generator never reads.
# Compact mode drops them (plus the base64 `logo`) so a 100+-field schema
# fits the agent's tool-result size cap — without it the agent gets a
# TRUNCATED field list and forwards an incomplete schema_override, starving
# the composites a modeling rule reads (SentinelOne ~105 fields → only ~33
# reached the worker → XDM 0 despite raw landing).
#
# ALSO omit is_array/is_meta when falsy. Both default False at the
# worker, so dropping the False cases is lossless and roughly halves per-field
# bytes — needed because a 222-field vendor (FortiGate) overflowed even the
# keep-all-4-keys compact (truncated to ~103 fields → mapped 76 of a possible
# higher count). After this the full 222-field schema fits the cap.
def _compact_schema_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip per-field description + the base64 logo, and omit is_array/is_meta
    when False, so even a 200+-field schema fits the agent's tool-result cap.

    Lossless for schema_override: xlog reads name/type/is_array/is_meta (the
    latter two defaulting False when absent) plus is_gate/example for gate
    fields, which are RETAINED because the generator pins gate fields to their
    example. `example` is dropped for every non-gate field."""
    out = {k: v for k, v in payload.items() if k != "logo"}
    fields = out.get("fields")
    if isinstance(fields, list):
        compact: list[dict[str, Any]] = []
        for f in fields:
            if not isinstance(f, dict):
                continue
            cf: dict[str, Any] = {"name": f.get("name"), "type": f.get("type")}
            if f.get("is_array"):
                cf["is_array"] = True
            if f.get("is_meta"):
                cf["is_meta"] = True
            # A gate field's `example` is load-bearing, not illustrative: it is
            # the only value the rule accepts. Dropping it here is what made
            # compact schemas silently ungeneratable for gated sources, so both
            # the flag and the value survive compaction.
            if f.get("is_gate"):
                cf["is_gate"] = True
                if f.get("example") is not None:
                    cf["example"] = f.get("example")
            # An enum's allowed values are load-bearing for the same reason a
            # gate's example is: without them the generator emits a random token
            # and the field's XDM target populates with a meaningless value.
            if f.get("enum_values"):
                cf["enum_values"] = f.get("enum_values")
            compact.append(cf)
        out["fields"] = compact
    return out


async def data_sources_get_schema(
    data_source_id: str, compact: bool = False
) -> dict[str, Any]:
    """Return the field inventory for one data source.

    Args:
        data_source_id: composite id `<pack>/<rule>/<dataset>` —
            e.g. `FortiGate/FortiGate_1_3/fortinet_fortigate_raw`.
            Get available IDs from data_sources_list.
        compact: when True, each field carries only
            `name`/`type`/`is_array`/`is_meta` — exactly the keys the
            log-simulation worker's `schema_override` consumes — and the
            verbose `description`/`example` and base64 `logo` are dropped.
            **Set compact=True whenever you fetch this schema to pass as
            `schema_override` to `phantom_create_data_worker`.** Large
            vendors (SentinelOne ~105 fields, Zscaler ~108) exceed the
            agent's tool-result size cap with full descriptions, so the
            field list gets truncated mid-way and the worker receives an
            INCOMPLETE schema — which silently caps XDM mapping (the back
            half of the field list, where nested-JSON composites live,
            never arrives). Compact mode keeps the WHOLE field list under
            the cap. Leave False (default) only when you need
            descriptions/examples for display. The modeling-rule GATE hint
            lives in the top-level `how_to_use` (preserved in compact mode),
            so you do NOT need verbose field descriptions to seed the gate.

    Returns:
        {
          ok: bool,
          data_source: {
            id, pack_name, ..., (all the basic columns), how_to_use,
            fields: [{name, type, is_array, is_meta, description, example}, ...],
            # compact=True → fields: [{name, type, is_array, is_meta}, ...]
            delivery: "syslog" | "http",   # how synthetic logs reach Cortex
          },
        }

    `delivery` decides the sending path. "syslog" (the default) = CEF/syslog
    to the broker through phantom_create_data_worker. "http" = JSON to an
    XSIAM HTTP Log Collector through the `http-sender` connector tools
    (list_destinations, then generate_events / send_events); do NOT create a
    syslog data worker for an "http" source. Read the source's `how_to_use`
    for the profile/scenario names and the JSON shape.

    Resolves installed sources from the store; for any other catalog source
    (uninstalled, or a dataset cortex-content doesn't enumerate) it serves the
    bundled/user YAML — the same source of truth the catalog lists from.
    """
    from usecase.data_sources_store import get_data_sources_store

    store = get_data_sources_store()
    payload: dict[str, Any] | None = None
    if store is not None:
        expanded = store.get_with_schema(data_source_id)
        if expanded is not None:
            payload = expanded.to_dict()
            # The store carries no how_to_use, so enrich an installed
            # source's schema with the simulation guidance the agent reads
            # from the effective (overlay-aware) YAML, so a
            # how_to_use edit reaches the installed source too, matching the
            # uninstalled/preview path.
            parts = data_source_id.split("/")
            if len(parts) == 3:
                eff = get_data_sources_yaml_loader().get_by_3tuple(*parts)
                if eff is not None and getattr(eff, "how_to_use", None):
                    payload["how_to_use"] = eff.how_to_use
                # delivery is YAML-only; overlay it on the store payload.
                if eff is not None:
                    payload["delivery"] = getattr(eff, "delivery", "syslog")
            payload.setdefault("how_to_use", "")
            payload.setdefault("delivery", "syslog")

    if payload is None:
        # Fall back to the bundled/user YAML (source of truth) so the
        # agent can read the schema of ANY catalog source, not just installed
        # ones. Independent of store state.
        loader = get_data_sources_yaml_loader()
        parts = data_source_id.split("/")
        yaml_ds = (
            loader.get_by_3tuple(parts[0], parts[1], parts[2])
            if len(parts) == 3
            else loader.get_by_id(data_source_id)
        )
        if yaml_ds is not None:
            payload = _yaml_ds_to_schema_payload(
                yaml_ds, data_source_id, is_preview=True
            )

    if payload is None:
        return {"ok": False, "error": "not found", "data_source_id": data_source_id}

    if compact:
        payload = _compact_schema_payload(payload)
    return {"ok": True, "data_source": payload}


async def data_sources_install(
    pack_name: str,
    rule_name: str,
    dataset_name: str | None = None,
) -> dict[str, Any]:
    """Install a data source (vendor schema) from a Cortex content pack.

    Extracts the raw vendor field inventory from the pack's
    ModelingRule schema.json + persists it to the data sources store
    so log-simulation skills can use the vendor's
    actual field set instead of Rosetta's generic defaults.

    Args:
        pack_name: Cortex content pack containing the modeling rule
            (e.g. "FortiGate"). Get the list via cortex_search_packs
            or cortex_list_packs(xsiam_only=True).
        rule_name: modeling rule directory name within the pack
            (e.g. "FortiGate_1_3"). Get via cortex_list_modeling_rules.
        dataset_name: optional — when omitted, installs ALL datasets
            the rule defines (most rules have one dataset). When
            provided, installs only that dataset. For sources bundled as
            YAML, pass BOTH rule_name AND dataset_name: the HTTP-collector
            variants (`delivery: http`) share pack_name and dataset_name
            with their syslog siblings and differ ONLY in rule_name (e.g.
            Okta / OktaHttpCollector / okta_sso_raw vs the syslog Okta rule),
            so omitting dataset_name falls through to the cortex-content
            extraction path instead of the bundled YAML.

    Returns:
        {
          ok: bool,
          data_source_ids: [str, ...],     # newly-installed composite ids
          fields_count: int,
          datasets_installed: int,
          datasets_in_rule: int,
          pack_version: str | null,
        }

    Re-installing an existing data source replaces the row + field
    set (idempotent). The cascade DELETE on FK ensures no stale fields
    survive a re-install.
    """
    from usecase.data_sources_store import get_data_sources_store

    store = get_data_sources_store()
    if store is None:
        return {"ok": False, "error": "data sources store not initialized"}
    if not pack_name or not rule_name:
        return {"ok": False, "error": "pack_name and rule_name are required"}

    actor_token = set_current_actor("agent")
    try:
        try:
            # Check user-uploaded YAML first; falls back to
            # cortex-content extraction for bundled packs. Same rule as the
            # REST install endpoint: bundle YAMLs with populated `fields[]`
            # also use the YAML path, so the curated field schemas survive
            # an agent-initiated install.
            yaml_loader = get_data_sources_yaml_loader()
            yaml_ds = None
            if dataset_name is not None:
                candidate = yaml_loader.get_by_3tuple(
                    pack_name, rule_name, dataset_name,
                )
                if candidate is not None:
                    prefer_yaml = (
                        candidate.origin == "user"
                        or bool(candidate.fields)
                    )
                    if prefer_yaml:
                        yaml_ds = candidate
            if yaml_ds is not None:
                composed, meta = _compose_from_user_yaml(
                    yaml_ds, installed_by="agent",
                )
            else:
                composed, meta = await _extract_and_compose_data_sources(
                    pack_name=pack_name,
                    rule_name=rule_name,
                    dataset_name=dataset_name,
                    installed_by="agent",
                )
        except FileNotFoundError as exc:
            return {
                "ok": False,
                "error": f"cortex-content connector source missing: {exc}",
            }
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        # Resolve the audit log once; tolerate None for tests.
        a = audit_log()
        installed_ids: list[str] = []
        total_fields = 0
        for ds, fields in composed:
            store.install(ds, fields=fields)
            installed_ids.append(ds.id)
            total_fields += len(fields)
            if a is not None:
                a.record(
                    action="data_source_install",
                    target=f"data_source:{ds.id}",
                    status="success",
                    metadata={
                        "pack_name": ds.pack_name,
                        "rule_name": ds.rule_name,
                        "dataset_name": ds.dataset_name,
                        "field_count": ds.field_count,
                        "is_rawlog_only": ds.is_rawlog_only,
                        "pack_version": ds.pack_version,
                        "via": "mcp_tool",
                    },
                )
        return {
            "ok": True,
            "data_source_ids": installed_ids,
            "fields_count": total_fields,
            "datasets_installed": meta["datasets_installed"],
            "datasets_in_rule": meta["datasets_in_rule"],
            "pack_version": meta["pack_version"],
        }
    finally:
        reset_current_actor(actor_token)


async def data_sources_uninstall(
    pack_name: str,
    rule_name: str,
    dataset_name: str,
) -> dict[str, Any]:
    """Remove an installed data source (vendor schema) from the catalog.

    Counterpart to data_sources_install — same identifying triple, in
    the same order. Set this when the operator says "uninstall X" /
    "remove that data source" / "we don't need the <vendor> schema
    anymore". Catalog metadata, not a credential — this only removes
    the field schema from the installed set; it does not touch any
    connector instance or previously-generated logs.

    Args:
        pack_name: Cortex content pack the data source was installed
            from (e.g. "FortiGate"). Same value used at install time —
            get it from data_sources_list if unsure.
        rule_name: modeling rule directory name (e.g. "FortiGate_1_3").
        dataset_name: the specific dataset to remove. Required — unlike
            data_sources_install, this call always targets exactly one
            installed row; there is no "remove all datasets" shorthand.

    Returns {"ok": true, "deleted": bool, "data_source_id": str}.
    "deleted": false with a 404-shaped "error" means the data source
    wasn't installed to begin with — not a failure, just a no-op.
    """
    from usecase.data_sources_store import get_data_sources_store

    store = get_data_sources_store()
    if store is None:
        return {"ok": False, "error": "data sources store not initialized"}
    if not pack_name or not rule_name or not dataset_name:
        return {
            "ok": False,
            "error": "pack_name, rule_name, and dataset_name are required",
        }

    data_source_id = compose_data_source_id(pack_name, rule_name, dataset_name)
    actor_token = set_current_actor("agent")
    try:
        deleted = store.uninstall(data_source_id)
        a = audit_log()
        if a is not None:
            a.record(
                action="data_source_uninstall",
                target=f"data_source:{data_source_id}",
                status="success" if deleted else "not_found",
                metadata={"data_source_id": data_source_id, "via": "mcp_tool"},
            )
        if not deleted:
            return {
                "ok": True,
                "deleted": False,
                "data_source_id": data_source_id,
                "error": "not found",
            }
        return {"ok": True, "deleted": True, "data_source_id": data_source_id}
    finally:
        reset_current_actor(actor_token)


# Module-level category mapping — mirror of mcp/agent/app/data-sources/categories.ts
# so the agent's reasoning gets the same short labels the UI uses.
# Edit the TS file + this dict together when adding new badges.
_CATEGORY_LABELS = {
    "Analytics & SIEM": "SIEM",
    "Network Security": "Network",
    "Endpoint": "EDR",
    "Cloud Security": "Cloud",
    "Cloud Services": "Cloud",
    "Cloud Service Provider": "Cloud Provider",
    "Identity and Access Management": "IAM",
    "Data Enrichment & Threat Intelligence": "Threat Intel",
    "Email": "Email",
    "Vulnerability Management": "Vuln",
    "IT Services": "IT",
    "CI/CD": "DevOps",
    "Forensics": "Forensics",
    "Database": "Database",
    "Messaging": "Messaging",
    "Authentication": "Auth",
    "Utilities": "Utility",
}

# Fine-grained data-source class per pack, curated by hand
# against each pack's actual description (pack_metadata.json's coarse
# `categories[]` can't distinguish e.g. a firewall from a WAF from a
# proxy — all "Network Security"). Scenario skills that need to tell
# these apart (does the operator have a WAF vs just a firewall?) match
# on this, not `_CATEGORY_LABELS`. Valid classes: firewall, waf, proxy,
# ndr, dns, email-gateway, edr, saas, cloud, siem, vpn, lb, other.
# Extend when a newly-installed pack isn't covered — default "other" is
# safe (skills treat it as "no match for this class"), never force-fit
# an uncertain classification.
_PACK_DATA_SOURCE_CLASS: dict[str, str] = {
    "AMP": "edr",
    "AWS-CloudTrail": "cloud",
    "AWS-GuardDuty": "cloud",
    "AWS-SecurityHub": "cloud",
    "AWS_ELB": "lb",
    "AWS_WAF": "waf",
    "AbnormalSecurity": "email-gateway",
    "Absolute": "other",
    "AdminByRequest": "other",
    "Akamai_SIEM": "waf",
    "AlibabaActionTrail": "cloud",
    "ApacheTomcat": "other",
    "ApacheWebServer": "other",
    "AppSentinelsAi": "other",
    "AristaSwitch": "other",
    "Armis": "other",
    "AtlassianConfluenceCloud": "other",
    "Auditd": "other",
    "AvayaAuraCommunicationManager": "other",
    "AzureAppService": "cloud",
    "AzureDevOps": "other",
    "AzureFirewall": "firewall",
    "AzureFlowLogs": "cloud",
    "AzureKubernetesServices": "cloud",
    "AzureSecurityCenter": "cloud",
    "AzureWAF": "waf",
    "BarracudaEmailProtection": "email-gateway",
    "BarracudaWAF": "waf",
    "Barracuda_Cloudgen_Firewall": "firewall",
    "BeyondTrustPrivilegedRemoteAccess": "other",
    "BeyondTrustRemoteSupport": "other",
    "BeyondTrust_Password_Safe": "other",
    "BitSight": "other",
    "Bitbucket": "other",
    "BitwardenPasswordManager": "other",
    "BloodHoundEnterprise": "other",
    "BluecatAddressManager": "dns",
    "Box": "other",
    "BrocadeSwitch": "other",
    "CarbonBlackDefense": "edr",
    "Celonis": "other",
    "CheckpointFirewall": "firewall",
    "Cisco-umbrella-cloud-security": "dns",
    "CiscoASA": "firewall",
    "CiscoASR": "other",
    "CiscoAppDynamics": "other",
    "CiscoCatalyst": "other",
    "CiscoFirepower": "firewall",
    "CiscoISR": "other",
    "CiscoNexus": "other",
    "CiscoSMA": "email-gateway",
    "CiscoSpark": "other",
    "CiscoStealthwatch": "ndr",
    "CiscoThousandEyes": "other",
    "Cisco_Wireless_LAN_Controller": "other",
    "CitrixADC": "lb",
    "Claroty": "ndr",
    "ClearswiftDLP": "other",
    "CloudflareWAF": "waf",
    "CloudflareZeroTrust": "proxy",
    "Code42": "other",
    "CohesityHelios": "other",
    "CommvaultBackupSolutions": "other",
    "CorelightZeek": "ndr",
    "CybelAngel": "other",
    "CyberArkEPM": "other",
    "CyberArkEPV": "other",
    "CyberArkIdentity": "saas",
    "CyberArkPAS": "other",
    "CyberArk_Privileged_Threat_Analytics": "other",
    "Darktrace": "ndr",
    "DeCYFIR": "other",
    "DelineaALM": "other",
    "DelineaSS": "other",
    "DellEMCUnity": "other",
    "DigitalGuardian": "other",
    "DigitalShadows": "other",
    "Docusign": "other",
    "Dragos_Platform": "other",
    "Dropbox": "other",
    "Druva": "other",
    "DuoAdminApi": "saas",
    "Exabeam": "siem",
    "ExtraHop": "ndr",
    "F5APM": "vpn",
    "F5ASM": "waf",
    "F5BigIPAWAF": "waf",
    "F5LTM": "lb",
    "FireEyeETP": "email-gateway",
    "FireEyeHX": "edr",
    "FireEyeNX": "ndr",
    "Forcepoint": "proxy",
    "ForcepointDLP": "other",
    "ForcepointEmailSecurity": "email-gateway",
    "ForcepointSWG": "proxy",
    "ForeScoutCounterACT": "other",
    "FortiGate": "firewall",
    "FortiManager": "other",
    "Fortimail": "email-gateway",
    "FortinetFortiwebVM": "waf",
    "GenesysCloud": "other",
    "GenetecSecurityCenter": "other",
    "GitGuardian": "other",
    "GitHub": "other",
    "GitLab": "other",
    "GoogleApigee": "other",
    "GoogleChrome": "other",
    "GoogleCloudLogging": "cloud",
    "GoogleCloudSCC": "cloud",
    "GoogleDrive": "other",
    "GuardiCore": "other",
    "HPEArubaCentral": "other",
    "HPEArubaClearPass": "other",
    "HPESwitch": "other",
    "HashiCorp-Vault": "other",
    "HelloWorld": "other",
    "HuaweiFW": "firewall",
    "HuaweiNetworkDevices": "other",
    "IBMDirectoryServer": "other",
    "IBMGuardium": "other",
    "IBMMaaS360Security": "other",
    "IBMSecurityVerify": "saas",
    "IBMStorageScale": "other",
    "IBM_AIX": "other",
    "IllusiveNetworks": "other",
    "Imperva_WAF": "waf",
    "Incapsula": "waf",
    "Infoblox": "dns",
    "InfobloxBloxOne": "dns",
    "IronPort": "email-gateway",
    "IronscalesEventCollector": "email-gateway",
    "IvantiConnectSecure": "vpn",
    "IvantiPulseSecureVTM": "lb",
    "JamfProtect": "edr",
    "Jira": "other",
    "JuniperSRX": "firewall",
    "KeeperSecurity": "other",
    "Kiteworks": "other",
    "KnowBe4_KMSAT": "other",
    "Kubernetes": "other",
    "LenelS2NetBox": "other",
    "LinuxEventsCollection": "other",
    "LookoutMobileEndpointSecurity": "edr",
    "MacOS": "other",
    "ManageEngine": "other",
    "ManageEngine-ADAudit": "other",
    "ManageEngine-ADManager": "other",
    "ManageEngine-ADSelfServicePlus": "other",
    "McAfeeDatabaseSecurity": "other",
    "McAfeeNSM": "ndr",
    "McAfeeWebGateway": "proxy",
    "MicrosoftADFS": "saas",
    "MicrosoftAdvancedThreatAnalytics": "other",
    "MicrosoftCloudAppSecurity": "saas",
    "MicrosoftDHCP": "other",
    "MicrosoftDNS": "dns",
    "MicrosoftDefenderAdvancedThreatProtection": "edr",
    "MicrosoftDefenderforIdentity": "other",
    "MicrosoftECM": "other",
    "MicrosoftEntraID": "saas",
    "MicrosoftExchangeServer": "other",
    "MicrosoftGraphSecurity": "other",
    "MicrosoftIISWebServer": "other",
    "MicrosoftIntune": "other",
    "MicrosoftNPS": "other",
    "MicrosoftWSUS": "other",
    "MicrosoftWindowsAMSI": "other",
    "MicrosoftWindowsEvents": "other",
    "MicrosoftWindowsSysmon": "other",
    "Mimecast": "email-gateway",
    "Monday": "other",
    "MongoDBAtlas": "other",
    "MySQLEnterprise": "other",
    "NGINXWebServer": "other",
    "NVIDIA_DOCA_Argus": "other",
    "NasuniFileServices": "other",
    "NetBox": "other",
    "NetmotionVPN": "vpn",
    "Netskope": "proxy",
    "Office365": "saas",
    "Okta": "saas",
    "OktaASA": "other",
    "OktaAuth0": "saas",
    "OktaOAG": "vpn",
    "OneLogin": "saas",
    "OnePassword": "other",
    "Oracle": "other",
    "OracleCloudInfrastructure": "cloud",
    "Oracle_IAM": "saas",
    "Orca": "cloud",
    "Portnox": "other",
    "PrismaCloud": "cloud",
    "PrismaCloudCompute": "other",
    "PrismaSaasSecurity": "saas",
    "ProofpointCasb": "saas",
    "ProofpointEmailSecurity": "email-gateway",
    "ProofpointIsolation": "other",
    "ProofpointObserveIT": "other",
    "ProofpointServerProtection": "email-gateway",
    "ProofpointTAP": "email-gateway",
    "ProofpointThreatResponse": "other",
    "RSASecureID": "saas",
    "RadwareCloudDDoSProtectionServices": "other",
    "RadwareCloudServices": "waf",
    "ReblazeWAF": "waf",
    "RecordedFuture": "other",
    "RetarusSecureEmailGateway": "email-gateway",
    "RunZero": "other",
    "SafeNet_Trusted_Access": "saas",
    "SailPointIdentityNow": "saas",
    "Salesforce": "other",
    "SaviyntEIC": "saas",
    "SecureAuthIdentityPlatform": "saas",
    "SemperisDSP": "other",
    "SentinelOne": "edr",
    "ServiceNow": "other",
    "Shodan": "other",
    "Siemens_SiPass": "other",
    "Silverfort": "saas",
    "Slack": "other",
    "SonicWallNSv": "firewall",
    "Squid": "proxy",
    "SymantecBlueCoatProxySG": "proxy",
    "SymantecCloudSOC": "saas",
    "SymantecCloudSecureWebGateway": "proxy",
    "SymantecDLP": "other",
    "SymantecEndpointProtection": "edr",
    "SymantecEndpointSecurity": "edr",
    "SynopsysCoverity": "other",
    "Tableau": "other",
    "Tanium": "edr",
    "TaniumThreatResponse": "edr",
    "TeamViewer": "other",
    "Tenable_io": "other",
    "ThinkstCanary": "other",
    "TigeraCalico": "other",
    "Trellix_ePO": "edr",
    "TrendMicroDeepSecurity": "edr",
    "TrendMicroEmailSecurity": "email-gateway",
    "TrendMicroInterScanWebSecurity": "proxy",
    "TrendMicroTippingPoint": "ndr",
    "TrendMicroVisionOne": "edr",
    "UbiquitiUnifi": "other",
    "VMWareNSX": "other",
    "VMwareESXi": "other",
    "VMwareVCenter": "other",
    "Vectra_AI": "ndr",
    "WatchguardFirebox": "firewall",
    "WithSecure": "edr",
    "Workday": "other",
    "ZeroNetworksSegment": "other",
    "Zoom": "other",
    "Zscaler": "proxy",
    "ZscalerZPA": "vpn",
    "cisco-ise": "other",
    "cisco-meraki": "other",
    "epo": "edr",
    "jamf": "other",
    "qualys": "other",
}


async def data_sources_installed_as_vendors() -> dict[str, Any]:
    """List installed data sources as tech-stack-shaped vendor entries.

    This is the SOLE authoritative source for "what vendor/product
    literals are safe to use for log generation." A separate
    operator-declared vendor/product list could disagree with an
    installed data source's actual (Cortex-verified) vendor/product
    literal and field mapping, so vendor selection has one home.

    For each installed source, when the operator says "stream
    {vendor} {category} logs", you should:
      1. Find the entry in this response.
      2. Call data_sources_get_schema(data_source_id) to get the
         field list.
      3. Call phantom_create_data_worker with schema_override = the
         fields[] list (vendor-faithful streaming).

    Returns:
        {
          ok: bool,
          vendors: [
            {
              vendor: str,            # canonical vendor display name
              product: str,           # pack_name (matches data_sources_list)
              category: str,          # broad display label (SIEM/EDR/Network/Cloud/IAM/...)
              data_source_class: str, # fine-grained simulation class — one of
                                       # firewall/waf/proxy/ndr/dns/email-gateway/
                                       # edr/saas/cloud/siem/vpn/lb/other.
                                       # Exists because `category` alone can't
                                       # distinguish e.g. a firewall from a WAF
                                       # from a proxy (all "Network Security" at
                                       # the pack-metadata level). Scenario skills
                                       # that need to tell those apart (does the
                                       # operator have a WAF vs just a firewall?)
                                       # match on this field, not `category`.
              formats: [str, ...],    # log formats this vendor supports
                                       # (["JSON"] for delivery "http")
              delivery: str,          # "syslog" (default) | "http".
                                       # "syslog" -> phantom_create_data_worker
                                       # (CEF/syslog to the broker). "http" ->
                                       # do NOT create a data worker; use the
                                       # `http-sender` connector tools
                                       # (list_destinations, then
                                       # generate_events / send_events) and
                                       # follow the source's how_to_use.
              description: str,      # one-line vendor/product description
              source: "installed",    # marker so the agent knows where this came from
              pack_name: str,         # full identifier — feed to data_sources_get_schema
              rule_name: str,
              dataset_name: str,
              data_source_id: str,    # "<pack>/<rule>/<dataset>" — feed to schema lookup
              field_count: int,       # non-meta vendor field count
            },
          ],
          total_vendors: int,
          source: "data_sources_store",
        }
    """
    from usecase.data_sources_store import get_data_sources_store

    store = get_data_sources_store()
    if store is None:
        return {"ok": False, "error": "data sources store not initialized"}

    rows = store.list(filter=None)
    if not rows:
        return {
            "ok": True,
            "vendors": [],
            "total_vendors": 0,
            "source": "data_sources_store",
            "hint": (
                "No data sources installed yet. The operator can install "
                "vendor schemas via /data-sources Browse tab or via the "
                "data_sources_install MCP tool."
            ),
        }

    # Load vendor_map.yaml once for canonical vendor name + category enrichment.
    # baked_root defaults to None so the per-row pack_metadata lookup safely
    # short-circuits if the baked tree is unavailable for any reason.
    vendor_map: dict[str, dict] = {}
    baked_root: Path | None = None
    try:
        cortex = _load_cortex_content()
        baked_mod_name = cortex.__name__.rsplit(".", 1)[0] + "._baked_client"
        baked_mod = sys.modules.get(baked_mod_name)
        if baked_mod is None:
            spec = importlib.util.spec_from_file_location(
                baked_mod_name,
                str(_resolve_cortex_content_src() / "_baked_client.py"),
            )
            baked_mod = importlib.util.module_from_spec(spec)
            sys.modules[baked_mod_name] = baked_mod
            spec.loader.exec_module(baked_mod)
        if baked_mod.is_baked_available():
            baked_root = baked_mod.baked_root_path()
            vmap_path = baked_root / "vendor_map.yaml"
            if vmap_path.is_file():
                import yaml as _yaml
                vmap = _yaml.safe_load(vmap_path.read_text()) or {}
                # Build pack_name → vendor entry index
                for vk, info in (vmap.get("vendors") or {}).items():
                    for pack in info.get("packs") or []:
                        vendor_map[pack] = {
                            "vendor": info.get("display_name", vk),
                            "vendor_key": vk,
                        }
    except Exception as exc:
        logger.debug("vendor_map load failed in installed_as_vendors: %s", exc)

    # `delivery` is YAML-only (the install store has no column for it).
    delivery_by_id: dict[str, str] = {}
    try:
        for y in get_data_sources_yaml_loader().list_all():
            delivery_by_id[
                compose_data_source_id(y.pack_name, y.rule_name, y.dataset_name)
            ] = y.delivery
    except Exception as exc:  # noqa: BLE001 — defensive; default to syslog
        logger.debug("delivery lookup failed in installed_as_vendors: %s", exc)

    vendors_out: list[dict[str, Any]] = []
    for row in rows:
        pack = row.pack_name
        vendor_info = vendor_map.get(pack) or {"vendor": pack, "vendor_key": pack.lower()}
        # Derive category from pack_metadata.json categories[]
        category = "Other"
        description = row.pack_description or ""
        if baked_root is not None:
            try:
                meta_path = baked_root / "Packs" / pack / "pack_metadata.json"
                if meta_path.is_file():
                    import json as _json
                    meta = _json.loads(meta_path.read_text())
                    raw_categories = meta.get("categories") or []
                    if raw_categories:
                        category = _CATEGORY_LABELS.get(raw_categories[0], "Other")
                    if not description:
                        description = (meta.get("description") or "")[:200]
            except Exception:
                pass

        delivery = delivery_by_id.get(row.id, "syslog")
        vendors_out.append({
            "vendor": vendor_info["vendor"],
            "product": pack,
            "category": category,
            "data_source_class": _PACK_DATA_SOURCE_CLASS.get(pack, "other"),
            "formats": ["JSON"] if delivery == "http" else ["SYSLOG", "CEF", "JSON"],
            "delivery": delivery,
            "description": description,
            "source": "installed",
            "pack_name": row.pack_name,
            "rule_name": row.rule_name,
            "dataset_name": row.dataset_name,
            "data_source_id": row.id,
            "field_count": row.non_meta_field_count,
        })

    # Sort by vendor (alpha) then product (alpha) for stable agent reasoning
    vendors_out.sort(key=lambda v: (v["vendor"].lower(), v["product"].lower()))

    return {
        "ok": True,
        "vendors": vendors_out,
        "total_vendors": len(vendors_out),
        "source": "data_sources_store",
    }


async def data_sources_edit(
    pack_name: str,
    rule_name: str,
    dataset_name: str,
    how_to_use: str | None = None,
    fields: list[dict] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Edit a data source's curated docs/schema, creating a new version.

    Catalog-side (CLAUDE.md § Catalog boundary): edits the curated
    `how_to_use` prose and/or the schema `fields[]` list. Touches no
    secrets, so it is agent-callable. The file on disk is never mutated —
    each save is a snapshot in the version store, and the loader serves the
    newest snapshot as an overlay. On the FIRST edit of a source, the
    pristine original is preserved as version 1 (author "bundle-baseline");
    your edit becomes version 2.

    Use when the operator asks to fix, clarify, or extend a data source's
    usage guidance or field schema — e.g. "improve the how_to_use for
    ServiceNow", "add a field to the FortiGate schema". Identify the source
    via `data_sources_list` (which gives pack/rule/dataset).

    System (bundle-origin) sources ARE editable, but editing one creates an
    operator override layered on top of the shipped definition. Mention this
    to the operator when editing a system source: "the original is preserved
    as version 1; this creates an override you can roll back."

    Args:
        pack_name: Pack identifier (e.g. "ServiceNow"). From data_sources_list.
        rule_name: Rule identifier (e.g. "ServiceNow").
        dataset_name: Dataset identifier (e.g. "servicenow_servicenow_raw").
        how_to_use: Optional. Replacement markdown for the usage section.
            Omit to leave the current text unchanged.
        fields: Optional. Replacement schema columns — a list of objects, each
            {name, type, description?, example?, is_meta?, is_array?}. Field
            names must be unique and non-empty. Replaces the whole field list;
            omit to leave the schema unchanged.
        note: Optional. A short changelog note stored with this version.

    Example payload (clarify ServiceNow usage):
        {
          "pack_name": "ServiceNow", "rule_name": "ServiceNow",
          "dataset_name": "servicenow_servicenow_raw",
          "how_to_use": "Stream ServiceNow audit events as CEF over syslog...",
          "note": "clarified broker setup"
        }

    Returns:
        {ok: True, version: int, data_source_id: str, installed_schema_synced: bool}
        on success, or {ok: False, error: str} if the source is unknown or the
        edit fails schema validation (e.g. duplicate field names). No version is
        written on failure. installed_schema_synced is True when the source was
        installed and its served schema was updated to match this edit, so
        vendor-faithful simulation uses the edited schema immediately.
    """
    return _apply_edit(
        pack_name,
        rule_name,
        dataset_name,
        how_to_use=how_to_use,
        fields=fields,
        note=note,
        author="agent",
    )


async def data_sources_list_versions(
    pack_name: str,
    rule_name: str,
    dataset_name: str,
) -> dict[str, Any]:
    """Inspect a data source's edit history.

    Returns every saved version with its author, change note, and timestamp,
    newest marked current. Use this to see what changed and to pick a version
    number for `data_sources_rollback`. A source that has never been edited
    returns an empty list (it is served straight from its bundled/uploaded
    file). Identify the source via `data_sources_list` (pack/rule/dataset).

    Args:
        pack_name: Pack identifier (e.g. "ServiceNow"). From data_sources_list.
        rule_name: Rule identifier (e.g. "ServiceNow").
        dataset_name: Dataset identifier (e.g. "servicenow_servicenow_raw").

    Returns:
        {ok: True, data_source_id: str, versions: [
            {version: int, author: str, note: str|None,
             created_at: str, is_current: bool}, ...]}
        Versions are ordered oldest→newest. Version 1 (author
        "bundle-baseline") is the pristine original on any edited source.
    """
    from usecase.data_source_versions_store import get_data_source_versions_store

    ds_id = compose_data_source_id(pack_name, rule_name, dataset_name)
    store = get_data_source_versions_store()
    rows = store.list_versions(ds_id) if store is not None else []
    versions = [
        {
            "version": r["version"],
            "author": r["author"],
            "note": r["note"],
            "created_at": r["created_at"],
            "is_current": bool(r["is_current"]),
        }
        for r in rows
    ]
    return {"ok": True, "data_source_id": ds_id, "versions": versions}


async def data_sources_rollback(
    pack_name: str,
    rule_name: str,
    dataset_name: str,
    version: int,
) -> dict[str, Any]:
    """Roll a data source back to a prior version.

    Non-destructive: the target version is copied forward as a NEW current
    version; the intervening versions stay in history, so you can always roll
    forward again. Call `data_sources_list_versions` first to choose the
    version number. Works for system (bundle) and user sources alike — a
    rollback on a system source is an operator override, same as an edit.

    Args:
        pack_name: Pack identifier (e.g. "ServiceNow"). From data_sources_list.
        rule_name: Rule identifier (e.g. "ServiceNow").
        dataset_name: Dataset identifier (e.g. "servicenow_servicenow_raw").
        version: The version number to roll back to (from
            data_sources_list_versions).

    Example payload (revert ServiceNow to its original):
        {"pack_name": "ServiceNow", "rule_name": "ServiceNow",
         "dataset_name": "servicenow_servicenow_raw", "version": 1}

    Returns:
        {ok: True, version: int, data_source_id: str, installed_schema_synced: bool}
        — `version` is the NEW current version created by the rollback, and
        installed_schema_synced is True when an installed source's served schema
        was updated to match the rolled-back version. On failure (unknown
        version, or a source with no version history): {ok: False, error: str}.
    """
    return _apply_rollback(
        pack_name,
        rule_name,
        dataset_name,
        version=version,
        author="agent",
    )


# ─── helpers ──────────────────────────────────────────────────────


async def _json_body(
    request: Request,
) -> dict[str, Any] | JSONResponse:
    """Parse JSON request body; return JSONResponse(400) on error."""
    try:
        body = await request.json()
    except Exception as exc:
        return JSONResponse(
            {"error": f"invalid JSON body: {exc}"},
            status_code=400,
        )
    if not isinstance(body, dict):
        return JSONResponse(
            {"error": "body must be a JSON object"},
            status_code=400,
        )
    return body


def _canonical_yaml_bytes(doc: dict[str, Any]) -> bytes:
    """Serialize a YAML doc to canonical bytes for hashing.

    Used by the user-upload preview→commit accept_token flow to verify
    the operator submits the exact same bytes at commit that were
    validated at preview. We use JSON with sorted keys + no whitespace
    rather than YAML's safe_dump because YAML serialization is
    indentation-sensitive and PyYAML's output isn't byte-stable across
    versions; JSON with sort_keys=True is canonical by definition.

    The hash isn't a security boundary (operator is already
    bearer-authenticated); it's a sanity check that the YAML wasn't
    silently mutated by an intermediary."""
    import json as _json
    return _json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
