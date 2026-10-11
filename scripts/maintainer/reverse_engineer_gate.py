#!/usr/bin/env python3
"""Reverse-engineer a data source's modeling-rule gate from its .xif.

Reads the live (committed) rule snapshot each run — NO stored vendor->value
mapping. The modeling-rule .xif files under scripts/maintainer/modeling_rules/
are the ground truth; this module parses them to discover, per dataset:

  * UNCONDITIONAL — the dataset maps regardless of payload: either no leading
    `filter` precedes the `xdm.*` assignments, or a `not in (...)` / `!=`
    catch-all branch exists so every event maps to *some* statement.
  * RAW gate — a leading `filter <field> in (...)` / `= "x"` on a payload
    field a simulated event can carry. `values` is the literal set that clears
    it; seed any of `seed_fields` to one of those values for XDM to populate.
  * FUNCTION gate — the filter keys on a function-derived field
    (e.g. `get_category = coalesce(category, Category)`); resolved back to the
    underlying raw `seed_fields` (`category`, `Category`).
  * META gate — the gate field is `_`-prefixed (e.g. `_log_type`); stamped by
    the XSIAM ingestion layer (Broker applet / HTTP Collector), NOT settable
    from the event body. Onboarding-only; documented in the source how_to_use.
  * COMPUTED gate — the gate field is derived in-rule by a non-coalesce
    expression (e.g. json_extract); no direct raw seed.
  * NOT_FOUND — no modeling rule .xif for this pack in the snapshot.

Why a single block can need a multi-statement scan: one `[MODEL: dataset=X]`
block may hold several independent `filter ... | alter xdm.* ...;` statements
(`;`-separated). "Is it gated?" therefore depends on ALL filters in the block,
not just the first — a `not in (...)` branch makes the union a catch-all.

Versioning: a pack may ship base + `_1_3` + `_2_0` .xif files. We union the
gate value-sets across every version present, so a value that clears the gate
in any shipped version counts as satisfiable (XSIAM auto-upgrades content).

Scope: MODELING-rule gates only. Parsing-rule dataset ROUTING (e.g. which of
okta_sso_raw / okta_okta_raw an event lands in) is a separate concern,
documented per-source in the data_source.yaml how_to_use.

Usage:
  python3 scripts/maintainer/reverse_engineer_gate.py <data_source_id> [<id> ...]
"""
import os
import re
import sys
import glob
import json

MR = os.path.join(os.path.dirname(__file__), "modeling_rules")
PR = os.path.join(os.path.dirname(__file__), "parsing_rules")

_VER_RE = re.compile(r"_(\d+(?:_\d+)*)$")


def _version_files(pack, rule, root):
    """Every .xif for `pack` whose stem is `rule` or `rule_<ver>`.
    Falls back to any `{pack}__*.xif` if no rule-stem match (naming drift)."""
    out = []
    for x in sorted(glob.glob(os.path.join(root, f"{pack}__*.xif"))):
        stem = os.path.basename(x)[:-4]                 # drop ".xif"
        after = stem.split("__", 1)[1] if "__" in stem else stem
        base = _VER_RE.sub("", after)                   # strip trailing _X_Y
        if base == rule:
            out.append(x)
    if not out:
        out = sorted(glob.glob(os.path.join(root, f"{pack}__*.xif")))
    return out


def _model_blocks(txt, dataset):
    """Body of every `[MODEL: dataset=<dataset> ...]` block.
    Tolerates whitespace + quoting variants:
      [MODEL: dataset = "x"]  [MODEL:dataset = x]  [MODEL: dataset="x", model=Audit]
    """
    hdr = re.compile(
        r"\[MODEL:\s*dataset\s*=\s*\"?" + re.escape(dataset) + r"\"?\s*(?:,[^\]]*)?\]",
        re.I,
    )
    nexthdr = re.compile(r"\[MODEL:", re.I)
    blocks = []
    for m in hdr.finditer(txt):
        s = m.end()
        n = nexthdr.search(txt, s)
        blocks.append(txt[s : (n.start() if n else len(txt))])
    return blocks


def _values(cond):
    """Literal set from `in ("a","b")` / `in("a","b")` or `= "x"`."""
    m = re.search(r"\bin\s*\((.*?)\)", cond, re.S)
    if m:
        return [v for v in re.findall(r"[\"']([^\"']*)[\"']", m.group(1))]
    m = re.search(r"=\s*[\"']([^\"']+)[\"']", cond)
    return [m.group(1)] if m else []


def _is_catchall(cond):
    return bool(re.search(r"\bnot\s+in\b|!=|<>", cond))


