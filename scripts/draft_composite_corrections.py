#!/usr/bin/env python3
"""
draft_composite_corrections.py — maintainer script that drafts
Pattern-P3 data_source.yaml corrections per bundled pack.

Background
==========

The base cortex-extractor walks each pack's compiled schema.json
(which declares top-level field NAMES + their type but nothing about
nested shape) and assumes top-level columns are flat strings. It does
NOT walk the .xif AST to detect the `field -> nested` deref pattern
that marks composite shapes. Left uncorrected, composite fields are
flattened to `type:string` with heuristically-wrong descriptions taken
from one extracted XDM property.

Pattern-P3 (the corrected shape) keeps top-level wire entries AND
adds dotted-path leaf entries for every nested path the modeling
rule dereferences.

What this script does
=====================

For each pack under bundles/spark/data-sources/:

  1. Read the current data_source.yaml (carry forward all non-fields
     metadata — id, vendor, product, logo, version, use_cases, etc.).
  2. Read the corresponding .xif under
     scripts/maintainer/modeling_rules/<pack>__<rule>.xif if it exists.
  3. Read the compiled schema.json under
     bundles/spark/connectors/cortex-content/baked/Packs/<pack>/ModelingRules/<rule>/<rule>_schema.json
     if it exists.
  4. Parse the XIF — strip comments, split into [MODEL:]/[RULE:] blocks,
     resolve `call <rule>` directives.
  5. For each [MODEL:] block matching the pack's dataset_name, analyze
     the body for:
       - `field -> path` derefs → mark `field` composite + add leaf
       - `field -> []` array derefs
       - `arraymap(field -> [], "@element" -> sub)` → leaf `field[].sub`
       - `json_extract_(scalar|array)(field, "$.path")` → composite + leaf
       - XDM target assignments → type hints for scalars
       - `parse_timestamp(...)`, `to_integer(...)`, etc. → type hints
  6. Cross-reference dereffed identifiers against schema.json's columns;
     local-variable derefs (computed during alter) are discarded.
  7. Emit a DRAFT data_source.yaml with:
       - Top-level wire entries (type:json for composites + example)
       - Dotted-path leaves (per-leaf scalar type + stub description
         naming the XDM target it drives + stub example)
  8. Validate emitted YAML against data_source.schema.json.

The DRAFT is then manually reviewed pack-by-pack — descriptions and
examples upgraded to natural-language vendor-specific content.

Usage
=====

  python3 scripts/draft_composite_corrections.py                  # all
  python3 scripts/draft_composite_corrections.py --pack <pack_id> # one
  python3 scripts/draft_composite_corrections.py --dry-run        # no writes
  python3 scripts/draft_composite_corrections.py --report-only    # parser stats

Per scripts/CLAUDE.md, this is maintainer-only research tooling.
Runtime never invokes this — its OUTPUT is the committed YAMLs.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

# Allow running from anywhere in the repo
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_SOURCES_DIR = REPO_ROOT / "bundles/spark/data-sources"
MODELING_RULES_DIR = REPO_ROOT / "scripts/maintainer/modeling_rules"
BAKED_PACKS_DIR = REPO_ROOT / "bundles/spark/connectors/cortex-content/baked/Packs"
SCHEMA_PATH = DATA_SOURCES_DIR / "data_source.schema.json"


# ─── XIF parsing primitives ──────────────────────────────────────────

COMMENT_BLOCK_RE = re.compile(r'/\*.*?\*/', re.DOTALL)
COMMENT_LINE_RE = re.compile(r'//[^\n]*')

# Block headers — [MODEL: ...] and [RULE: ...]
BLOCK_HEADER_RE = re.compile(r'\[(?P<kind>MODEL|RULE):[^\]]+\]', re.IGNORECASE)
DATASET_RE = re.compile(r'dataset\s*=\s*"?([a-zA-Z0-9_]+)"?', re.IGNORECASE)
RULE_NAME_RE = re.compile(r'\[RULE:\s*([a-zA-Z0-9_]+)\s*\]', re.IGNORECASE)

# `call <rule_name>` directive
CALL_RE = re.compile(r'(?:^|\n|\|)\s*call\s+([a-zA-Z_][a-zA-Z0-9_]*)\b', re.IGNORECASE)

# Deref patterns
# `field -> []` (standalone array iteration)
DEREF_ARR_RE = re.compile(r'`?([a-zA-Z_][a-zA-Z0-9_]*)`?\s*->\s*\[\]')

# `field -> path` (path may be `a`, `a.b`, `a.b.c`, optionally `[]` suffix)
# We capture both the source name and the full path. Note: this also
# matches inside arraymap(...) so we filter against schema_columns later.
DEREF_PATH_RE = re.compile(
    r'`?([a-zA-Z_][a-zA-Z0-9_]*)`?\s*->\s*([a-zA-Z_][a-zA-Z0-9_.]*)(\[\])?'
)

# `"@element" -> path` (per-element access inside arraymap)
ELEMENT_SUB_RE = re.compile(r'"@element"\s*->\s*([a-zA-Z_][a-zA-Z0-9_.]*)')

# arraymap(field -> [], ...) — direct array-of-objects iteration
ARRAYMAP_DIRECT_RE = re.compile(
    r'arraymap\s*\(\s*`?([a-zA-Z_][a-zA-Z0-9_]*)`?\s*->\s*(?:([a-zA-Z_][a-zA-Z_0-9.]*))?\[\]'
)

# arraymap(local_var, ...) — iteration over a previously-bound local
ARRAYMAP_VAR_RE = re.compile(
    r'arraymap\s*\(\s*([a-zA-Z_][a-zA-Z_0-9]*)\s*,'
)

# Local variable binding: `name = field -> path?[]?`
# Two flavors:
#   `name = field -> []`          (array iteration; iterates @element)
#   `name = field -> path[]`      (array sub-path iteration)
#   `name = field -> path`        (single scalar/object property access)
#   `name = field -> path1.path2` (deep property access)
# The `[]` is OPTIONAL — both array AND non-array bindings need to be
# tracked so that later `xdm.X = name` correctly back-propagates the
# target to the source field/path. The `is_array_marker` capture tells
# us whether arraymap(name, ...) is valid against this binding.
LOCAL_BINDING_RE = re.compile(
    r'(?:^|\n|,|\|)\s*'
    r'([a-zA-Z_][a-zA-Z_0-9]*)'           # local name
    r'\s*=\s*'
    r'`?([a-zA-Z_][a-zA-Z_0-9]*)`?'      # source field
    r'\s*->\s*'
    r'(?:([a-zA-Z_][a-zA-Z_0-9.]*))?'    # optional sub-path
    r'(\[\])?'                            # OPTIONAL array marker
)

# JSONPath extracts (alternative to `->`)
JSONPATH_SCALAR_RE = re.compile(
    r'json_extract_scalar\s*\(\s*`?([a-zA-Z_][a-zA-Z0-9_]*)`?\s*,\s*"\$\.([^"]+)"\s*\)'
)
JSONPATH_ARRAY_RE = re.compile(
    r'json_extract_array\s*\(\s*`?([a-zA-Z_][a-zA-Z0-9_]*)`?\s*,\s*"\$\.([^"]+)"\s*\)'
)

# XDM target assignment: `xdm.path = expr,`  OR  `XDM.Path = expr,`
# Captures the lowercased dotted target + the RHS (until comma/newline/;).
XDM_TARGET_RE = re.compile(
    r'(?:xdm|XDM)\.([a-zA-Z0-9_.]+)\s*=\s*([^,;\n]+?)(?=[,;\n]|$)',
    re.IGNORECASE,
)

# parse_timestamp("%fmt", field) → field is datetime
PARSE_TIMESTAMP_RE = re.compile(
    r'parse_timestamp\s*\(\s*"[^"]*"\s*,\s*`?([a-zA-Z_][a-zA-Z0-9_]*)`?\s*\)'
)

# Numeric / boolean coercion: to_integer(field) / to_boolean(field) etc.
COERCION_RE = re.compile(
    r'(to_integer|to_boolean|to_float|to_number)\s*\(\s*`?([a-zA-Z_][a-zA-Z0-9_]*)`?\s*\)'
)

# Bare-field on XDM RHS — `xdm.X = field` (no function wrap, no deref)
BARE_FIELD_RE = re.compile(r'^`?([a-zA-Z_][a-zA-Z0-9_]*)`?$')

# Any `name = <expr>` LHS that's NOT an `xdm.…` assignment. Captures
# locals computed via regextract / arraystring / if() / concat / etc.
# Used to flag carry-forward entries the root extractor wrongly
# preserved (e.g. `get_ip = arraystring(regextract(_raw_log, …), "")`).
NON_DEREF_LOCAL_RE = re.compile(
    r'(?:^|\n|,|\|)\s*'
    r'(?!xdm\.|XDM\.)'                    # not an xdm target
    r'([a-zA-Z_][a-zA-Z0-9_]*)'           # local name (no dots)
    r'\s*=\s*'
)


# ─── Data classes ────────────────────────────────────────────────────

@dataclass
class FieldInfo:
    """What we discover about a single field (top-level OR dotted-path leaf)."""
    name: str
    is_array: bool = False
    is_composite: bool = False  # truthy if dereffed anywhere
    type_hints: set = field(default_factory=set)
    xdm_targets: set = field(default_factory=set)
    is_leaf: bool = False  # True if this is a dotted-path entry (not top-level)


@dataclass
class XifAnalysis:
    """Per-dataset analysis output."""
    dataset: str
    fields: dict = field(default_factory=dict)  # name -> FieldInfo
    # All `alter`-local names captured anywhere in the model body.
    # Distinct from `fields` — locals are intermediate computation aliases
    # the root extractor wrongly captures as schema fields. We
    # surface them here so carry-forward can prune them.
    local_names: set = field(default_factory=set)


@dataclass
class ParserReport:
    """Diagnostics from a parser run — collected for the final report."""
    packs_processed: int = 0
    packs_with_xif: int = 0
    packs_without_xif: int = 0
    packs_with_composites: int = 0
    packs_pure_scalar: int = 0
    packs_skipped_curated: int = 0
    leaves_drafted: int = 0
    failures: list = field(default_factory=list)  # [(pack_id, reason)]


# ─── XIF parsing ─────────────────────────────────────────────────────

def strip_comments(text: str) -> str:
    """Remove /* ... */ block + // line comments."""
    text = COMMENT_BLOCK_RE.sub(' ', text)
    text = COMMENT_LINE_RE.sub('', text)
    return text


