"""Data sources YAML loader.

Loads `data_source.yaml` files from two storage roots:

  • BUNDLE root  — `bundles/spark/data-sources/<id>/data_source.yaml` in dev
                   (`/app/bundle/data-sources/<id>/data_source.yaml` in container)
                   ships in the agent image; read-only at runtime

  • USER root    — `/app/data/user_data_sources/<id>/data_source.yaml`
                   operator-uploaded; writable; persists across container
                   restarts via the `phantom_mcp_data` volume.

The loader joins both into a unified catalog. Collision rule:
**bundle always wins** for the same id. Operators can't override bundled
packs; their custom data sources must use new ids.

# Why a separate module

The data_sources.py route handlers already do install + uninstall against
the SQLite `data_sources_store`. That code path is for INSTALLED state
(schemas extracted from cortex-content, persisted to the store at install
time). The YAML loader is for AVAILABILITY state (what's on disk to browse
+ install). Different lifecycle, different domain — separated cleanly per
the canonical-state discipline (root CLAUDE.md § Rule 1: one state
surface = one storage home).

# Boundary check

The loader is CATALOG-side state per CLAUDE.md § Catalog boundary ≠
credential boundary. The YAML it reads/writes contains:
  • vendor names, product names, descriptions, categories
  • field inventories (for user-uploaded sources)
  • base64-encoded logo bytes
None of these are secrets. The agent gets a `data_sources_list_yaml`
MCP tool that reads;
the write path stays REST-only because uploading is an explicit
operator action with a similarity-check prompt the agent shouldn't
auto-confirm.

# Tests

Unit tests cover: list/get round-trip, bundle-wins collision rule, YAML
validation against `data_source.schema.json`, user-write atomicity,
deletion idempotency. Integration with the catalog endpoint lives in
`tests/test_data_sources_api.py`.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("Phantom MCP")

# A Cortex modeling-rule version suffix: digits and underscores only, e.g. the
# "_1_3" in "FortiGate_1_3". See `_get_by_3tuple_version_tolerant`.
_VERSION_SUFFIX_RE = re.compile(r"^[0-9]+(_[0-9]+)*$")


# ─── Path resolution ───────────────────────────────────────────────


def resolve_bundle_root() -> Path:
    """Find the bundled data-sources root (read-only at runtime).

    Container layout (production):  /app/bundle/data-sources/
    Source-tree layout (dev/tests): <repo>/bundles/spark/data-sources/

    Override via env `PHANTOM_DATA_SOURCES_BUNDLE_ROOT` (tests use this).
    """
    override = os.environ.get("PHANTOM_DATA_SOURCES_BUNDLE_ROOT")
    if override:
        return Path(override)
    container = Path("/app/bundle/data-sources")
    if container.is_dir():
        return container
    # Walk up from this file:
    # bundles/spark/mcp/src/usecase/data_sources_yaml_loader.py
    # parents[0] = usecase, [1] = src, [2] = mcp, [3] = spark
    # → bundles/spark/data-sources/
    return Path(__file__).resolve().parents[3] / "data-sources"


def resolve_user_root() -> Path:
    """Resolve the user-uploaded data-sources root path.

    Container layout: /app/data/user_data_sources/
    Tests: override via env `PHANTOM_DATA_SOURCES_USER_ROOT`.

    Does NOT create the directory — callers that write use `write_user`
    which mkdir's lazily. Read-only callers (list_user, get_user) handle
    missing-dir gracefully by returning empty results.
    """
    override = os.environ.get("PHANTOM_DATA_SOURCES_USER_ROOT")
    return Path(override) if override else Path("/app/data/user_data_sources")


# ─── Schema validation ─────────────────────────────────────────────


def resolve_schema_path() -> Path:
    """Find data_source.schema.json (next to the bundled YAMLs)."""
    return resolve_bundle_root() / "data_source.schema.json"


_schema_cache: dict[str, Any] | None = None


def load_schema() -> dict[str, Any]:
    """Cached JSON Schema load."""
    global _schema_cache
    if _schema_cache is None:
        path = resolve_schema_path()
        if not path.is_file():
            raise FileNotFoundError(f"data_source.schema.json not found at {path}")
        _schema_cache = json.loads(path.read_text())
    return _schema_cache


def validate_yaml_doc(doc: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate a YAML doc against data_source.schema.json.

    Returns (ok, errors). errors is a list of human-readable messages
    suitable for displaying in the operator upload modal.
    """
    try:
        import jsonschema
    except ImportError:
        # In environments without jsonschema (very rare — we add it to CI
        # and the agent image), fall back to a minimal structural check.
        logger.warning("jsonschema not installed; running minimal validation only")
        return _validate_minimal(doc)

    schema = load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if not errors:
        return True, []
    msgs = []
    for err in errors:
        path = ".".join(str(p) for p in err.path) or "<root>"
        msgs.append(f"{path}: {err.message}")
    return False, msgs