def _split_or(cond):
    """Split a filter condition on TOP-LEVEL `or`, respecting parens and quotes.

    A gate is frequently a disjunction across DIFFERENT fields, and reading only the first
    disjunct understates it. The Windows rule is the clear case:

        filter channel in ("System","Application","Directory Service")
            or provider_name in ("Microsoft-Windows-PowerShell", ...)
            or provider_name contains "Microsoft-Windows-Security-"

    Taking only `channel` reports the gate as three channel values, so a correct
    `channel: Security` event — which enters through the THIRD disjunct and was verified
    end-to-end mapping 52 xdm fields — is reported as failing the gate.
    """
    parts, buf, depth, quote = [], [], 0, None
    i = 0
    while i < len(cond):
        c = cond[i]
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'":
            quote = c
            buf.append(c)
        elif c == "(":
            depth += 1
            buf.append(c)
        elif c == ")":
            depth -= 1
            buf.append(c)
        elif depth == 0 and cond[i:i + 4].lower() in (" or ",) and i + 4 <= len(cond):
            parts.append("".join(buf).strip())
            buf = []
            i += 4
            continue
        else:
            buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p]


def _contains_literal(cond):
    """`field contains "X"` -> X. A substring gate, satisfied by any value containing X."""
    m = re.search(r"\bcontains\s+[\"']([^\"']+)[\"']", cond, re.I)
    return m.group(1) if m else None


def _alt_gates(cond):
    """Every disjunct of `cond` as {field, values, contains} — the full gate, not just the first."""
    alts = []
    for part in _split_or(cond):
        fld = _gate_field_of(part)
        if not fld:
            continue
        sub = _contains_literal(part)
        vals = _values(part) if sub is None else []
        if vals or sub:
            alts.append({"field": fld, "values": sorted(set(vals)), "contains": sub})
    return alts


def _stages(blk):
    """Pipe/`;`-separated stages, whitespace-normalized, comments stripped.
    A `/* ... */` or `//` comment between the MODEL header and the leading
    `filter` (e.g. CloudTrail) would otherwise hide the gate. NOTE: a literal
    `|` inside a regex string in a filter would mis-split — none of the
    validated gate filters use that form (they are plain `in (...)` / `= "x"`)."""
    blk = re.sub(r"/\*.*?\*/", " ", blk, flags=re.S)        # block comments
    blk = re.sub(r"//[^\n]*", " ", blk)                     # line comments
    return [" ".join(s.split()) for s in re.split(r"[|;]", blk) if s.split()]


# Scalar wrappers a gate may cast the field through before comparing. The gate
# `to_string(event_id) in ("1200", ...)` gates on event_id, not on to_string --
# reading the first identifier verbatim names the FUNCTION and then reports the
# gate unsatisfiable no matter what the schema seeds. Value-preserving for the
# purposes of "which field must the schema seed".
_CAST_FNS = (
    "to_string", "to_integer", "to_number", "to_float", "to_boolean",
    "lowercase", "uppercase", "trim", "ltrim", "rtrim",
)
_CAST_RE = re.compile(
    r"^(?:" + "|".join(_CAST_FNS) + r")\s*\(\s*([A-Za-z0-9_.]+)", re.I)


# `json_extract_scalar(details, "$.type")` gates on the JSON LEAF details.type,
# not on a column called json_extract_scalar. The bundle already expresses nested
# fields with exactly this dotted-leaf convention, so resolving it here yields a
# name the schema can actually declare and the generator can pin.
_JSONX_RE = re.compile(
    r"^json_extract(?:_scalar)?\s*\(\s*([A-Za-z0-9_]+)\s*,\s*[\"']\$\.([^\"']+)[\"']",
    re.I)


def _gate_field_of(cond):
    """Name the field a filter condition gates on, unwrapping scalar casts.

    Unwraps one level only: nested casts on a gate field do not occur in the
    rules we have, and unwrapping blindly would misread `coalesce(a, b)` --
    which has genuinely different semantics -- as gating on `a`.
    """
    m = _JSONX_RE.match(cond)
    if m:
        return "%s.%s" % (m.group(1), m.group(2).replace('"', ""))
    m = _CAST_RE.match(cond)
    if m:
        return m.group(1)
    m = re.match(r"([A-Za-z0-9_.]+)", cond)
    tok = m.group(1) if m else None
    # A bare identifier immediately followed by "(" is a FUNCTION, not a field.
    # Naming it as the gate invents a column that cannot exist -- which is how a
    # field literally called `json_extract_scalar` got written into a schema.
    if tok and re.match(r"^%s\s*\(" % re.escape(tok), cond):
        return None
    return tok