def split_blocks(xif_text: str) -> tuple[dict, dict]:
    """
    Split XIF into [MODEL: dataset=X] blocks and [RULE: name] blocks.
    Returns (model_blocks, rule_blocks).
    """
    cleaned = strip_comments(xif_text)

    headers = [(m.start(), m.end(), m.group()) for m in BLOCK_HEADER_RE.finditer(cleaned)]

    model_blocks = {}
    rule_blocks = {}

    for i, (start, end, header) in enumerate(headers):
        body_start = end
        body_end = headers[i + 1][0] if i + 1 < len(headers) else len(cleaned)
        body = cleaned[body_start:body_end]

        is_model = header.lower().startswith('[model:')
        if is_model:
            m = DATASET_RE.search(header)
            if m:
                model_blocks[m.group(1)] = body
        else:
            m = RULE_NAME_RE.match(header)
            if m:
                rule_blocks[m.group(1)] = body

    return model_blocks, rule_blocks


def expand_rule_calls(body: str, rule_blocks: dict, visited: Optional[set] = None) -> str:
    """Recursively inline `call <rule>` references into the body."""
    if visited is None:
        visited = set()

    def replace_call(m):
        rule_name = m.group(1)
        if rule_name in visited:
            return ''
        if rule_name not in rule_blocks:
            return ''
        nested = visited | {rule_name}
        return ' ' + expand_rule_calls(rule_blocks[rule_name], rule_blocks, nested) + ' '

    return CALL_RE.sub(replace_call, body)