def _validate_minimal(doc: dict[str, Any]) -> tuple[bool, list[str]]:
    """Fallback validation when jsonschema isn't available."""
    required = ["schema_version", "id", "pack_name", "rule_name",
                "dataset_name", "vendor", "product", "fields"]
    missing = [k for k in required if k not in doc]
    if missing:
        return False, [f"missing required field(s): {', '.join(missing)}"]
    if doc.get("schema_version") != 1:
        return False, [f"schema_version must be 1, got {doc.get('schema_version')}"]
    return True, []


# ─── Delivery ────────────────────────────────────────────────

DEFAULT_DELIVERY = "syslog"
VALID_DELIVERIES = ("syslog", "http", "wec")


def normalize_delivery(value: Any) -> str:
    """Return a valid `delivery` value; anything unrecognised -> "syslog"."""
    return value if isinstance(value, str) and value in VALID_DELIVERIES else DEFAULT_DELIVERY


# ─── Loader dataclass ──────────────────────────────────────────────


@dataclass
class YamlDataSource:
    """In-memory representation of one data_source.yaml file."""

    id: str
    pack_name: str
    rule_name: str
    dataset_name: str
    vendor: str
    product: str
    description: str = ""
    # Operator-facing instructions for simulation: multi-dataset
    # handling, CEF vs JSON wire format selection, sentinel values, MR-fire
    # requirements, lessons learned from per-vendor validation. Multi-line markdown.
    how_to_use: str = ""
    categories: list[str] = field(default_factory=list)
    version: str = ""
    origin: str = "bundle"  # "bundle" | "user"
    author: str = ""
    uploaded_by: str | None = None
    created_at: str = ""
    updated_at: str = ""
    logo: dict[str, Any] | None = None
    formats: list[str] = field(default_factory=lambda: ["SYSLOG", "CEF", "JSON"])
    is_rawlog_only: bool = False
    fields: list[dict[str, Any]] = field(default_factory=list)
    # No xdm_mappings field: data sources are vendor-neutral specs and XDM
    # is Cortex-specific.
    # Operator-curated product-type labels per vendor.
    # Single source of truth: `scripts/curate_vendor_use_cases.py`'s
    # CURATION dict. Canonical values enumerated in CANONICAL_USE_CASES
    # in the same script. UI surfaces these as filter chips + card
    # badges, replacing the XSIAM platform `categories` for the badge
    # role (categories remains as backend metadata for now).
    use_cases: list[str] = field(default_factory=list)
    # When true, the vendor has been smoke-tested end-to-end
    # via the stream_simulate_to_xsiam skill (or equivalent automated
    # path) and the simulation → broker → XSIAM raw landing pipeline
    # is known to work. UI renders a small green "Validated" pill on
    # the Browse-page row so operators can scan for vendors we know
    # are operational. The flag is set in YAML by
    # `scripts/maintainer/enrich_validated_yamls_v2.py`.
    validated: bool = False
    # RAW-validated tier: pack not installed on the tenant, but a raw
    # dataset query confirmed the synthetic data lands the exact field names the
    # rule would read. Proven-correct shape, ready-to-map. Renders the amber
    # "Raw Validated" pill. Mutually exclusive with `validated` (the MAPPING tier).
    raw_validated: bool = False
    # How synthetic logs reach Cortex for this source. "syslog" (default)
    # = CEF/syslog to the broker via phantom_create_data_worker. "http" = JSON
    # to an XSIAM HTTP Log Collector via the `http-sender` bundle connector.
    # Optional in the YAML; absent == "syslog" and stays absent on round-trip.
    delivery: str = "syslog"

    # Provenance for the loader (not part of the YAML schema)
    _source_path: Path | None = None
    _source_root: str = ""  # "bundle" | "user"

    @classmethod
    def from_doc(cls, doc: dict[str, Any], source_path: Path, source_root: str) -> YamlDataSource:
        """Build from a parsed YAML doc + provenance."""
        return cls(
            id=doc["id"],
            pack_name=doc["pack_name"],
            rule_name=doc["rule_name"],
            dataset_name=doc["dataset_name"],
            vendor=doc["vendor"],
            product=doc["product"],
            description=doc.get("description", "") or "",
            how_to_use=doc.get("how_to_use", "") or "",
            categories=list(doc.get("categories") or []),
            version=doc.get("version", "") or "",
            origin=doc.get("origin", "bundle"),
            author=doc.get("author", "") or "",
            uploaded_by=doc.get("uploaded_by"),
            created_at=doc.get("created_at", "") or "",
            updated_at=doc.get("updated_at", "") or "",
            logo=doc.get("logo"),
            formats=list(doc.get("formats") or ["SYSLOG", "CEF", "JSON"]),
            is_rawlog_only=bool(doc.get("is_rawlog_only", False)),
            fields=list(doc.get("fields") or []),
            use_cases=list(doc.get("use_cases") or []),
            validated=bool(doc.get("validated", False)),
            raw_validated=bool(doc.get("raw_validated", False)),
            delivery=normalize_delivery(doc.get("delivery")),
            _source_path=source_path,
            _source_root=source_root,
        )

    def to_doc(self) -> dict[str, Any]:
        """Serialize back to a YAML-ready dict.

        The dataclass's private `_source_*` fields are dropped (they're
        loader-internal, not part of the on-disk schema)."""
        doc: dict[str, Any] = {
            "schema_version": 1,
            "id": self.id,
            "pack_name": self.pack_name,
            "rule_name": self.rule_name,
            "dataset_name": self.dataset_name,
            "vendor": self.vendor,
            "product": self.product,
            "description": self.description,
            "how_to_use": self.how_to_use,
            "categories": self.categories,
            "version": self.version,
            "origin": self.origin,
            "author": self.author,
            "uploaded_by": self.uploaded_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "logo": self.logo,
            "formats": self.formats,
            "is_rawlog_only": self.is_rawlog_only,
            "fields": self.fields,
            "use_cases": self.use_cases,
            "validated": self.validated,
            "raw_validated": self.raw_validated,
        }
        # Optional key: omitted for the default so existing sources
        # round-trip byte-identically.
        if self.delivery != DEFAULT_DELIVERY:
            doc["delivery"] = self.delivery
        return doc

    def to_catalog_row(self, installed: bool = False) -> dict[str, Any]:
        """Render in the legacy catalog row shape so the UI doesn't change.

        Mirrors the catalog.json row format the UI expects;
        adds `origin` for the "User upload" badge."""
        return {
            "pack_name": self.pack_name,
            "rule_name": self.rule_name,
            "dataset_name": self.dataset_name,
            "supported_modules": ["xsiam"],  # All bundled are XSIAM; user packs default same
            "pack_description": self.description,
            "currentVersion": self.version,
            "is_rawlog_only": self.is_rawlog_only,
            "field_count": len(self.fields),
            "non_meta_field_count": len([f for f in self.fields if not f.get("is_meta", False)]),
            "logo_url": self._compute_logo_url(),
            "logo_type": (self.logo or {}).get("mime_type", "").replace("image/", "") or "svg",
            "installed": installed,
            "vendor_key": _slugify(self.vendor).lower(),
            "vendor_display_name": self.vendor,
            "vendor_primary_color": "#5F6368",  # Will be overridden by enrichment for bundle
            "categories": self.categories,
            "use_cases": self.use_cases,
            "origin": self.origin,
            # Surface validated flag so the BrowseRow can
            # render a small green "Validated" pill on rows we've
            # smoke-tested end-to-end.
            "validated": self.validated,
            "raw_validated": self.raw_validated,
            # "syslog" | "http" | "wec". Lets the UI/agent tell an
            # HTTP-collector source (http-sender connector) or a WEC source
            # (wec-sender connector) from a syslog/CEF one.
            "delivery": self.delivery,
            "id": self.id,
        }

    def _compute_logo_url(self) -> str | None:
        """Return the agent-side URL the UI fetches the logo from.

        Returns `None` when the YAML has no inline logo. That tells the UI
        to render the placeholder icon directly, without round-tripping a
        request that's guaranteed to 404.

        The YAML's `logo:` block is the single source of truth for the logo.

        Why drop the legacy `/logo/<pack>` URL from catalog output:
          - Returning this URL for EVERY bundle pack makes the UI request
            it for vendors with no baked asset; those 404 and show up as
            empty panels or placeholder icons. The request is wasted
            bandwidth and the network noise makes first-page load feel slow.
          - The legacy route remains live on the MCP for backward
            compat with older agent images, but new catalogs no
            longer point to it.

        Returns:
          - `/api/agent/data-sources/inline-logo/<id>` when YAML
             has inline base64 logo data.
          - `None` otherwise. UI renders the placeholder icon.
        """
        if self.logo:
            return f"/api/agent/data-sources/inline-logo/{self.id}"
        return None


