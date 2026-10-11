"""cortex-content connector — MCP tools for the Cortex content
catalog bundled with Phantom.

Tool names auto-namespace as `cortex-content/<bare_name>` per the
embedded MCP's connector loader; `connector.yaml`'s
`runtimeMapping.functionPrefix=cortex_` strips the prefix at dispatch
time, so the agent sees `cortex-content/list_packs`, etc.

Why this connector exists: provides the agent with a live reference
for what canonical XDM data-model parsers look like across the ~26
packs that ship ModelingRules today. When the agent authors / updates
data models for the operator's tenant, it can fetch the reference
implementation per data source instead of guessing XDM paths.

Besides the fetch surface (list_* / get_* tools), `index_kb`
walks one pack's rules and upserts them into the agent's knowledge
KB under kb_name='cortex-content' so the agent can semantic-search
('show me an XDM rule for cisco_esa') instead of round-tripping
through list_*/get_* one rule at a time. Idempotent — source_hash
dedupe means re-indexing the same pack is cheap; re-embedding only
runs on rules whose source actually changed.
"""
from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Any


# Explicit tool exports. Without `__all__` the runtime falls back to
# auto-discovery and logs a missing-__all__ warning. Declaring it
# stabilizes the public surface and avoids that warning.
__all__ = [
    "cortex_list_packs",
    "cortex_search_packs",
    "cortex_get_pack",
    "cortex_list_modeling_rules",
    "cortex_get_modeling_rule",
    "cortex_list_parsing_rules",
    "cortex_get_parsing_rule",
    "cortex_list_correlation_rules",
    "cortex_get_correlation_rule",
    "cortex_index_kb",
    # marketplace data sources
    "cortex_extract_vendor_schema",
    "cortex_extract_vendor_logo",
    "cortex_extract_vendor_catalog",
]


from ._github_client import (
    GitHubClient,
    GitHubNotFoundError,
    GitHubRateLimitError,
)

logger = logging.getLogger("Phantom MCP.cortex-content")


# ─── Config resolution ──────────────────────────────────────────────


def _get_client():
    """Return the cortex-content client.

    The catalog ships with Phantom under
    `bundles/spark/connectors/cortex-content/baked/`. The client reads
    everything from that local directory — no network calls, no
    per-instance configuration.

    The connector_loader sets a contextvar with the current instance's
    config+secrets BEFORE dispatching each tool call (see
    bundles/spark/mcp/src/usecase/connector_loader.py). This client
    doesn't read any of that — instance config is unused.

    Raises FileNotFoundError if the catalog directory is missing from
    the bundle (would only happen if the image was built without it,
    which CI prevents).
    """
    from ._baked_client import BakedClient, baked_root_path, is_baked_available

    if not is_baked_available():
        raise FileNotFoundError(
            "cortex-content catalog directory is missing from the bundle; "
            "the image was built without it. Re-run the image build."
        )
    return BakedClient(baked_root_path())


def _error_envelope(fn_name: str, exc: BaseException) -> dict[str, Any]:
    """Construct the structured error envelope the agent expects.

    The try/except is inlined in each tool rather than applied as a
    `@_wrap_errors(...)` decorator: a decorator that wraps every tool with
    a `*args, **kwargs` shim breaks FastMCP's tool-introspection layer
    (`ValueError("Functions with *args are not supported as tools")`),
    which walks the function signature to derive the Pydantic input
    schema. Slightly more boilerplate, zero FastMCP-compat issues.
    """
    if isinstance(exc, GitHubNotFoundError):
        return {"ok": False, "error": f"not found: {exc}", "tool": fn_name}
    if isinstance(exc, GitHubRateLimitError):
        return {"ok": False, "error": str(exc), "tool": fn_name, "rate_limited": True}
    logger.exception("cortex-content tool %s failed", fn_name)
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "tool": fn_name}


# ─── Pack discovery tools ───────────────────────────────────────────


async def cortex_list_packs(
    supported_module: str | None = None,
    limit: int = 100,
    offset: int = 0,
    xsiam_only: bool = False,
) -> dict[str, Any]:
    """List packs in the content repo, optionally filtered by
    supportedModules. See connector.yaml for the full tool contract.

    `xsiam_only` is a shortcut — equivalent to passing
    `supported_module="xsiam"` but more discoverable for the
    marketplace data-sources flow. When both are passed, the
    explicit `supported_module` value wins (operator override).
    """
    # xsiam_only normalises to supported_module for impl
    # simplicity. If both are set, the explicit value takes precedence.
    if xsiam_only and not supported_module:
        supported_module = "xsiam"
    try:
        return await _cortex_list_packs_impl(supported_module, limit, offset)
    except Exception as exc:  # noqa: BLE001
        return _error_envelope("cortex_list_packs", exc)