def find_arraymap_extent(body: str, start: int) -> int:
    """
    Given `start` is the position right after `arraymap(field -> [],`,
    return the index of the matching closing paren.
    """
    depth = 1
    pos = start
    while pos < len(body) and depth > 0:
        c = body[pos]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        pos += 1
    return pos


# XDM = <expression> — capture the FULL expression (across nested parens)
XDM_ASSIGNMENT_RE = re.compile(
    r'(?:xdm|XDM)\.([a-zA-Z0-9_.]+)\s*=\s*',
    re.IGNORECASE,
)


def find_balanced_extent(body: str, start: int) -> int:
    """Walk balanced parens + brackets from `start` until we hit
    a top-level comma or semicolon (the assignment terminator)."""
    depth_paren = 0
    depth_bracket = 0
    pos = start
    while pos < len(body):
        c = body[pos]
        if c == '(':
            depth_paren += 1
        elif c == ')':
            if depth_paren == 0:
                return pos
            depth_paren -= 1
        elif c == '[':
            depth_bracket += 1
        elif c == ']':
            depth_bracket -= 1
        elif c in ',;' and depth_paren == 0 and depth_bracket == 0:
            return pos
        elif c == '\n' and depth_paren == 0 and depth_bracket == 0:
            return pos
        pos += 1
    return pos