# ─── Loader operations ─────────────────────────────────────────────


class DataSourcesYamlLoader:
    """Reads + writes data_source.yaml files across bundle and user roots.

    The loader is process-shared (instantiated once at MCP boot, wired
    into the catalog endpoint).

    Per-root scan cache, invalidated on directory mtime change. Without
    it, every catalog + inline-logo request re-parses all bundled YAMLs
    (seconds per request, and a very slow first paint when the UI
    fetches one logo per vendor card). With it, the bundle
    scan happens once at first request and is reused until the YAML
    directory's mtime advances; user-upload endpoints call
    `invalidate()` to bust the cache after a write.

    The cache is in-memory only (per worker process). Container
    restart re-scans the YAMLs — that's by design; YAMLs ARE the
    source of truth and shouldn't be shadowed by an obsolete snapshot.
    """

    def __init__(
        self,
        bundle_root: Path | None = None,
        user_root: Path | None = None,
    ) -> None:
        self.bundle_root = bundle_root or resolve_bundle_root()
        self.user_root = user_root or resolve_user_root()
        # Per-root scan cache: keyed by root path; value is
        # (mtime_ns_at_scan, list[YamlDataSource]). A subsequent call
        # restats the root dir; if mtime hasn't moved, return the cached
        # list. If mtime advanced (entry added/removed), re-scan.
        self._scan_cache: dict[str, tuple[int, list[YamlDataSource]]] = {}
        # `get_by_id` accelerator: dict[id → ds] from the last
        # successful list_all() scan. Rebuilt whenever the underlying
        # roots scan-cache is invalidated.
        self._id_index: dict[str, YamlDataSource] | None = None

    def _load_one(self, yaml_path: Path, origin: str) -> YamlDataSource | None:
        """Parse one data_source.yaml. Returns None on error (logged)."""
        try:
            import yaml
            doc = yaml.safe_load(yaml_path.read_text())
            if not isinstance(doc, dict):
                logger.warning("data_source.yaml at %s is not a dict; skipping", yaml_path)
                return None
            # Stamp origin if not set in YAML (defensive — migration sets it)
            doc.setdefault("origin", origin)
            return YamlDataSource.from_doc(doc, yaml_path, origin)
        except Exception as exc:
            logger.warning("failed to load %s: %s", yaml_path, exc)
            return None

    def _root_mtime_ns(self, root: Path) -> int:
        """Directory mtime — moves when entries are added/removed.

        Returns 0 when the root doesn't exist (empty bundle / no user
        uploads yet). The cache stays valid until something appears.
        """
        try:
            return root.stat().st_mtime_ns
        except FileNotFoundError:
            return 0

    def _scan_root(self, root: Path, origin: str) -> list[YamlDataSource]:
        """Walk a root dir; collect every `<id>/data_source.yaml`.

        Caches per-root by directory mtime. Re-scans only when the
        root's mtime advances (entry added or removed at the top level).
        Modifying an EXISTING YAML's contents doesn't bump the parent
        dir's mtime — but that path runs through `write_user()` which
        explicitly invalidates anyway.
        """
        key = str(root)
        mtime = self._root_mtime_ns(root)
        cached = self._scan_cache.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        if not root.is_dir():
            self._scan_cache[key] = (mtime, [])
            # Drop stale id-index — list_all() will rebuild on next call.
            self._id_index = None
            return []

        out: list[YamlDataSource] = []
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            yaml_path = entry / "data_source.yaml"
            if not yaml_path.is_file():
                continue
            ds = self._load_one(yaml_path, origin)
            if ds is not None:
                out.append(ds)
        self._scan_cache[key] = (mtime, out)
        # Drop stale id-index — list_all() will rebuild on next call.
        self._id_index = None
        return out

    def invalidate(self) -> None:
        """Bust the per-root scan cache. Called from upload/delete
        endpoints that write to user_root, in case the directory mtime
        is sub-resolution close (some filesystems quantize to 1 s).
        """
        self._scan_cache.clear()
        self._id_index = None

    def list_all(self) -> list[YamlDataSource]:
        """Return every data source from both roots. Bundle wins on id collision."""
        bundle_sources = self._scan_root(self.bundle_root, "bundle")
        user_sources = self._scan_root(self.user_root, "user")
        bundle_ids = {s.id for s in bundle_sources}
        # Filter user sources whose id collides with a bundle source — bundle wins
        user_filtered = [s for s in user_sources if s.id not in bundle_ids]
        if len(user_filtered) < len(user_sources):
            dropped = {s.id for s in user_sources} - {s.id for s in user_filtered}
            logger.info(
                "data sources: %d user uploads shadowed by bundle ids: %s",
                len(dropped), sorted(dropped),
            )
        return self._apply_version_overlay(bundle_sources + user_filtered)

    def _apply_version_overlay(
        self, sources: list[YamlDataSource]
    ) -> list[YamlDataSource]:
        """Overlay the version store's current snapshot onto each source
        that has been edited. Keyed by the composite id (pack/rule/dataset),
        matching the store. Bundle/user files are never mutated; an un-edited
        source is returned unchanged. Degrades to the file source on any error
        (the source still loads, just without the overlay).
        """
        from usecase.data_source_versions_store import (
            get_data_source_versions_store,
        )

        store = get_data_source_versions_store()
        if store is None:
            return sources
        try:
            current = store.all_current()  # {composite_id: yaml_snapshot}
            if not current:
                return sources
            import yaml

            from usecase.data_sources_store import compose_data_source_id

            out: list[YamlDataSource] = []
            for s in sources:
                cid = compose_data_source_id(
                    s.pack_name, s.rule_name, s.dataset_name
                )
                snap = current.get(cid)
                if snap is None:
                    out.append(s)
                    continue
                try:
                    doc = yaml.safe_load(snap) or {}
                    out.append(
                        YamlDataSource.from_doc(doc, s._source_path, s._source_root)
                    )
                except Exception:
                    logger.exception(
                        "version overlay parse failed for %s; serving file", cid
                    )
                    out.append(s)
            return out
        except Exception:
            logger.exception("version-store overlay failed; serving file sources")
            return sources

    def list_user(self) -> list[YamlDataSource]:
        """Operator-uploaded sources only (for the upload-management UI)."""
        return self._scan_root(self.user_root, "user")

    def get_by_id(self, ds_id: str) -> YamlDataSource | None:
        """Lookup one source by id. Bundle wins on collision.

        Uses an id-indexed dict built lazily from list_all()
        so the inline-logo route is O(1) lookup, not O(N) linear scan.
        Index invalidates when the per-root scan cache invalidates.
        """
        if self._id_index is None:
            self._id_index = {ds.id: ds for ds in self.list_all()}
        return self._id_index.get(ds_id)

    def get_user(self, ds_id: str) -> YamlDataSource | None:
        """User-only lookup. Returns None if no user upload exists for this id."""
        path = self.user_root / ds_id / "data_source.yaml"
        if not path.is_file():
            return None
        return self._load_one(path, "user")

    def get_by_3tuple(
        self,
        pack_name: str,
        rule_name: str,
        dataset_name: str,
    ) -> YamlDataSource | None:
        """Lookup by (pack_name, rule_name, dataset_name).

        Used by the install path to decide between user-YAML-based install
        and cortex-content-based install, and by edit/rollback/versions to
        resolve an installed row back to its catalog entry. Bundle wins on
        the rare case where bundle + user share the same 3-tuple (per the
        same collision rule as get_by_id).
        """
        for ds in self.list_all():
            if (
                ds.pack_name == pack_name
                and ds.rule_name == rule_name
                and ds.dataset_name == dataset_name
            ):
                return ds
        return self._get_by_3tuple_version_tolerant(pack_name, rule_name, dataset_name)

    def _get_by_3tuple_version_tolerant(
        self,
        pack_name: str,
        rule_name: str,
        dataset_name: str,
    ) -> YamlDataSource | None:
        """Fallback for `get_by_3tuple`: tolerate a Cortex-style version suffix on `rule_name`.

        Cortex's own modeling-rule directory names carry a version ("FortiGate_1_3",
        "ZscalerModelingRule_1_3") that the bundled catalog's `rule_name` never does
        ("FortiGate", "ZscalerModelingRule") -- `cortex_list_modeling_rules` is where an
        agent read that versioned name from, and `data_sources_install` passes it straight
        through. Measured 2026-10-18 (test-findings F21): every data source installed this
        way permanently failed the exact-match lookup above, which broke Edit guidance /
        Rollback / version History for the installed row (the catalog YAML could never be
        found again), and silently skipped the bundled YAML's richer fields (descriptions,
        examples) in favor of the thinner cortex-extracted ones during install.

        Matches only when the candidate's own `rule_name` is a strict prefix of the given
        one, immediately followed by `_` and a version-shaped remainder (digits and
        underscores only), and exactly one such candidate exists for this pack+dataset.
        The strict-prefix requirement is what keeps this safe for the documented
        HTTP/WEC-delivery siblings that share a pack_name and dataset_name but differ in
        rule_name (e.g. "OktaHttpCollector" vs "OktaModelingRules" for Okta/okta_sso_raw):
        neither is a prefix of the other, so they never collide here.
        """
        candidates = [
            ds
            for ds in self.list_all()
            if ds.pack_name == pack_name
            and ds.dataset_name == dataset_name
            and rule_name.startswith(ds.rule_name + "_")
            and _VERSION_SUFFIX_RE.match(rule_name[len(ds.rule_name) + 1 :])
        ]
        return candidates[0] if len(candidates) == 1 else None

    def write_user(self, doc: dict[str, Any]) -> tuple[YamlDataSource | None, list[str]]:
        """Validate + write a user-uploaded YAML to disk.

        Returns (YamlDataSource | None, errors). On success the returned
        YamlDataSource has `_source_root="user"` and `_source_path` set.

        Refuses to overwrite a bundled id (raises ValueError); a user upload
        targeting the same id will be filtered out by `list_all()` anyway,
        but we surface the collision at write time so the operator gets a
        clear error instead of a silently-shadowed source.
        """
        # Defensive — force user origin + timestamps
        now = _now_iso()
        doc.setdefault("schema_version", 1)
        doc["origin"] = "user"
        doc.setdefault("author", "operator")
        doc.setdefault("created_at", now)
        doc["updated_at"] = now

        ok, errors = validate_yaml_doc(doc)
        if not ok:
            return None, errors

        ds_id = doc["id"]
        # Bundle-collision check
        bundle_yaml = self.bundle_root / ds_id / "data_source.yaml"
        if bundle_yaml.is_file():
            return None, [
                f"id '{ds_id}' is reserved by a bundled data source. "
                f"Choose a different id (the id is a free-form slug — "
                f"e.g. add an operator-prefix)."
            ]

        target_dir = self.user_root / ds_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "data_source.yaml"

        try:
            import yaml
            with target_path.open("w") as f:
                yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False, width=120)
        except Exception as exc:
            return None, [f"write failed: {exc}"]

        # Bust the per-root scan cache so the next list_all()
        # picks up this new upload immediately. Directory-mtime detection
        # usually catches the change on its own, but ext4 + macOS APFS
        # quantize mtime to 1 s — a same-second upload + immediate read
        # would otherwise serve stale data.
        self.invalidate()

        return YamlDataSource.from_doc(doc, target_path, "user"), []

    def update_user(
        self, ds_id: str, doc: dict[str, Any],
    ) -> tuple[YamlDataSource | None, list[str]]:
        """Validate + overwrite an EXISTING user-uploaded YAML on disk.

        Backs the PUT /api/v1/data-sources/user/{id} endpoint.

        Differences from `write_user`:
          * The target YAML at `<user_root>/<ds_id>/data_source.yaml` MUST
            already exist. Returns (None, ["not found"]) if not — the route
            translates that to HTTP 404.
          * The body's `id` MUST equal the path-arg `ds_id`. PUT is not a
            rename — operators wanting to change the id should delete +
            re-upload. Returns (None, [...]) on mismatch — HTTP 409.
          * `created_at` is preserved from the existing on-disk YAML (an
            edit does not reset creation time). `updated_at` is refreshed
            to now.
          * Bundle-collision still applies — if the id is also a bundled
            pack id, refuse the edit (defense-in-depth; the original
            upload should already have been refused by write_user).
        """
        ds_id = ds_id or ""
        if "/" in ds_id or ".." in ds_id or ds_id.startswith("."):
            return None, [f"invalid id '{ds_id}'"]

        target_path = self.user_root / ds_id / "data_source.yaml"
        if not target_path.is_file():
            return None, [f"user data source '{ds_id}' not found"]

        # Body id MUST match path id — PUT is not rename.
        body_id = doc.get("id")
        if not body_id or body_id != ds_id:
            return None, [
                f"id mismatch: path is '{ds_id}' but body id is "
                f"'{body_id!r}'. PUT does not rename — to change the id, "
                f"delete the source and re-upload."
            ]

        # Bundle-collision defensive check (same as write_user). Should
        # never trip during update_user because the original write_user
        # would have refused; included for symmetry.
        bundle_yaml = self.bundle_root / ds_id / "data_source.yaml"
        if bundle_yaml.is_file():
            return None, [
                f"id '{ds_id}' is reserved by a bundled data source. "
                f"This user upload should not exist; delete + re-upload "
                f"with a different id."
            ]

        # Preserve created_at from existing YAML; force user origin +
        # refresh updated_at. The operator's body may or may not have
        # touched these — server is source of truth for both.
        try:
            import yaml as _yaml
            with target_path.open() as f:
                existing = _yaml.safe_load(f) or {}
        except Exception as exc:
            return None, [f"failed to read existing YAML: {exc}"]
        preserved_created = existing.get("created_at")
        now = _now_iso()
        doc.setdefault("schema_version", 1)
        doc["origin"] = "user"
        doc.setdefault("author", existing.get("author", "operator"))
        if preserved_created:
            doc["created_at"] = preserved_created
        else:
            doc.setdefault("created_at", now)
        doc["updated_at"] = now

        ok, errors = validate_yaml_doc(doc)
        if not ok:
            return None, errors

        try:
            import yaml
            with target_path.open("w") as f:
                yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False, width=120)
        except Exception as exc:
            return None, [f"write failed: {exc}"]

        # Same cache-invalidation discipline as write_user/delete_user
        # (directory-mtime detection is fine but ext4/APFS
        # second-quantization means a same-second read could miss).
        self.invalidate()

        return YamlDataSource.from_doc(doc, target_path, "user"), []

    def delete_user(self, ds_id: str) -> bool:
        """Remove a user-uploaded data source. Returns True if existed.

        Removes the entire `<user_root>/<id>/` directory (in case future
        sidecar files like `logo_light.svg` get written next to the YAML).
        Bundle ids are refused (raises ValueError) — the operator can't
        delete what they didn't upload.
        """
        # Bundle-protection: refuse to delete anything under bundle_root
        if (self.bundle_root / ds_id).exists():
            raise ValueError(
                f"id '{ds_id}' is bundled; only user-uploaded sources can be deleted"
            )
        target = self.user_root / ds_id
        if not target.exists():
            return False
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        # Bust the cache after delete (same reason as save_user)
        self.invalidate()
        return True


# ─── Helpers ───────────────────────────────────────────────────────


def _slugify(s: str, max_len: int = 128) -> str:
    """Mirror of the migration script's slugify so ids stay stable."""
    s = re.sub(r"[^A-Za-z0-9_.-]", "-", s).strip("-_.")
    return s[:max_len] or "unknown"


def _now_iso() -> str:
    """ISO-8601 UTC second-precision timestamp."""
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


# ─── Process-shared singleton ──────────────────────────────────────
#
# main.py wires one loader at boot via `set_data_sources_yaml_loader`.
# All other code reaches it via `get_data_sources_yaml_loader()`.
# Same pattern as `data_sources_store._singleton`.


_singleton: DataSourcesYamlLoader | None = None


def set_data_sources_yaml_loader(loader: DataSourcesYamlLoader | None) -> None:
    """Wire the process-global loader. Pass None to clear (tests use this)."""
    global _singleton
    _singleton = loader


def get_data_sources_yaml_loader() -> DataSourcesYamlLoader:
    """Resolve the process-global loader. Auto-creates with default roots
    if not yet wired (so unit tests that don't call set_* still work)."""
    global _singleton
    if _singleton is None:
        _singleton = DataSourcesYamlLoader()
    return _singleton