async def _cortex_list_packs_impl(
    supported_module: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    client = _get_client()
    entries = client.list_dir("Packs")
    # Keep only directories (each pack is a directory under Packs/).
    pack_names = sorted(
        e["name"] for e in entries if e.get("type") == "dir" and e.get("name")
    )

    # If we're filtering by supportedModule, we have to fetch each
    # pack's metadata to check the field. To stay under the 60/hr
    # anonymous rate limit, we use the cached pack_metadata path
    # which lives on the CDN and doesn't count against the API limit.
    if supported_module:
        wanted = supported_module.strip().lower()
        filtered: list[dict[str, Any]] = []
        # Apply offset/limit BEFORE the per-pack metadata fetch so we
        # don't fetch metadata for thousands of packs to find 100.
        # This isn't perfect (we don't know the filtered-total without
        # walking everything) but it's the right tradeoff for the
        # rate-limit-conscious flow.
        for name in pack_names[offset : offset + max(1, min(limit, 500))]:
            try:
                meta = client.get_file_json(f"Packs/{name}/pack_metadata.json")
            except GitHubNotFoundError:
                continue
            modules = meta.get("supportedModules") or []
            if isinstance(modules, list) and any(
                str(m).strip().lower() == wanted for m in modules
            ):
                filtered.append(_pack_summary(name, meta))
        return {
            "ok": True,
            "packs": filtered,
            "total": len(pack_names),  # unfiltered total
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < len(pack_names),
            "filter": {"supported_module": supported_module},
        }

    # No filter — return a slice with minimal metadata fetched.
    window = pack_names[offset : offset + max(1, min(limit, 500))]
    result = []
    for name in window:
        try:
            meta = client.get_file_json(f"Packs/{name}/pack_metadata.json")
            result.append(_pack_summary(name, meta))
        except GitHubNotFoundError:
            # Pack directory exists but metadata is missing — surface a
            # minimal entry so operators still see the pack name.
            result.append({"name": name, "description": None, "version": None})
    return {
        "ok": True,
        "packs": result,
        "total": len(pack_names),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(window) < len(pack_names),
    }


async def cortex_search_packs(query: str, limit: int = 20) -> dict[str, Any]:
    """Fuzzy-search packs by name/description/keywords/categories.

    Scoring: SequenceMatcher ratio against (name + description +
    keywords + tags + categories) text. Threshold 0.2 below which the
    pack is omitted. Top-K returned in descending relevance order.
    """
    try:
        return await _cortex_search_packs_impl(query, limit)
    except Exception as exc:  # noqa: BLE001
        return _error_envelope("cortex_search_packs", exc)


async def _cortex_search_packs_impl(query: str, limit: int) -> dict[str, Any]:
    if not query or not query.strip():
        return {"ok": False, "error": "query is required", "tool": "cortex_search_packs"}

    client = _get_client()
    entries = client.list_dir("Packs")
    pack_names = sorted(
        e["name"] for e in entries if e.get("type") == "dir" and e.get("name")
    )

    q = query.strip().lower()
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for name in pack_names:
        try:
            meta = client.get_file_json(f"Packs/{name}/pack_metadata.json")
        except GitHubNotFoundError:
            continue
        haystack = _searchable_text(name, meta).lower()
        # Fast exact-substring boost; then fall back to fuzzy ratio.
        if q in haystack:
            score = 1.0
        else:
            score = SequenceMatcher(None, q, haystack).ratio()
        if score >= 0.2:
            scored.append((score, name, meta))

    scored.sort(key=lambda t: -t[0])
    top = scored[: max(1, min(limit, 100))]
    return {
        "ok": True,
        "query": query,
        "total_matched": len(scored),
        "matches": [
            {**_pack_summary(name, meta), "relevance_score": round(score, 3)}
            for score, name, meta in top
        ],
    }


async def cortex_get_pack(pack_name: str) -> dict[str, Any]:
    """Fetch pack_metadata.json + top-level tree + README for one pack."""
    try:
        return await _cortex_get_pack_impl(pack_name)
    except Exception as exc:  # noqa: BLE001
        return _error_envelope("cortex_get_pack", exc)


async def _cortex_get_pack_impl(pack_name: str) -> dict[str, Any]:
    if not pack_name or not pack_name.strip():
        return {"ok": False, "error": "pack_name is required", "tool": "cortex_get_pack"}

    client = _get_client()
    tree = client.list_dir(f"Packs/{pack_name}")
    metadata = client.get_file_json(f"Packs/{pack_name}/pack_metadata.json")
    readme: str | None = None
    try:
        readme = client.get_file(f"Packs/{pack_name}/README.md")
    except GitHubNotFoundError:
        readme = None
    return {
        "ok": True,
        "pack_name": pack_name,
        "metadata": metadata,
        "tree": [
            {"name": e.get("name"), "type": e.get("type"), "size": e.get("size", 0)}
            for e in tree
        ],
        "readme": readme,
    }


# ─── ModelingRules tools ─────────────────────────────────────────────


async def cortex_list_modeling_rules(pack_name: str) -> dict[str, Any]:
    """List ModelingRules directories under a pack."""
    try:
        return await _list_rule_dirs(pack_name, "ModelingRules", "modeling_rules")
    except Exception as exc:  # noqa: BLE001
        return _error_envelope("cortex_list_modeling_rules", exc)


async def cortex_get_modeling_rule(pack_name: str, rule_name: str) -> dict[str, Any]:
    """Fetch the three-file bundle (.xif + .yml + _schema.json) for
    one modeling rule."""
    try:
        return await _get_rule_bundle(pack_name, rule_name, "ModelingRules")
    except Exception as exc:  # noqa: BLE001
        return _error_envelope("cortex_get_modeling_rule", exc)


# ─── ParsingRules tools ──────────────────────────────────────────────


async def cortex_list_parsing_rules(pack_name: str) -> dict[str, Any]:
    """List ParsingRules directories under a pack."""
    try:
        return await _list_rule_dirs(pack_name, "ParsingRules", "parsing_rules")
    except Exception as exc:  # noqa: BLE001
        return _error_envelope("cortex_list_parsing_rules", exc)


async def cortex_get_parsing_rule(pack_name: str, rule_name: str) -> dict[str, Any]:
    """Fetch the three-file bundle for one parsing rule."""
    try:
        return await _get_rule_bundle(pack_name, rule_name, "ParsingRules")
    except Exception as exc:  # noqa: BLE001
        return _error_envelope("cortex_get_parsing_rule", exc)


# ─── CorrelationRules tools ──────────────────────────────────────────


async def cortex_list_correlation_rules(pack_name: str) -> dict[str, Any]:
    """List CorrelationRules directories under a pack."""
    try:
        return await _list_rule_dirs(pack_name, "CorrelationRules", "correlation_rules")
    except Exception as exc:  # noqa: BLE001
        return _error_envelope("cortex_list_correlation_rules", exc)


async def cortex_get_correlation_rule(pack_name: str, rule_name: str) -> dict[str, Any]:
    """Fetch the .yml + .xql for one correlation rule.

    CorrelationRules typically have only two files (no _schema.json):
      <Rule>.yml — rule metadata (severity, mitre tags, description)
      <Rule>.xql — the XQL query that produces the alert
    """
    try:
        return await _cortex_get_correlation_rule_impl(pack_name, rule_name)
    except Exception as exc:  # noqa: BLE001
        return _error_envelope("cortex_get_correlation_rule", exc)


async def _cortex_get_correlation_rule_impl(
    pack_name: str, rule_name: str,
) -> dict[str, Any]:
    if not pack_name or not rule_name:
        return {
            "ok": False,
            "error": "pack_name and rule_name are required",
            "tool": "cortex_get_correlation_rule",
        }
    client = _get_client()
    base = f"Packs/{pack_name}/CorrelationRules/{rule_name}"

    yml: str | None = None
    xql: str | None = None
    # CorrelationRules can be single-file or nested in their own dir.
    # Try both shapes.
    try:
        entries = client.list_dir(base)
        for e in entries:
            name = e.get("name", "")
            if name.endswith(".yml") or name.endswith(".yaml"):
                yml = client.get_file(f"{base}/{name}")
            elif name.endswith(".xql"):
                xql = client.get_file(f"{base}/{name}")
    except GitHubNotFoundError:
        # Try the flat-file shape: Packs/<pack>/CorrelationRules/<rule>.yml
        try:
            yml = client.get_file(f"Packs/{pack_name}/CorrelationRules/{rule_name}.yml")
        except GitHubNotFoundError:
            return {
                "ok": False,
                "error": f"correlation rule {rule_name!r} not found in pack {pack_name!r}",
                "tool": "cortex_get_correlation_rule",
            }

    return {
        "ok": True,
        "pack_name": pack_name,
        "rule_name": rule_name,
        "yml": yml,
        "xql": xql,
    }


# ─── Shared helpers ──────────────────────────────────────────────────


def _pack_summary(name: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Project pack_metadata.json down to the small shape list_packs
    and search_packs return. Keeps the response payload small —
    operators get full metadata via cortex_get_pack."""
    return {
        "name": name,
        "description": meta.get("description"),
        "version": meta.get("currentVersion") or meta.get("version"),
        "supportedModules": meta.get("supportedModules") or [],
        "marketplaces": meta.get("marketplaces") or [],
        "categories": meta.get("categories") or [],
    }


def _searchable_text(name: str, meta: dict[str, Any]) -> str:
    """Concatenate the pack_metadata fields the search tool keys on
    into one searchable string. Order matters slightly for the
    ratio() scoring — name + description weight more than tags."""
    parts: list[str] = [name]
    for field in ("description", "name"):
        val = meta.get(field)
        if isinstance(val, str):
            parts.append(val)
    for field in ("keywords", "tags", "categories", "useCases"):
        val = meta.get(field) or []
        if isinstance(val, list):
            parts.extend(str(v) for v in val if v)
    return " ".join(parts)


async def _list_rule_dirs(
    pack_name: str,
    rules_subdir: str,
    response_key: str,
) -> dict[str, Any]:
    """Shared list-rules implementation for Modeling/Parsing/Correlation
    rules. Each rule lives at Packs/<pack>/<subdir>/<rule_name>/.
    Returns a list with rule name + datasets parsed from each rule's
    _schema.json (when present) so the agent can see "this rule
    models <datasets>" without a per-rule fetch."""
    if not pack_name or not pack_name.strip():
        return {
            "ok": False,
            "error": "pack_name is required",
            "tool": f"cortex_list_{response_key}",
        }
    client = _get_client()
    try:
        entries = client.list_dir(f"Packs/{pack_name}/{rules_subdir}")
    except GitHubNotFoundError:
        # Pack exists but has no <rules_subdir> directory — return
        # empty rather than 404.
        return {
            "ok": True,
            "pack_name": pack_name,
            response_key: [],
        }

    rules: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("type") != "dir":
            continue
        rule_name = entry.get("name")
        if not rule_name:
            continue
        # Best-effort: parse datasets from the rule's _schema.json if
        # present. Failures here downgrade the rule entry to just
        # {name, datasets: []} so listing never breaks on a single
        # malformed rule.
        datasets: list[str] = []
        try:
            schema = client.get_file_json(
                f"Packs/{pack_name}/{rules_subdir}/{rule_name}/{rule_name}_schema.json"
            )
            if isinstance(schema, dict):
                datasets = sorted(schema.keys())
        except GitHubNotFoundError:
            pass
        rules.append({"name": rule_name, "datasets": datasets})

    return {"ok": True, "pack_name": pack_name, response_key: rules}


async def _get_rule_bundle(
    pack_name: str,
    rule_name: str,
    rules_subdir: str,
) -> dict[str, Any]:
    """Shared get-rule implementation for Modeling/Parsing rules. Fetches
    <Rule>.xif + <Rule>.yml + <Rule>_schema.json from one rule
    directory."""
    if not pack_name or not rule_name:
        return {
            "ok": False,
            "error": "pack_name and rule_name are required",
            "tool": f"cortex_get_{rules_subdir.lower().rstrip('s')}",
        }
    client = _get_client()
    base = f"Packs/{pack_name}/{rules_subdir}/{rule_name}"
    xif = client.get_file(f"{base}/{rule_name}.xif")
    yml_text: str | None = None
    try:
        yml_text = client.get_file(f"{base}/{rule_name}.yml")
    except GitHubNotFoundError:
        pass
    schema: Any = None
    try:
        schema = client.get_file_json(f"{base}/{rule_name}_schema.json")
    except GitHubNotFoundError:
        pass
    return {
        "ok": True,
        "pack_name": pack_name,
        "rule_name": rule_name,
        "xif": xif,
        "yml": yml_text,
        "schema": schema,
    }


# ─── KB indexing ────────────────────────────────────────────────────


_VALID_RULE_TYPES = ("modeling", "parsing", "correlation")
_RULE_SUBDIR = {
    "modeling": "ModelingRules",
    "parsing": "ParsingRules",
    "correlation": "CorrelationRules",
}


async def cortex_index_kb(
    pack_name: str,
    rule_types: list[str] | None = None,
    kb_name: str = "cortex-content",
) -> dict[str, Any]:
    """Index one pack's ModelingRules / ParsingRules / CorrelationRules
    into the agent's knowledge_search KB for semantic retrieval.

    After indexing, the agent can semantic-search the pack's content
    via the standard `knowledge_search` tool with `kb_name="cortex-content"`
    (or whichever KB name was passed). Each rule becomes one KB document
    keyed by `<pack>/<type>/<rule>` so re-indexing is idempotent — the
    KB's source_hash de-dup skips the embed step on unchanged rules.

    Args:
        pack_name: pack to index (e.g. "F5APM", "MicrosoftDefenderAdvancedThreatProtection").
            Use `cortex-content/list_packs` or `cortex-content/search_packs`
            to discover pack names first.
        rule_types: optional subset of {"modeling", "parsing", "correlation"}.
            Default = all three. Pass e.g. `["modeling"]` to only index
            the ModelingRules (the common case for data-model authoring
            reference).
        kb_name: target KB namespace. Default "cortex-content". Override
            only when isolating an experiment from the main KB.

    Returns:
        {pack_name, kb_name, indexed: {modeling: N, parsing: N, correlation: N},
         unchanged: M, errors: [...]}.
        `indexed` counts insert+update; `unchanged` counts source_hash hits
        (no re-embed); `errors` is a list of {rule_type, rule_name, error}
        for per-rule failures that didn't abort the whole index call.

    Cost notes: dominated by Vertex embedding API calls — one embed per
    new/changed rule. Typical pack has 1–5 rules total, so a single
    pack index is seconds to a minute. For the full ~26 packs that ship
    ModelingRules, call this tool sequentially per pack — there's no
    bulk "index everything" tool intentionally, to keep per-call latency
    bounded and to let the operator pin which packs go into the KB.
    """
    try:
        return await _cortex_index_kb_impl(pack_name, rule_types, kb_name)
    except Exception as exc:  # noqa: BLE001
        return _error_envelope("cortex_index_kb", exc)


async def _cortex_index_kb_impl(
    pack_name: str,
    rule_types: list[str] | None,
    kb_name: str,
) -> dict[str, Any]:
    import hashlib
    import json

    if not pack_name or not pack_name.strip():
        return {"ok": False, "error": "pack_name is required", "tool": "cortex_index_kb"}
    if not kb_name or not kb_name.strip():
        return {"ok": False, "error": "kb_name is required", "tool": "cortex_index_kb"}

    requested = rule_types if rule_types is not None else list(_VALID_RULE_TYPES)
    norm_types: list[str] = []
    for t in requested:
        tl = str(t).strip().lower()
        if tl not in _VALID_RULE_TYPES:
            return {
                "ok": False,
                "error": (
                    f"unknown rule_type {tl!r}; must be one of "
                    f"{list(_VALID_RULE_TYPES)}"
                ),
                "tool": "cortex_index_kb",
            }
        norm_types.append(tl)

    try:
        from usecase.kb_store import knowledge_base  # type: ignore
    except ImportError:
        return {
            "ok": False,
            "error": "knowledge base module unavailable on this MCP runtime",
            "tool": "cortex_index_kb",
        }
    kb = knowledge_base()
    if kb is None:
        return {
            "ok": False,
            "error": "knowledge base not initialized — did the runtime boot complete?",
            "tool": "cortex_index_kb",
        }

    client = _get_client()

    # Pack-level metadata gets attached to every rule doc so the agent
    # can filter / cite the source pack from search hits.
    try:
        pack_meta = client.get_file_json(f"Packs/{pack_name}/pack_metadata.json")
    except GitHubNotFoundError:
        return {
            "ok": False,
            "error": f"pack {pack_name!r} has no pack_metadata.json (does it exist in the repo?)",
            "tool": "cortex_index_kb",
        }

    indexed = {"modeling": 0, "parsing": 0, "correlation": 0}
    unchanged = 0
    errors: list[dict[str, Any]] = []

    for rule_type in norm_types:
        subdir = _RULE_SUBDIR[rule_type]
        try:
            entries = client.list_dir(f"Packs/{pack_name}/{subdir}")
        except GitHubNotFoundError:
            # Pack legitimately has no rules of this type — not an error.
            continue
        except GitHubRateLimitError as exc:
            errors.append(
                {"rule_type": rule_type, "rule_name": None, "error": str(exc)},
            )
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {"rule_type": rule_type, "rule_name": None, "error": f"{type(exc).__name__}: {exc}"},
            )
            continue

        for entry in entries:
            if entry.get("type") != "dir":
                # Correlation rules occasionally live as flat files
                # under Packs/<pack>/CorrelationRules/<rule>.yml — index
                # those too.
                if rule_type == "correlation" and (
                    entry.get("name", "").endswith(".yml")
                    or entry.get("name", "").endswith(".yaml")
                ):
                    rule_name = entry["name"].rsplit(".", 1)[0]
                    try:
                        result = await _index_one_correlation_flat(
                            kb, kb_name, pack_name, pack_meta, rule_name,
                            client, hashlib, json,
                        )
                    except Exception as exc:  # noqa: BLE001
                        errors.append({
                            "rule_type": rule_type, "rule_name": rule_name,
                            "error": f"{type(exc).__name__}: {exc}",
                        })
                        continue
                    if result == "unchanged":
                        unchanged += 1
                    else:
                        indexed[rule_type] += 1
                continue

            rule_name = entry.get("name")
            if not rule_name:
                continue
            try:
                result = await _index_one_rule(
                    kb, kb_name, pack_name, pack_meta, rule_type, subdir,
                    rule_name, client, hashlib, json,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append({
                    "rule_type": rule_type, "rule_name": rule_name,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue
            if result == "unchanged":
                unchanged += 1
                _emit_index_doc_metric("unchanged")
            else:
                indexed[rule_type] += 1
                _emit_index_doc_metric(result)  # "insert" or "update"

    # Per-pack run counter labeled by overall result. Operators
    # see a single line per index_kb call ("succeeded" / "partial" /
    # "failed") regardless of which rule types the pack ships. The
    # per-document counter (above) gives the finer-grained breakdown.
    if errors:
        overall = "partial" if (sum(indexed.values()) + unchanged) > 0 else "failed"
    else:
        overall = "succeeded"
    _emit_index_run_metric(pack_name=pack_name, result=overall)

    return {
        "ok": True,
        "pack_name": pack_name,
        "kb_name": kb_name,
        "indexed": indexed,
        "unchanged": unchanged,
        "errors": errors,
    }


async def _index_one_rule(
    kb: Any,
    kb_name: str,
    pack_name: str,
    pack_meta: dict[str, Any],
    rule_type: str,
    subdir: str,
    rule_name: str,
    client: GitHubClient,
    hashlib_mod: Any,
    json_mod: Any,
) -> str:
    """Fetch + compose + upsert one rule. Returns kb upsert action
    ("insert" | "update" | "unchanged")."""
    base = f"Packs/{pack_name}/{subdir}/{rule_name}"

    # Fetch the rule's files. Best-effort — a rule missing its .xif
    # is a malformed rule, but we should not abort the whole pack index
    # because of one bad rule.
    xif: str | None = None
    yml_text: str | None = None
    schema: Any = None
    try:
        xif = client.get_file(f"{base}/{rule_name}.xif")
    except GitHubNotFoundError:
        pass
    try:
        yml_text = client.get_file(f"{base}/{rule_name}.yml")
    except GitHubNotFoundError:
        pass
    try:
        schema = client.get_file_json(f"{base}/{rule_name}_schema.json")
    except GitHubNotFoundError:
        pass

    if not xif and not yml_text and schema is None:
        # Nothing to index; skip without recording as an error (returning
        # "unchanged" reuses the existing accounting bucket for "this
        # didn't add anything to the KB").
        return "unchanged"

    datasets = sorted(schema.keys()) if isinstance(schema, dict) else []

    # Composed content blob — the embed input. Order matters: the .xif
    # (XQL code, the most-specific signal of "what does this rule do?")
    # leads, then the .yml metadata, then the schema. Each section is
    # delimited so the agent can read the result back as structured
    # content from knowledge_search.
    content_parts = [
        f"# {pack_name}/{subdir}/{rule_name}",
        f"Rule type: {rule_type}",
        f"Pack: {pack_name}",
        f"Datasets: {', '.join(datasets) if datasets else '(none)'}",
        f"Pack description: {pack_meta.get('description') or '(none)'}",
        "",
    ]
    if xif:
        content_parts.extend([f"## .xif ({rule_name}.xif)", "```xql", xif, "```", ""])
    if yml_text:
        content_parts.extend([f"## .yml ({rule_name}.yml)", "```yaml", yml_text, "```", ""])
    if schema is not None:
        content_parts.extend([
            f"## _schema.json ({rule_name}_schema.json)",
            "```json",
            json_mod.dumps(schema, indent=2, sort_keys=True),
            "```",
            "",
        ])
    content = "\n".join(content_parts)

    source_hash = hashlib_mod.sha256(content.encode("utf-8")).hexdigest()
    doc_id = f"{pack_name}/{rule_type}/{rule_name}"
    title = f"{pack_name} — {rule_type} — {rule_name}"

    _, action = kb.upsert(
        kb_name=kb_name,
        doc_id=doc_id,
        title=title,
        category=rule_type,
        content=content,
        metadata={
            "pack_name": pack_name,
            "rule_type": rule_type,
            "rule_name": rule_name,
            "datasets": datasets,
            "supportedModules": pack_meta.get("supportedModules") or [],
            "pack_version": (
                pack_meta.get("currentVersion") or pack_meta.get("version")
            ),
        },
        source_path=base,
        source_hash=source_hash,
    )
    return action


async def _index_one_correlation_flat(
    kb: Any,
    kb_name: str,
    pack_name: str,
    pack_meta: dict[str, Any],
    rule_name: str,
    client: GitHubClient,
    hashlib_mod: Any,
    json_mod: Any,
) -> str:
    """Index a flat-file correlation rule (Packs/<pack>/CorrelationRules/<rule>.yml).
    Unlike directory-shaped rules, these have no .xif and may have no
    .xql counterpart. Returns upsert action like _index_one_rule."""
    yml_text = client.get_file(
        f"Packs/{pack_name}/CorrelationRules/{rule_name}.yml"
    )
    xql_text: str | None = None
    try:
        xql_text = client.get_file(
            f"Packs/{pack_name}/CorrelationRules/{rule_name}.xql"
        )
    except GitHubNotFoundError:
        pass

    content_parts = [
        f"# {pack_name}/CorrelationRules/{rule_name}",
        "Rule type: correlation (flat-file)",
        f"Pack: {pack_name}",
        f"Pack description: {pack_meta.get('description') or '(none)'}",
        "",
        f"## .yml ({rule_name}.yml)",
        "```yaml",
        yml_text,
        "```",
        "",
    ]
    if xql_text:
        content_parts.extend([
            f"## .xql ({rule_name}.xql)", "```xql", xql_text, "```", "",
        ])
    content = "\n".join(content_parts)
    source_hash = hashlib_mod.sha256(content.encode("utf-8")).hexdigest()
    doc_id = f"{pack_name}/correlation/{rule_name}"
    title = f"{pack_name} — correlation — {rule_name}"

    _, action = kb.upsert(
        kb_name=kb_name,
        doc_id=doc_id,
        title=title,
        category="correlation",
        content=content,
        metadata={
            "pack_name": pack_name,
            "rule_type": "correlation",
            "rule_name": rule_name,
            "supportedModules": pack_meta.get("supportedModules") or [],
            "pack_version": (
                pack_meta.get("currentVersion") or pack_meta.get("version")
            ),
            "flat_file": True,
        },
        source_path=f"Packs/{pack_name}/CorrelationRules/{rule_name}.yml",
        source_hash=source_hash,
    )
    return action


# ─── cortex-content KB indexing metrics ───────────────────────────────
#
# Symmetric to the agent_batch_propose metrics. Two counters
# (the pack-level run counter + per-document action counter); no
# histogram because doc counts are bounded by what each pack ships
# (typically 1-5 rules per pack) and per-pack timing is a separate
# observability concern.
#
# Same silent-fail contract: metrics failures never affect the tool's
# primary path. The xsiam connector uses the same `from usecase.X
# import Y` cross-package import pattern (xql_rag_service); main.py's
# manifest pre-registration loop handles counters declared in
# manifest.observability.metrics[].


def _emit_index_run_metric(*, pack_name: str, result: str) -> None:
    """Per-pack run counter. result ∈ {succeeded, partial, failed}.
    Silent no-op when the metrics registry isn't installed."""
    try:
        from usecase.metrics_registry import metrics_registry  # type: ignore
        reg = metrics_registry()
        if reg is None:
            return
        c = reg.counter(
            "phantom_cortex_content_index_runs_total",
            "cortex-content/index_kb calls broken down by overall result",
        )
        c.inc(pack=pack_name, result=result)
    except Exception:  # noqa: BLE001
        pass


def _emit_index_doc_metric(action: str) -> None:
    """Per-document counter. action ∈ {insert, update, unchanged}.
    insert+update means an embedding was generated; unchanged means
    source_hash dedupe skipped the embed step. Lets dashboards split
    new-content rate from cache-hit rate."""
    try:
        from usecase.metrics_registry import metrics_registry  # type: ignore
        reg = metrics_registry()
        if reg is None:
            return
        c = reg.counter(
            "phantom_cortex_content_indexed_docs_total",
            "cortex-content/index_kb per-document outcomes (insert/update/unchanged)",
        )
        c.inc(action=action)
    except Exception:  # noqa: BLE001
        pass


# ─── Marketplace data sources ──────────────────────────────────────
#
# 3 tools support the data-sources marketplace flow:
#
#   cortex_extract_vendor_schema(pack, rule):
#     Returns the raw vendor field inventory for one ModelingRule by
#     reading <Rule>_schema.json directly (Cortex publishes structured
#     field types alongside every modeling rule). For packs whose schema
#     is just `_raw_log` (33% of packs), `is_rawlog_only=True` is set
#     so the caller can treat it as a deferred case.
#
#   cortex_extract_vendor_logo(pack):
#     Finds + returns the canonical vendor logo URL for one pack.
#     Search order: Integrations/<int>/<int>_dark.svg → <int>_image.png
#     → Author_image.png → null. Returns the RAW GitHub URL (not bytes)
#     so the UI can <img src="...">; MCP responses stay JSON-only.
#
#   cortex_extract_vendor_catalog(xsiam_only=True):
#     Roll-up tool — scans the repo tree, returns one catalog row per
#     ModelingRule with {pack, rule, dataset, field_count, has_logo,
#     is_rawlog_only, supported_modules}. Powers the marketplace UI's
#     vendor-list-with-counts view. ~3-5s wall time for ~217 rules.


async def cortex_extract_vendor_schema(
    pack_name: str,
    rule_name: str,
) -> dict[str, Any]:
    """Return the raw vendor field inventory for one ModelingRule.

    Reads `Packs/<pack>/ModelingRules/<rule>/<rule>_schema.json` directly.
    That JSON is exactly the structured field inventory we want — Cortex
    publishes it alongside every modeling rule so XSIAM can validate
    ingested logs against the rule's expected fields. We reuse it here
    as the canonical "what fields does this vendor emit" reference.

    Args:
        pack_name: pack containing the rule (e.g. "FortiGate").
        rule_name: modeling rule directory name (e.g. "FortiGate_1_3").
            Use cortex_list_modeling_rules(pack) first to discover the
            correct rule_name — some packs version the rule directory
            (FortiGate_1_2 → FortiGate_1_3, etc.).

    Returns:
        {
          ok: bool,
          pack_name: str,
          rule_name: str,
          datasets: {
            "<dataset_name>": {
              field_count: int,
              fields: [{name, type, is_array}, ...],
              is_rawlog_only: bool,   # True if only _raw_log (or near-empty)
            },
            ...
          },
          total_field_count: int,
          is_structured: bool,    # True if any dataset has > 5 non-meta fields
          source_path: str,       # the schema.json path we read
        }

    For packs whose modeling rule extracts fields via regex from
    `_raw_log` (F5APM-style), `is_rawlog_only=True` is set on each
    affected dataset. Regex-template extraction is not implemented,
    so those packs are not supported.
    """
    try:
        return await _cortex_extract_vendor_schema_impl(pack_name, rule_name)
    except Exception as exc:  # noqa: BLE001
        return _error_envelope("cortex_extract_vendor_schema", exc)


# Fields that every ModelingRule's schema includes regardless of vendor.
# When the only fields are these, the rule is "rawlog-only" — there's
# no vendor-specific structured data to consume.
_META_SCHEMA_FIELDS = {"_id", "_product", "_raw_log", "_vendor", "_time", "_collector_name"}


async def _cortex_extract_vendor_schema_impl(
    pack_name: str,
    rule_name: str,
) -> dict[str, Any]:
    if not pack_name or not rule_name:
        return {
            "ok": False,
            "error": "pack_name and rule_name are required",
            "tool": "cortex_extract_vendor_schema",
        }
    client = _get_client()
    schema_path = (
        f"Packs/{pack_name}/ModelingRules/{rule_name}/{rule_name}_schema.json"
    )
    try:
        raw_schema = client.get_file_json(schema_path)
    except GitHubNotFoundError as exc:
        return {
            "ok": False,
            "error": f"schema.json not found at {schema_path}",
            "detail": str(exc),
            "tool": "cortex_extract_vendor_schema",
        }
    if not isinstance(raw_schema, dict):
        return {
            "ok": False,
            "error": f"schema.json at {schema_path} is not an object (got {type(raw_schema).__name__})",
            "tool": "cortex_extract_vendor_schema",
        }

    datasets: dict[str, Any] = {}
    total_field_count = 0
    any_structured = False
    for dataset_name, fields_dict in raw_schema.items():
        if not isinstance(fields_dict, dict):
            # Defensive: skip malformed dataset entries
            continue
        field_entries = []
        non_meta_count = 0
        for fname, meta in fields_dict.items():
            if isinstance(meta, dict):
                ftype = meta.get("type", "unknown")
                is_array = bool(meta.get("is_array", False))
            else:
                # Some old packs use a string directly as the type
                ftype = str(meta) if meta is not None else "unknown"
                is_array = False
            field_entries.append({
                "name": fname,
                "type": ftype,
                "is_array": is_array,
            })
            if fname not in _META_SCHEMA_FIELDS:
                non_meta_count += 1
        is_rawlog_only = non_meta_count == 0
        if not is_rawlog_only:
            any_structured = True
        datasets[dataset_name] = {
            "field_count": len(field_entries),
            "non_meta_field_count": non_meta_count,
            "fields": field_entries,
            "is_rawlog_only": is_rawlog_only,
        }
        total_field_count += len(field_entries)

    return {
        "ok": True,
        "pack_name": pack_name,
        "rule_name": rule_name,
        "datasets": datasets,
        "total_field_count": total_field_count,
        "is_structured": any_structured,
        "source_path": schema_path,
    }


async def cortex_extract_vendor_logo(pack_name: str) -> dict[str, Any]:
    """Find the canonical vendor logo URL for a pack.

    Search order (first match wins):
      1. Packs/<pack>/Integrations/<int>/<int>_dark.svg — preferred
         (SVG scales perfectly + is theme-friendly).
      2. Packs/<pack>/Integrations/<int>/<int>_image.png — common
         fallback for packs without an SVG variant.
      3. Packs/<pack>/Author_image.png — for modeling-rule-only packs
         (no integration dir, e.g. F5APM).

    Returns the raw GitHub URL — not the bytes. The UI renders the
    URL directly via `<img src="...">`; this keeps MCP responses
    JSON-only + avoids base64 overhead. The URL is on raw.github
    usercontent.com (CDN) so it's already cache-friendly.

    Args:
        pack_name: pack to find a logo for (e.g. "FortiGate").

    Returns:
        {
          ok: bool,
          pack_name: str,
          logo_url: str | null,      # raw GitHub URL, or null if none found
          logo_type: "svg" | "png" | null,
          source_path: str | null,   # repo-relative path that matched
          searched_paths: [str],     # all candidates we tried, for debug
        }
    """
    try:
        return await _cortex_extract_vendor_logo_impl(pack_name)
    except Exception as exc:  # noqa: BLE001
        return _error_envelope("cortex_extract_vendor_logo", exc)


async def _cortex_extract_vendor_logo_impl(pack_name: str) -> dict[str, Any]:
    if not pack_name:
        return {
            "ok": False,
            "error": "pack_name is required",
            "tool": "cortex_extract_vendor_logo",
        }
    client = _get_client()
    searched: list[str] = []
    found_path: str | None = None
    logo_type: str | None = None

    # Step 1: check for Integrations/* — most packs with logos use this
    integrations_path = f"Packs/{pack_name}/Integrations"
    integrations: list[dict[str, Any]] = []
    try:
        integrations = client.list_dir(integrations_path)
    except GitHubNotFoundError:
        pass

    integration_names = [
        e["name"] for e in integrations if e.get("type") == "dir" and e.get("name")
    ]

    for int_name in integration_names:
        # Try dark.svg first (preferred — theme-friendly + scales)
        svg_path = f"{integrations_path}/{int_name}/{int_name}_dark.svg"
        searched.append(svg_path)
        try:
            # HEAD-equivalent check: try the raw fetch with cheap error mode
            client.get_file(svg_path)
            found_path = svg_path
            logo_type = "svg"
            break
        except GitHubNotFoundError:
            pass
        # Try image.png
        png_path = f"{integrations_path}/{int_name}/{int_name}_image.png"
        searched.append(png_path)
        try:
            # PNG content is binary; get_file may garble, but presence is
            # what matters. We catch JSON errors and treat any successful
            # fetch as "the file exists."
            _ = client.get_file(png_path)
            found_path = png_path
            logo_type = "png"
            break
        except GitHubNotFoundError:
            pass

    # Step 2: fall back to Author_image.png at pack root
    if not found_path:
        author_path = f"Packs/{pack_name}/Author_image.png"
        searched.append(author_path)
        try:
            client.get_file(author_path)
            found_path = author_path
            logo_type = "png"
        except GitHubNotFoundError:
            pass

    # Logo URL always points at Phantom's local serving route. The
    # /api/agent/data-sources/logo/<pack> handler streams the bytes
    # from the bundled catalog with appropriate Content-Type.
    logo_url: str | None = (
        f"/api/agent/data-sources/logo/{pack_name}" if found_path else None
    )

    return {
        "ok": True,
        "pack_name": pack_name,
        "logo_url": logo_url,
        "logo_type": logo_type,
        "source_path": found_path,
        "searched_paths": searched,
    }


async def cortex_extract_vendor_catalog(
    xsiam_only: bool = True,
    include_rawlog: bool = True,
    pack_limit: int = 0,
) -> dict[str, Any]:
    """Catalog every ModelingRule in the bundled Cortex content +
    summarise.

    Powers the marketplace data-sources UI: returns one row per
    `(pack, rule, dataset)` triple, each with field count + logo URL +
    rawlog flag. The UI groups rows by pack → vendor card; clicking
    a card shows the rule list; clicking a rule shows the field
    inventory.

    All data comes from Phantom's local catalog. Sub-millisecond.

    Args:
        xsiam_only: when True (default), only packs with
            `supportedModules` containing "xsiam" are included.
            Set False to include all packs (mostly SOAR-only).
        include_rawlog: when True (default), include rawlog-only rules
            with `is_rawlog_only=True` set. Set False to omit them
            entirely (a marketplace view may want structured
            packs only).
        pack_limit: process at most this many packs (0 = all). Useful
            for first-call testing without burning rate limit.

    Returns:
        {
          ok: bool,
          rows: [{
            pack_name, rule_name, dataset_name,
            field_count, non_meta_field_count, is_rawlog_only,
            logo_url, logo_type,
            supported_modules: [str],
            pack_description: str,
            pack_version: str,
          }],
          packs_scanned: int,
          rules_found: int,
          structured_rules: int,
          rawlog_rules: int,
        }
    """
    try:
        return await _cortex_extract_vendor_catalog_impl(
            xsiam_only, include_rawlog, pack_limit
        )
    except Exception as exc:  # noqa: BLE001
        return _error_envelope("cortex_extract_vendor_catalog", exc)


async def _cortex_extract_vendor_catalog_impl(
    xsiam_only: bool,
    include_rawlog: bool,
    pack_limit: int,
) -> dict[str, Any]:
    client = _get_client()

    # Step 1: list all packs
    pack_entries = client.list_dir("Packs")
    pack_names = sorted(
        e["name"] for e in pack_entries if e.get("type") == "dir" and e.get("name")
    )
    if pack_limit > 0:
        pack_names = pack_names[:pack_limit]

    rows: list[dict[str, Any]] = []
    structured_rules = 0
    rawlog_rules = 0
    packs_scanned = 0

    for pack_name in pack_names:
        # Pack metadata (for xsiam filter + display info)
        try:
            meta = client.get_file_json(f"Packs/{pack_name}/pack_metadata.json")
        except GitHubNotFoundError:
            continue
        supported_modules = meta.get("supportedModules") or []
        if xsiam_only:
            has_xsiam = any(
                str(m).strip().lower() == "xsiam" for m in supported_modules
            )
            if not has_xsiam:
                continue

        # Has ModelingRules?
        try:
            rules = client.list_dir(f"Packs/{pack_name}/ModelingRules")
        except GitHubNotFoundError:
            continue

        rule_names = [
            e["name"] for e in rules if e.get("type") == "dir" and e.get("name")
        ]
        if not rule_names:
            continue

        packs_scanned += 1

        # Lookup vendor logo once per pack
        logo_info = await _cortex_extract_vendor_logo_impl(pack_name)
        logo_url = logo_info.get("logo_url") if isinstance(logo_info, dict) else None
        logo_type = logo_info.get("logo_type") if isinstance(logo_info, dict) else None

        for rule_name in rule_names:
            schema_resp = await _cortex_extract_vendor_schema_impl(
                pack_name, rule_name
            )
            if not schema_resp.get("ok"):
                continue
            for ds_name, ds_info in schema_resp.get("datasets", {}).items():
                is_rawlog = ds_info.get("is_rawlog_only", False)
                if is_rawlog:
                    rawlog_rules += 1
                else:
                    structured_rules += 1
                if not include_rawlog and is_rawlog:
                    continue
                rows.append({
                    "pack_name": pack_name,
                    "rule_name": rule_name,
                    "dataset_name": ds_name,
                    "field_count": ds_info["field_count"],
                    "non_meta_field_count": ds_info["non_meta_field_count"],
                    "is_rawlog_only": is_rawlog,
                    "logo_url": logo_url,
                    "logo_type": logo_type,
                    "supported_modules": supported_modules,
                    "pack_description": meta.get("description"),
                    "pack_version": meta.get("currentVersion"),
                })

    return {
        "ok": True,
        "rows": rows,
        "packs_scanned": packs_scanned,
        "rules_found": len(rows),
        "structured_rules": structured_rules,
        "rawlog_rules": rawlog_rules,
        "filter": {
            "xsiam_only": xsiam_only,
            "include_rawlog": include_rawlog,
            "pack_limit": pack_limit,
        },
    }
