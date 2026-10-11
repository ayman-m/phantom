"""KbLoader — boot-time ingestion of the bundle's knowledge bases.

Per `manifest.yaml:knowledge.bundled[]`, each entry declares:

    knowledge:
      bundled:
        - name: "phantom-soc"
          path: "./kbs/phantom-soc/"
          schema: "./kbs/phantom-soc/schema.json"

The loader walks each bundled KB's directory, parses every supported
file into a (doc_id, metadata, content) triple, and upserts it into
the `SqliteKnowledgeBase`. Idempotent: docs whose source_hash matches
the persisted hash are skipped (no re-embed).

# Supported file formats

  - **Markdown with YAML frontmatter** (`.md`): the canonical format.
    Frontmatter becomes `metadata`; body becomes `content`.
  - **JSON** (`.json`, except `schema.json`): the entire object is
    the metadata; the `content` field (if present) or the JSON-
    stringified body is the searchable content.

Files outside this set are skipped with a debug log.

# Doc-id derivation

Preferred: the frontmatter's `id` field (per `schema.json:required`).
Fallback: the file's relative path, sans extension. Either way the id
is stable across boots, which the loader relies on for change
detection (a renamed file is a delete + insert).

# Schema validation

The bundle's `schema.json` is loaded once. For each parsed doc we do
best-effort type checks against the `required` and `enum` fields.
Validation failures are logged as warnings — they don't reject the
doc, since a poorly-authored KB shouldn't brick the agent. SOC
operators see them in audit (every load emits a kb_loaded event with
counts of inserted / updated / unchanged / skipped).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("Phantom MCP")

# Frontmatter delimiter regex. Matches the leading `---\n...\n---` block.
_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<fm>.*?)\n---\s*\n(?P<body>.*)\Z",
    re.DOTALL,
)


class KbLoaderError(RuntimeError):
    """Raised on unrecoverable load errors (e.g. bundle path missing)."""


# Circuit breaker: if the embedder is fundamentally broken (Vertex
# outage, bad credentials, wrong project/region — anything that makes
# EVERY call fail), kb.upsert() raises on every single doc. Without a
# breaker, the loader grinds through every doc in every bundled KB —
# with 250+ docs in the xql-examples KB alone, that reliably exceeds
# entrypoint.sh's fixed 60s MCP-readiness window and crash-loops the
# ENTIRE container forever, since the embedder's brokenness doesn't
# change between restarts. Trip after a handful of
# consecutive failures: one clear error beats hundreds of identical
# warnings, and a bounded worst case beats an embedder outage taking
# down the whole product.
_EMBED_FAILURE_CIRCUIT_BREAKER = 5


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (metadata, body). Empty metadata when no frontmatter block."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    fm_text = match.group("fm")
    body = match.group("body")
    # Parse YAML frontmatter. We avoid pulling pyyaml here because the
    # MCP container already has it (pinned via fastmcp deps), but
    # importing inside the function keeps this module's import surface
    # explicit — surfacing a clearer error if the env is unexpectedly
    # missing yaml.
    import yaml  # noqa: PLC0415
    try:
        meta = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        logger.warning("kb_loader: malformed frontmatter (%s) — treating as empty", exc)
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    return meta, body


def _validate_against_schema(
    metadata: dict[str, Any],
    schema: dict[str, Any] | None,
    *,
    where: str,
) -> tuple[list[str], list[str]]:
    """Schema validation. Returns (warnings, missing_required).

    `missing_required` is the list of schema-required field names that
    are absent from `metadata`. When non-empty, the caller MUST skip
    the upsert — required means required, not "log a warning and ship
    a broken doc into the KB". `warnings` covers softer
    issues (enum violations, type mismatches) which are logged but do
    not block the upsert.
    """
    if not schema:
        return [], []
    warnings: list[str] = []
    missing_required: list[str] = []

    required = schema.get("required") or []
    if isinstance(required, list):
        for k in required:
            if isinstance(k, str) and k not in metadata:
                missing_required.append(k)
                warnings.append(f"missing required field {k!r}")

    props = schema.get("properties") or {}
    if isinstance(props, dict):
        for k, v in metadata.items():
            spec = props.get(k)
            if not isinstance(spec, dict):
                continue
            enum_vals = spec.get("enum")
            if isinstance(enum_vals, list) and v not in enum_vals:
                warnings.append(
                    f"field {k!r} value {v!r} not in enum {enum_vals!r}"
                )
            expected_type = spec.get("type")
            if expected_type == "string" and not isinstance(v, str):
                warnings.append(f"field {k!r} should be string")
            elif expected_type == "array" and not isinstance(v, list):
                warnings.append(f"field {k!r} should be array")
            elif expected_type == "object" and not isinstance(v, dict):
                warnings.append(f"field {k!r} should be object")

    if warnings:
        for w in warnings:
            logger.warning("kb_loader: %s — %s", where, w)
    return warnings, missing_required


def _iter_kb_files(root: Path) -> Iterable[Path]:
    """Yield candidate doc files under `root` in deterministic order.

    Defensive filtering:
      - Skip the bundle's `schema.json` (it's metadata about docs, not
        a doc itself).
      - Skip any path component starting with `.` — covers `.git`,
        `.DS_Store`, and the `._*` AppleDouble metadata files that
        macOS tar can leak into a Linux container's bind mount.
        Reading those as UTF-8 fails because they're binary resource
        forks, and they have no business being in a KB anyway.
      - Allow only `.md`, `.markdown`, `.json`, `.txt` suffixes.
    """
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.name == "schema.json":
            continue
        # Hidden / sidecar files anywhere relative to the KB root → skip.
        # Use relative_to so an unrelated dotted directory upstream of
        # the bundle (e.g. /Users/.cache/...) doesn't false-positive.
        try:
            rel_parts = p.relative_to(root).parts
        except ValueError:
            rel_parts = ()
        if any(part.startswith(".") for part in rel_parts):
            continue
        if p.suffix.lower() in (".md", ".markdown", ".json", ".txt"):
            yield p


def _doc_from_md(text: str) -> tuple[dict[str, Any], str]:
    return _parse_frontmatter(text)


def _doc_from_json(text: str) -> tuple[dict[str, Any], str]:
    """For JSON files, the whole object is metadata; `content` field
    (or the entire JSON re-serialized) is the body."""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("kb_loader: invalid JSON (%s)", exc)
        return {}, text
    if not isinstance(obj, dict):
        return {}, json.dumps(obj)
    body = obj.get("content")
    if isinstance(body, str) and body.strip():
        meta = {k: v for k, v in obj.items() if k != "content"}
        return meta, body
    # No `content` field — embed the whole object's JSON dump as body
    # so the doc is at least discoverable via a search by structural
    # keywords ("attack_techniques", "category", etc.).
    return obj, json.dumps(obj, ensure_ascii=False)


def load_bundled_knowledge(
    *,
    kb,                         # SqliteKnowledgeBase, but typed Any to dodge cycles
    bundle_root: Path,
    bundled: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Walk every `bundled[]` entry, ingest its docs, return per-KB counts.

    Counts shape:
        {
          "phantom-soc": {
            "inserted": 3,
            "updated":  0,
            "unchanged": 0,
            "removed": 0,
            "skipped": 0,   # files we couldn't parse
          }
        }

    The loader records ONE `kb_loaded` audit event per KB summarizing
    the action breakdown — useful for boot-time forensics ("did the
    KB grow on this deploy?") without flooding the audit log with
    per-doc rows (those are emitted by `kb.upsert` separately, when
    docs actually changed).
    """
    from usecase.audit_log import ACTION_KB_LOADED, record_event

    summary: dict[str, dict[str, int]] = {}
    # Shared across every bundled entry in this call — the embedder is
    # the same underlying dependency for all of them, so a run of
    # failures in one KB means the next KB will fail identically.
    consecutive_embed_failures = 0
    aborted = False

    for entry in bundled or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        path = entry.get("path")
        schema_path = entry.get("schema")
        if not isinstance(name, str) or not isinstance(path, str):
            logger.warning("kb_loader: skipping malformed bundled entry %r", entry)
            continue

        kb_root = (bundle_root / path).resolve()
        if not kb_root.is_dir():
            logger.warning(
                "kb_loader: kb %s path %s does not exist — skipping",
                name, kb_root,
            )
            continue

        schema: dict[str, Any] | None = None
        if isinstance(schema_path, str):
            sp = (bundle_root / schema_path).resolve()
            if sp.is_file():
                try:
                    schema = json.loads(sp.read_text("utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning(
                        "kb_loader: could not parse schema %s (%s)", sp, exc
                    )

        # Key names match what `kb.upsert()` returns as its action
        # tuple ("insert"/"update"/"unchanged") plus loader-local
        # bookkeeping for "removed" (vanished-from-disk) and "skipped"
        # (read errors). An earlier draft used past-tense keys here
        # which silently disconnected from upsert's return values —
        # all real inserts landed in `counts["insert"]` while the log
        # line read `counts["inserted"]` and printed 0. Tense alignment
        # matters!
        counts = {
            "insert": 0, "update": 0, "unchanged": 0,
            "removed": 0, "skipped": 0, "invalid": 0,
        }
        seen_doc_ids: set[str] = set()

        for f in _iter_kb_files(kb_root):
            try:
                text = f.read_text("utf-8")
            except OSError as exc:
                logger.warning("kb_loader: cannot read %s (%s)", f, exc)
                counts["skipped"] += 1
                continue
            if f.suffix.lower() in (".md", ".markdown"):
                meta, body = _doc_from_md(text)
            elif f.suffix.lower() == ".json":
                meta, body = _doc_from_json(text)
            else:  # .txt
                meta, body = {}, text

            # Doc id: prefer frontmatter.id, fall back to relative path
            # without the extension. Stable across boots either way.
            rel = f.relative_to(kb_root).as_posix()
            doc_id = meta.get("id")
            if not isinstance(doc_id, str) or not doc_id:
                doc_id = os.path.splitext(rel)[0]

            _, missing_required = _validate_against_schema(
                meta, schema, where=f"{name}:{doc_id}",
            )
            if missing_required:
                # Required-field validation is enforcing, not
                # advisory. Without this skip, the kb_loader would
                # silently upsert docs missing `id`/`title`/
                # `category` (the schema's required trio for
                # xql-examples) — the doc would land in the KB with empty
                # metadata + get embedded as searchable content.
                # A README.md at the KB root or a raw source file under
                # _tools/ are typical leaks. Reaper at the
                # bottom of this loop drops previously-loaded copies
                # of now-invalid docs because they're not added to
                # seen_doc_ids here.
                logger.warning(
                    "kb_loader: %s — skipping doc (missing required: %s)",
                    f"{name}:{doc_id}",
                    ", ".join(missing_required),
                )
                counts["invalid"] += 1
                continue

            try:
                _, action = kb.upsert(
                    kb_name=name,
                    doc_id=doc_id,
                    content=body.strip(),
                    title=meta.get("title") if isinstance(meta.get("title"), str) else None,
                    category=meta.get("category") if isinstance(meta.get("category"), str) else None,
                    metadata=meta,
                    source_path=rel,
                    source_hash=_sha256(text),
                )
                counts[action] = counts.get(action, 0) + 1
                seen_doc_ids.add(doc_id)
                consecutive_embed_failures = 0
            except Exception as exc:
                logger.warning(
                    "kb_loader: failed to upsert %s/%s (%s)", name, doc_id, exc
                )
                counts["skipped"] += 1
                consecutive_embed_failures += 1
                if consecutive_embed_failures >= _EMBED_FAILURE_CIRCUIT_BREAKER:
                    logger.error(
                        "kb_loader: %d consecutive upsert failures — the "
                        "embedder appears non-functional (check the Vertex "
                        "provider config: project, region, service-account "
                        "credentials). Aborting remaining KB load for this "
                        "boot instead of retrying every document; "
                        "already-persisted docs are unaffected and search "
                        "will simply be incomplete until this is fixed and "
                        "the container restarts.",
                        consecutive_embed_failures,
                    )
                    aborted = True
                    break

        if aborted:
            # Stopped partway through this KB's file list — do NOT run
            # the "reap docs that vanished from disk" step below. Every
            # unvisited file's doc_id is absent from seen_doc_ids
            # purely because we didn't get to it, not because it's
            # gone from disk; reaping now would delete still-valid
            # docs out from under a broken-embedder boot.
            summary[name] = counts
            record_event(
                ACTION_KB_LOADED,
                target=f"kb:{name}",
                status="aborted",
                metadata={
                    "kb_name": name,
                    "source_path": str(kb_root),
                    "reason": "embedder_circuit_breaker",
                    **counts,
                },
            )
            logger.warning(
                "kb_loader: %s — load aborted after %d consecutive embed "
                "failures (insert=%d update=%d unchanged=%d skipped=%d)",
                name, consecutive_embed_failures, counts["insert"],
                counts["update"], counts["unchanged"], counts["skipped"],
            )
            break

        # Reap docs that vanished from disk since last boot.
        existing = kb.kb_doc_ids(name)
        gone = existing - seen_doc_ids
        for stale in gone:
            if kb.remove(name, stale):
                counts["removed"] += 1

        summary[name] = counts
        record_event(
            ACTION_KB_LOADED,
            target=f"kb:{name}",
            status="success",
            metadata={
                "kb_name": name,
                "source_path": str(kb_root),
                **counts,
            },
        )
        logger.info(
            "kb_loader: %s — insert=%d update=%d unchanged=%d "
            "removed=%d skipped=%d invalid=%d",
            name, counts["insert"], counts["update"], counts["unchanged"],
            counts["removed"], counts["skipped"], counts["invalid"],
        )

    return summary