def _classify_block(blk):
    """Return (kind, gate_field, values_list, alt_gates) for one MODEL block.
    kind in {"unconditional", "gated"}.

    `alt_gates` carries EVERY disjunct of the filter, not just the one on gate_field, so a
    caller can tell whether an event clears the gate by some other branch. gate_field and
    values keep their original meaning for backwards compatibility.
    """
    gate_field = None
    values = []
    alts = []
    for st in _stages(blk):
        if st.startswith("filter"):
            cond = st[len("filter"):].strip()
            if _is_catchall(cond):
                return ("unconditional", None, [], [])      # catch-all branch
            alts += _alt_gates(cond)
            fld = _gate_field_of(cond)
            if gate_field is None:
                gate_field = fld
            if fld == gate_field:
                values += _values(cond)
        elif "xdm." in st and gate_field is None:
            return ("unconditional", None, [], [])          # mapped before any gate
    if gate_field is None:
        return ("unconditional", None, [], [])
    return ("gated", gate_field, values, alts)


# XSIAM convention: rule-derived intermediates are prefixed; raw payload
# fields are not. Lets us tell a seedable raw gate (`eventType`, `Category`)
# from a rule-computed one (`get_category`, `is_auth`) WITHOUT mistaking the
# gate's own `filter Category = "x"` / `if(eventType = "y", ...)` for a def.
_DERIVED_PREFIXES = ("get_", "check_", "tmp_", "is_", "has_", "parsed_")


def _seed_fields(blocks, gate_field):
    """Raw field(s) a simulated payload can carry to clear the gate.
    Non-derived field -> itself. Derived field (`get_category`) -> the raw
    fields inside its `= coalesce(a, b)` definition. Derived + unresolved
    (e.g. `is_auth` from classification logic) -> None (computed)."""
    if not gate_field.startswith(_DERIVED_PREFIXES):
        return [gate_field]                                 # raw payload field
    for blk in blocks:
        for st in _stages(blk):
            if st.startswith("filter"):
                continue
            am = re.search(
                r"\b" + re.escape(gate_field) + r"\s*=\s*coalesce\s*\((.*?)\)", st, re.S)
            if am:
                return [t.strip() for t in am.group(1).split(",")]
    return None                                             # derived, unresolved


def classify(pack, rule, dataset, mr_root=MR):
    files = _version_files(pack, rule, mr_root)
    if not files:
        return {"kind": "not_found", "detail": f"no .xif for {pack}__{rule}*"}
    saw_block = False
    saw_uncond = False
    gated_field = None
    values = set()
    rules_used = []
    all_blocks = []
    all_alts = []
    seen_alts = set()
    for f in files:
        blocks = _model_blocks(open(f, errors="ignore").read(), dataset)
        if blocks:
            saw_block = True
            rules_used.append(os.path.basename(f))
            all_blocks += blocks
        for blk in blocks:
            kind, fld, vals, alts = _classify_block(blk)
            if kind == "unconditional":
                saw_uncond = True
            else:
                if gated_field is None:
                    gated_field = fld
                if fld == gated_field:
                    values.update(vals)
                for a in alts:
                    key = (a["field"], a["contains"], tuple(a["values"]))
                    if key not in seen_alts:
                        seen_alts.add(key)
                        all_alts.append(a)
    if not saw_block:
        return {"kind": "not_found", "dataset": dataset,
                "files": [os.path.basename(f) for f in files],
                "detail": f"no [MODEL] block for {dataset}"}
    # Any unconditional/catch-all path means the dataset maps regardless.
    if saw_uncond or gated_field is None:
        return {"kind": "unconditional", "dataset": dataset, "rules": rules_used,
                "detail": "maps unconditionally (no leading filter or catch-all branch)"}
    if gated_field.startswith("_"):
        return {"kind": "meta", "dataset": dataset, "rules": rules_used,
                "gate_field": gated_field, "values": sorted(values),
                "detail": "META gate — stamped by ingestion layer, not settable from payload"}
    seed_fields = _seed_fields(all_blocks, gated_field)
    if seed_fields is None or not values:
        # derived-and-unresolved, or a non-string gate (e.g. `is_auth = true`)
        # with no literal value set — not a deterministically-seedable gate.
        return {"kind": "computed", "dataset": dataset, "rules": rules_used,
                "gate_field": gated_field, "values": sorted(values),
                "detail": "computed/non-literal gate — no direct raw seed value"}
    kind = "function" if seed_fields != [gated_field] else "raw"
    return {"kind": kind, "dataset": dataset, "rules": rules_used,
            "gate_field": gated_field, "seed_fields": seed_fields,
            "values": sorted(values), "alt_gates": all_alts,
            "detail": f"seed one of {seed_fields} to a value in {sorted(values)}"
                      + (f", OR satisfy any of {all_alts}" if len(all_alts) > 1 else "")}


def analyze(ds_id, mr_root=MR):
    try:
        pack, rule, dataset = ds_id.split("__", 2)
    except ValueError:
        return {"id": ds_id, "kind": "error", "detail": "id not pack__rule__dataset"}
    out = classify(pack, rule, dataset, mr_root)
    out["id"] = ds_id
    return out


if __name__ == "__main__":
    for ds in sys.argv[1:]:
        print(json.dumps(analyze(ds), indent=2))