def analyze_block(body: str, schema_columns: set) -> tuple[dict, set]:
    """Walk a model-body. Returns ({field_name: FieldInfo}, {local_names}).

    `local_names` is the set of all `name = ...` LHS identifiers — used
    later to prune carry-forward extras that are XIF locals masquerading
    as wire fields (a root-extractor artifact)."""
    fields: dict = {}
    all_locals: set = set()

    def get_or_create(name: str, *, is_leaf: bool = False) -> FieldInfo:
        if name not in fields:
            fields[name] = FieldInfo(name=name, is_leaf=is_leaf)
        return fields[name]

    # 1. `field -> []` standalone (array iteration without sub-path)
    for m in DEREF_ARR_RE.finditer(body):
        src = m.group(1)
        if src not in schema_columns:
            continue
        info = get_or_create(src)
        info.is_composite = True
        info.is_array = True

    # 2. `field -> path` (object property access; path may end in [])
    for m in DEREF_PATH_RE.finditer(body):
        src, path, arr = m.group(1), m.group(2), m.group(3)
        if src not in schema_columns:
            continue
        info = get_or_create(src)
        info.is_composite = True
        leaf_name = f"{src}.{path}"
        leaf = get_or_create(leaf_name, is_leaf=True)
        if arr:
            leaf.is_array = True

    # 3a. Build local-binding map. Captures both:
    #   `local = field -> path` (scalar/object) — for XDM target propagation
    #   `local = field -> path[]` (array) — also enables arraymap(local, ...)
    # The trailing `[]` is captured separately as `is_array` so downstream
    # logic can distinguish.
    bindings: dict = {}  # local_name -> (source_field, sub_path)
    array_bindings: set = set()  # subset of `bindings` that came from a `[]` deref
    for m in LOCAL_BINDING_RE.finditer(body):
        local = m.group(1)
        src = m.group(2)
        sub = m.group(3) or ''
        is_array = bool(m.group(4))
        # Track every local LHS — even when src is not in schema_columns
        # (e.g., chained `b = regextract(a, ...)` where `a` is itself a
        # local). These names must NEVER appear as carry-forward fields.
        if local not in schema_columns:
            all_locals.add(local)
        if src in schema_columns and local not in schema_columns:
            bindings[local] = (src, sub)
            if is_array:
                array_bindings.add(local)

    # Also capture standalone `name = <expression>` LHSes that aren't
    # `field -> path` derefs (regextract, arraystring, if(), etc.). The
    # root extractor harvests these too — they're the bulk of the
    # bogus `get_*`, `src_ip_v[46]` artifacts.
    for m in NON_DEREF_LOCAL_RE.finditer(body):
        local = m.group(1)
        if local not in schema_columns:
            all_locals.add(local)

    # 3b. `arraymap(field -> path?[], "@element" -> X)` — direct iteration
    for am in ARRAYMAP_DIRECT_RE.finditer(body):
        src, sub = am.group(1), am.group(2) or ''
        if src not in schema_columns:
            continue
        info = get_or_create(src)
        info.is_composite = True
        if not sub:
            info.is_array = True
        close = find_arraymap_extent(body, am.end())
        scope = body[am.end():close]
        prefix = f"{src}.{sub}[]" if sub else f"{src}[]"
        for em in ELEMENT_SUB_RE.finditer(scope):
            leaf_name = f"{prefix}.{em.group(1)}"
            get_or_create(leaf_name, is_leaf=True)

    # 3c. `arraymap(local_var, ...)` where local_var resolves via array bindings
    for am in ARRAYMAP_VAR_RE.finditer(body):
        local = am.group(1)
        if local not in array_bindings:  # must be an array binding for arraymap
            continue
        src, sub = bindings[local]
        info = get_or_create(src)
        info.is_composite = True
        if not sub:
            info.is_array = True
        close = find_arraymap_extent(body, am.end())
        scope = body[am.end():close]
        prefix = f"{src}.{sub}[]" if sub else f"{src}[]"
        for em in ELEMENT_SUB_RE.finditer(scope):
            leaf_name = f"{prefix}.{em.group(1)}"
            get_or_create(leaf_name, is_leaf=True)

    # 4. JSONPath scalar / array extracts
    for m in JSONPATH_SCALAR_RE.finditer(body):
        src, path = m.group(1), m.group(2)
        if src not in schema_columns:
            continue
        info = get_or_create(src)
        info.is_composite = True
        clean_path = path.replace('"', '').replace("'", '')
        leaf_name = f"{src}.{clean_path}"
        get_or_create(leaf_name, is_leaf=True)

    for m in JSONPATH_ARRAY_RE.finditer(body):
        src, path = m.group(1), m.group(2)
        if src not in schema_columns:
            continue
        info = get_or_create(src)
        info.is_composite = True
        clean_path = path.replace('"', '').replace("'", '')
        leaf = get_or_create(f"{src}.{clean_path}", is_leaf=True)
        leaf.is_array = True

    # 5. XDM target assignments → type hints for scalars
    for m in XDM_TARGET_RE.finditer(body):
        target = m.group(1).lower()
        rhs = m.group(2).strip()
        bare = BARE_FIELD_RE.match(rhs)
        if bare:
            src = bare.group(1)
            if src in schema_columns:
                info = get_or_create(src)
                info.xdm_targets.add(target)

    # 6. parse_timestamp → datetime
    for m in PARSE_TIMESTAMP_RE.finditer(body):
        src = m.group(1)
        if src in schema_columns:
            info = get_or_create(src)
            info.type_hints.add('datetime')

    # 7. Numeric / boolean coercion
    for m in COERCION_RE.finditer(body):
        func, src = m.group(1), m.group(2)
        if src not in schema_columns:
            continue
        info = get_or_create(src)
        hint = {
            'to_integer': 'integer',
            'to_boolean': 'boolean',
            'to_float': 'float',
            'to_number': 'float',
        }.get(func)
        if hint:
            info.type_hints.add(hint)

    # 8. Propagate XDM targets to LEAVES (not just top-level fields).
    # For each `xdm.X = <expression>` clause, scan the expression for
    # every `<field> -> <path>` deref. The XDM target `xdm.X` then drives
    # the leaf `<field>.<path>`. Also resolves local-variable bindings:
    # if `local = field -> path` and `xdm.X = local`, attribute `xdm.X`
    # to `<field>.<path>`.
    for m in XDM_ASSIGNMENT_RE.finditer(body):
        target = m.group(1).lower()
        rhs_start = m.end()
        rhs_end = find_balanced_extent(body, rhs_start)
        rhs = body[rhs_start:rhs_end]

        # 8a. Direct derefs in the expression: `field -> path`
        for d in DEREF_PATH_RE.finditer(rhs):
            src, path = d.group(1), d.group(2)
            if src not in schema_columns:
                continue
            leaf_name = f"{src}.{path}"
            if leaf_name in fields:
                fields[leaf_name].xdm_targets.add(target)

        # 8b. JSONPath extracts: `json_extract_scalar(field, "$.path")`
        for j in JSONPATH_SCALAR_RE.finditer(rhs):
            src, path = j.group(1), j.group(2)
            if src not in schema_columns:
                continue
            clean = path.replace('"', '').replace("'", '')
            leaf_name = f"{src}.{clean}"
            if leaf_name in fields:
                fields[leaf_name].xdm_targets.add(target)
        for j in JSONPATH_ARRAY_RE.finditer(rhs):
            src, path = j.group(1), j.group(2)
            if src not in schema_columns:
                continue
            clean = path.replace('"', '').replace("'", '')
            leaf_name = f"{src}.{clean}"
            if leaf_name in fields:
                fields[leaf_name].xdm_targets.add(target)

        # 8c. Local-variable references: `xdm.X = local_var` where
        # local_var was bound earlier. Resolve through `bindings`.
        for word in re.finditer(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', rhs):
            local = word.group(1)
            if local in bindings:
                src, sub = bindings[local]
                leaf_name = f"{src}.{sub}" if sub else src
                if leaf_name in fields:
                    fields[leaf_name].xdm_targets.add(target)
                # Also propagate to per-element leaves if the array has
                # @element subs visible (rare in this case)

    # 9. Mark arrays-of-objects as type:json (not string + is_array).
    # When we have a leaf like `field.sub` AND `field.sub[].X` exists,
    # the `field.sub` MUST be json (composite), not a scalar.
    array_of_obj_names = set()
    for name in fields:
        if '[].' in name:
            # Strip the [].X suffix to get the parent leaf name
            parent = name.split('[].')[0]
            array_of_obj_names.add(parent)
    for parent in array_of_obj_names:
        if parent in fields:
            fields[parent].is_composite = True
            fields[parent].is_array = True

    return fields, all_locals


# ─── Type inference + draft emission ─────────────────────────────────

def infer_type(info: FieldInfo, schema_type: Optional[str] = None) -> str:
    """Decide the YAML type for a field."""
    if info.is_composite:
        return 'json'

    if 'datetime' in info.type_hints:
        return 'datetime'
    if 'boolean' in info.type_hints:
        return 'boolean'
    if 'integer' in info.type_hints:
        return 'integer'
    if 'float' in info.type_hints:
        return 'float'

    # IPv4/IPv6 inference from XDM targets
    has_ipv4 = any('ipv4' in t for t in info.xdm_targets)
    has_ipv6 = any('ipv6' in t for t in info.xdm_targets)
    if has_ipv4 and not has_ipv6:
        return 'ipv4'
    if has_ipv6 and not has_ipv4:
        return 'ipv6'
    if has_ipv4 and has_ipv6:
        return 'string'

    # Email / host / hash / mac / port / url / file path
    if any(t.endswith('.sender') or t.endswith('.recipients')
           or t.endswith('.cc') or t.endswith('.bcc')
           or t.endswith('.return_path')
           for t in info.xdm_targets):
        return 'email'
    if any('host.hostname' in t or 'host.fqdn' in t for t in info.xdm_targets):
        return 'host'
    if any('host.mac_addresses' in t or t.endswith('.mac') for t in info.xdm_targets):
        return 'mac'
    for h, ty in [('md5', 'hash_md5'), ('sha1', 'hash_sha1'), ('sha256', 'hash_sha256')]:
        if any(h in t for t in info.xdm_targets):
            return ty
    if any('.url' in t for t in info.xdm_targets):
        return 'url'
    # `xdm.*.user.username` → person name (type:user). `xdm.*.user.identifier`
    # → opaque ID (type:string). Distinguish — these are different concerns.
    if any('.username' in t for t in info.xdm_targets):
        return 'user'
    if any('.port' in t for t in info.xdm_targets):
        return 'integer_port'
    if any('sent_bytes' in t or 'rcvd_bytes' in t or 'size_bytes' in t
           for t in info.xdm_targets):
        return 'integer_byte_count'
    if any('country' in t for t in info.xdm_targets):
        return 'country_code'
    if any('file.filename' in t or 'file.path' in t or 'process.executable.filename' in t
           for t in info.xdm_targets):
        return 'file_path'

    # Name-pattern heuristics on the field name itself (no XDM hint)
    name_low = info.name.lower()
    if name_low.endswith('.md5') or name_low == 'md5':
        return 'hash_md5'
    if name_low.endswith('.sha1') or name_low == 'sha1':
        return 'hash_sha1'
    if name_low.endswith('.sha256') or name_low == 'sha256':
        return 'hash_sha256'
    if name_low.endswith('.mac') or name_low.endswith('_mac'):
        return 'mac'
    if name_low.endswith('.port') or name_low.endswith('_port') \
            or name_low.endswith('port'):
        # Conservative — only if no other hint
        if not info.is_composite:
            return 'integer_port'
    if name_low.endswith('.hostname') or name_low.endswith('_hostname'):
        return 'host'

    # Schema-derived hints
    if schema_type in ('int', 'integer'):
        return 'integer'
    if schema_type == 'bool':
        return 'boolean'

    return 'string'


# Stub example generator — minimal, just enough to be illustrative
STUB_EXAMPLES = {
    'string': 'sample',
    'integer': 42,
    'float': 3.14,
    'boolean': True,
    'ipv4': '203.0.113.42',
    'ipv6': '2001:db8::1',
    'mac': '00:1A:2B:3C:4D:5E',
    'email': 'user@example.com',
    'host': 'host.example.com',
    'url': 'https://example.com/path',
    'domain': 'example.com',
    'datetime': '2026-05-26T12:34:56Z',
    'timestamp_ms': 1716729296000,
    'country_code': 'US',
    'hash_md5': '5d41402abc4b2a76b9719d911017c592',
    'hash_sha1': 'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d',
    'hash_sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'file_path': '/var/log/example.log',
    'user': 'jsmith',
    'json': '{}',
}


def stub_example(field_type: str, field_name: str) -> object:
    return STUB_EXAMPLES.get(field_type, 'sample')


def stub_description(info: FieldInfo, inferred_type: str) -> str:
    """Brief stub. Human reviewer will upgrade to natural-language."""
    parts = []
    if info.is_composite and info.is_array:
        parts.append('Array of objects — see leaf entries for per-element fields.')
    elif info.is_composite:
        parts.append('Composite object — see leaf entries for nested paths.')
    elif info.is_leaf:
        parent = info.name.split('.')[0].rstrip('[]')
        parts.append(f"Leaf under `{parent}`.")
    if info.xdm_targets:
        targets = sorted(info.xdm_targets)
        if len(targets) == 1:
            parts.append(f"Drives xdm.{targets[0]}.")
        elif len(targets) <= 3:
            parts.append(f"Drives xdm.{', xdm.'.join(targets)}.")
        else:
            parts.append(f"Drives xdm.{targets[0]} (and {len(targets) - 1} more).")
    if not parts:
        parts.append('TODO: write description.')
    return ' '.join(parts)


def draft_field(info: FieldInfo, schema_type: Optional[str] = None) -> dict:
    """Render a single FieldInfo as a YAML field dict."""
    inferred = infer_type(info, schema_type)
    entry: dict = {'name': info.name, 'type': inferred}
    if info.is_array:
        entry['is_array'] = True
    entry['description'] = stub_description(info, inferred)
    if inferred != 'json':
        entry['example'] = stub_example(inferred, info.name)
    else:
        entry['example'] = '{}'  # composite stub; human refines
    return entry


# ─── Per-pack orchestration ─────────────────────────────────────────

def load_schema_columns(pack_id: str, pack_dir: Path) -> tuple[set, dict]:
    """
    Look up the baked schema.json for this pack's modeling rule.
    Returns (column_names, column_metadata).
    """
    # pack_id shape: <PackName>__<RuleName>__<DatasetName>
    parts = pack_id.split('__')
    if len(parts) < 3:
        return set(), {}
    pack_name, rule_name, dataset_name = parts[0], parts[1], parts[2]

    schema_path = (
        BAKED_PACKS_DIR
        / pack_name
        / 'ModelingRules'
        / rule_name
        / f'{rule_name}_schema.json'
    )
    if not schema_path.exists():
        return set(), {}
    try:
        data = json.loads(schema_path.read_text())
    except json.JSONDecodeError:
        return set(), {}

    # Schema shape: {dataset_name: {col: {type, is_array}, ...}}
    cols = data.get(dataset_name, {})
    return set(cols.keys()), cols


def load_xif(pack_id: str) -> Optional[str]:
    """Look up the .xif for this pack."""
    parts = pack_id.split('__')
    if len(parts) < 3:
        return None
    pack_name, rule_name = parts[0], parts[1]

    xif_path = MODELING_RULES_DIR / f'{pack_name}__{rule_name}.xif'
    if not xif_path.exists():
        return None
    return xif_path.read_text()


def analyze_pack(pack_id: str) -> tuple[Optional[XifAnalysis], set, dict]:
    """Returns (analysis, schema_columns, schema_meta)."""
    schema_columns, schema_meta = load_schema_columns(pack_id, DATA_SOURCES_DIR / pack_id)
    xif_text = load_xif(pack_id)

    if xif_text is None:
        # No XIF — analysis is just the schema columns as scalars
        analysis = XifAnalysis(dataset='')
        for col in schema_columns:
            info = FieldInfo(name=col)
            analysis.fields[col] = info
        return analysis, schema_columns, schema_meta

    # Parse XIF, find the right [MODEL:] block matching this pack's dataset
    parts = pack_id.split('__')
    dataset_name = parts[2] if len(parts) >= 3 else ''

    model_blocks, rule_blocks = split_blocks(xif_text)

    body = model_blocks.get(dataset_name)
    if body is None:
        # XIF exists but no matching dataset block — treat as scalar-only
        analysis = XifAnalysis(dataset=dataset_name)
        for col in schema_columns:
            analysis.fields[col] = FieldInfo(name=col)
        return analysis, schema_columns, schema_meta

    # Inline rule calls
    body = expand_rule_calls(body, rule_blocks)

    fields, local_names = analyze_block(body, schema_columns)

    # Ensure EVERY schema column has an entry (even if not dereffed)
    for col in schema_columns:
        if col not in fields:
            fields[col] = FieldInfo(name=col)

    analysis = XifAnalysis(dataset=dataset_name, fields=fields,
                           local_names=local_names)
    return analysis, schema_columns, schema_meta


STUB_DESC_PREFIXES = ('Drives xdm.', 'Leaf path under', 'Leaf under',
                      'TODO:', 'Composite object', 'Array of objects',
                      'Drives xdm.(', 'Leaf path under `')


# Patterns that mark a field name as a root-extractor artifact
# (enum constant, regex char-class fragment, XIF local helper) rather than
# a vendor-emitted field. Used to prune carry-forward extras.
ALL_CAPS_CONST_RE = re.compile(r'^[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)*$')
INTERMEDIATE_HELPER_RE = re.compile(r'^(get|set|tmp|temp|aux|extract)_')


def _is_extractor_artifact(name: str, locals_set: set,
                           schema_cols: set) -> bool:
    """True iff `name` is almost certainly a root-extractor
    artifact (and therefore safe to drop from carry-forward).

    Conservative — protects real vendor fields:
      - `Acct_Input_Packets`, `c_ip_ipv4` (snake_case + lowercase parts)
      - `API_TYPE`, `API_VERSION` (Salesforce uses ALL_CAPS — survives
        because not in the XIF's `locals_set` and not in schema_columns,
        which means it was added by the vendor-doc backfill)

    Hard-drop rules (each requires a corroborating signal):
      1. Single-character names — always regex char-class fragments
         (`[s|S]uccess` → `s`, `S`).
      2. ALL_CAPS_NAME bound in the XIF's locals — enum value or
         XDM_CONST literal that the root extractor wrongly captures
         (e.g. `OPERATION_TYPE_AUTHENTICATION`, `HOPOPT`).
      3. Helper-prefix locals (`get_*`, `set_*`, `tmp_*`, `aux_*`) bound
         in the XIF's locals — intermediate computation aliases.
    """
    if len(name) <= 1:
        return True
    if ALL_CAPS_CONST_RE.match(name) and name in locals_set:
        return True
    if INTERMEDIATE_HELPER_RE.match(name) and name in locals_set:
        return True
    return False

# Types the operator-hand-curated YAMLs may have picked over plain 'string'.
# When an existing entry uses one of these types, we treat the type as
# authoritative — the operator chose it for a reason, don't downgrade.
SPECIFIC_TYPES = frozenset({
    'enum', 'regex', 'ipv4', 'ipv6', 'mac', 'email', 'host', 'url', 'domain',
    'user', 'datetime', 'timestamp_ms', 'integer_port', 'integer_byte_count',
    'integer', 'float', 'boolean', 'hash_md5', 'hash_sha1', 'hash_sha256',
    'file_path', 'country_code', 'string_short', 'string_long', 'json',
})


def _is_fully_curated(current_yaml: dict, analysis: XifAnalysis) -> bool:
    """
    Return True if the existing YAML covers EXACTLY the fields the
    script would emit AND every entry passes _looks_curated. When
    True the script skips the pack — no need to overwrite a
    pristine YAML with a cosmetically-reformatted equivalent.
    """
    existing = current_yaml.get('fields') or []
    existing_by_name = {
        e['name']: e for e in existing if isinstance(e, dict) and 'name' in e
    }
    expected_names = set(analysis.fields.keys())
    if set(existing_by_name.keys()) != expected_names:
        return False
    for entry in existing_by_name.values():
        if not _looks_curated(entry):
            return False
    return True


def _looks_curated(entry: dict) -> bool:
    """
    Heuristic for whether an existing field entry is hand-written.
    A description starting with stub markers OR shorter than 30 chars
    OR matching a placeholder example pattern → not curated.
    """
    desc = (entry.get('description') or '').strip()
    if not desc or len(desc) < 30:
        return False
    for prefix in STUB_DESC_PREFIXES:
        if desc.startswith(prefix):
            return False
    return True


def draft_pack_yaml(pack_id: str, current_yaml: dict, analysis: XifAnalysis,
                    schema_meta: dict, schema_columns: Optional[set] = None,
                    preserve_curated: bool = True) -> dict:
    """
    Build the drafted data_source.yaml dict.
    Preserves all non-fields metadata from the current YAML; replaces
    fields[] with the drafted shape.

    When preserve_curated=True (default):
      1. Field entries the analysis discovers AND match existing
         curated entries: keep the curated description + example,
         but apply the analysis's type classification (so e.g. a
         flat 'string' upgrades to 'json' if XIF says so).
      2. Field entries the analysis DIDN'T discover but exist in the
         current YAML are CARRIED FORWARD AS-IS. This protects
         hand-curated vendor-doc fields that don't appear
         in the modeling rule's schema.json.
      3. Newly-discovered fields with no existing counterpart get
         drafted with stub descriptions + examples.
    """
    drafted = dict(current_yaml)
    drafted['fields'] = []

    # Index existing entries by name for lookup
    existing_by_name = {}
    for entry in current_yaml.get('fields') or []:
        if isinstance(entry, dict) and 'name' in entry:
            existing_by_name[entry['name']] = entry

    top_level = []
    leaves = []
    # Track which existing entries the analysis already covered, so
    # we can preserve the rest at the end.
    covered_names: set = set()

    for name, info in analysis.fields.items():
        col_meta = schema_meta.get(name, {})
        col_type = col_meta.get('type')

        new_entry = draft_field(info, schema_type=col_type)

        if preserve_curated and name in existing_by_name:
            existing = existing_by_name[name]
            covered_names.add(name)
            existing_type = existing.get('type')
            curated_desc = _looks_curated(existing)
            curated_type = existing_type in SPECIFIC_TYPES
            # Intrinsic-property forces: if the existing entry has
            # enum_values, type MUST be enum (likewise regex_pattern
            # → regex). The schema enforces this; we enforce it back.
            forced_enum = 'enum_values' in existing
            forced_regex = 'regex_pattern' in existing

            if curated_desc or curated_type or forced_enum or forced_regex:
                merged = dict(new_entry)
                if curated_desc:
                    merged['description'] = existing.get('description', new_entry['description'])
                    if 'example' in existing:
                        merged['example'] = existing['example']
                # Specific-type wins unless the analysis upgraded to json
                # (composite shape from the XIF beats any prior scalar).
                if curated_type and new_entry.get('type') != 'json':
                    merged['type'] = existing_type
                    if existing.get('is_array'):
                        merged['is_array'] = True
                # Forced types (intrinsic-property fields) take absolute
                # priority — analysis can't downgrade.
                if forced_enum:
                    merged['type'] = 'enum'
                if forced_regex:
                    merged['type'] = 'regex'
                for k in ('enum_values', 'regex_pattern', 'observable_override', 'is_meta'):
                    if k in existing and k not in merged:
                        merged[k] = existing[k]
                new_entry = merged

        if info.is_leaf:
            leaves.append(new_entry)
        else:
            top_level.append(new_entry)

    # Carry forward any existing entries the analysis didn't discover.
    # These are hand-curated extras (e.g., vendor-doc fields).
    #
    # Filter root-extractor artifacts: that extractor wrongly captures
    # XIF `alter` locals (`get_ip`, `get_outcome`, …) AND regex
    # character-class fragments (`S`, `s`, `uccess` from `[s|S]uccess`) as
    # if they were schema fields. These artifacts can persist in the YAML
    # and the carry-forward path would preserve them silently. We drop any extras name that is NOT in
    # schema_columns AND NOT a dotted-path leaf AND fails the curated-
    # description heuristic (`_looks_curated`). Vendor-doc fields
    # survive because their descriptions are vendor-faithful
    # (>30 chars, no stub prefixes) — they pass `_looks_curated`.
    extras: list = []
    schema_cols = schema_columns or set()
    locals_set = analysis.local_names or set()
    if preserve_curated:
        for name, entry in existing_by_name.items():
            if name in covered_names:
                continue
            # Drop unambiguous root-extractor artifacts:
            # single chars, ALL_CAPS constants, helper-prefix locals.
            # Real vendor fields (snake_case with lowercase parts like
            # `Acct_Input_Packets`, `c_ip_ipv4`, `account_group_id`)
            # survive this check.
            if _is_extractor_artifact(name, locals_set, schema_cols):
                continue
            extras.append(dict(entry))

    top_level.sort(key=lambda f: f['name'])
    leaves.sort(key=lambda f: f['name'])
    extras.sort(key=lambda f: f['name'])

    # Order: top-level wire fields → dotted-path leaves → carried-over
    # extras (preserves the maintainer's prior structure).
    drafted['fields'] = top_level + leaves + extras
    return drafted


# ─── Main ───────────────────────────────────────────────────────────

def process_one_pack(pack_id: str, dry_run: bool, report: ParserReport,
                     preserve_curated: bool = True) -> Optional[Path]:
    """Process one pack. Returns the YAML path if drafted, else None."""
    pack_dir = DATA_SOURCES_DIR / pack_id
    yaml_path = pack_dir / 'data_source.yaml'
    if not yaml_path.exists():
        report.failures.append((pack_id, 'no data_source.yaml'))
        return None

    try:
        current = yaml.safe_load(yaml_path.read_text())
    except yaml.YAMLError as e:
        report.failures.append((pack_id, f'yaml parse: {e}'))
        return None

    try:
        analysis, schema_columns, schema_meta = analyze_pack(pack_id)
    except Exception as e:
        report.failures.append((pack_id, f'analyze: {e}'))
        return None

    has_xif = load_xif(pack_id) is not None
    if has_xif:
        report.packs_with_xif += 1
    else:
        report.packs_without_xif += 1

    has_composite = any(f.is_composite for f in analysis.fields.values())
    if has_composite:
        report.packs_with_composites += 1
    else:
        report.packs_pure_scalar += 1

    leaves_count = sum(1 for f in analysis.fields.values() if f.is_leaf)
    report.leaves_drafted += leaves_count

    # Skip packs that are already fully curated — no need to cosmetically
    # reformat a pristine YAML.
    if preserve_curated and _is_fully_curated(current, analysis):
        report.packs_skipped_curated += 1
        return None

    drafted = draft_pack_yaml(pack_id, current, analysis, schema_meta,
                              schema_columns=schema_columns,
                              preserve_curated=preserve_curated)

    if dry_run:
        return yaml_path

    yaml_path.write_text(yaml.safe_dump(drafted, sort_keys=False, default_flow_style=False))
    return yaml_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', help='Process a single pack id')
    parser.add_argument('--dry-run', action='store_true', help='No writes; just analyze')
    parser.add_argument('--report-only', action='store_true', help='Print parser stats only')
    parser.add_argument('--no-preserve', action='store_true',
                        help='Overwrite hand-curated descriptions with stubs')
    args = parser.parse_args()
    preserve_curated = not args.no_preserve

    report = ParserReport()

    if args.pack:
        pack_ids = [args.pack]
    else:
        pack_ids = sorted(
            d.name for d in DATA_SOURCES_DIR.iterdir()
            if d.is_dir() and (d / 'data_source.yaml').exists()
        )

    for pack_id in pack_ids:
        process_one_pack(pack_id, args.dry_run or args.report_only, report,
                         preserve_curated=preserve_curated)
        report.packs_processed += 1

    print(f"Packs processed: {report.packs_processed}")
    print(f"  with xif: {report.packs_with_xif}")
    print(f"  without xif: {report.packs_without_xif}")
    print(f"  composite shapes: {report.packs_with_composites}")
    print(f"  pure scalar: {report.packs_pure_scalar}")
    print(f"  skipped (already curated): {report.packs_skipped_curated}")
    print(f"  total leaves drafted: {report.leaves_drafted}")
    if report.failures:
        print(f"\nFailures ({len(report.failures)}):")
        for pid, reason in report.failures[:20]:
            print(f"  - {pid}: {reason}")
        if len(report.failures) > 20:
            print(f"  ... +{len(report.failures) - 20} more")


if __name__ == '__main__':
    sys.exit(main())
