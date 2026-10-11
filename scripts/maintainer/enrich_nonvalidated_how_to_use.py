#!/usr/bin/env python3
"""Reverse-engineer fields + how_to_use for non-validated data sources from their
parsing/modeling rules — purely static, NO XSIAM traffic.

For each source in scripts/maintainer/enrich_queue.tsv (a batch slice via
--start/--count): read the rules_by_dataset manifest + modeling/parsing .xif and
(1) add any missing JSON-composite dotted-leaf fields the modeling rule reads,
and (2) author a how_to_use covering routing (CEF header -> dataset), ingestion
shape (flat vs JSON-native), the modeling-rule gate, the XDM field inventory, the
category-specific operator setup, and a verify query. Does NOT set validated:true.

ROUTING is anchored on the DATASET NAME, not the pack display name: the broker
derives `norm(vendor)_norm(product)_raw`, and for renamed/acquired vendors the
pack's display name (e.g. Cisco/CiscoStealthwatch) does NOT derive the dataset
(lancope_stealthwatch_raw). We assert the pack vendor/product only when norm()
matches the dataset; otherwise we flag the divergence (the SentinelOne trap).

Usage:
    python3 scripts/maintainer/enrich_nonvalidated_how_to_use.py --start 0 --count 5 [--apply]
"""
from __future__ import annotations
import argparse, json, os, re, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DS = ROOT / "bundles" / "spark" / "data-sources"
RBD = ROOT / "scripts" / "maintainer" / "rules_by_dataset"
QUEUE = ROOT / "scripts" / "maintainer" / "enrich_queue.tsv"


def norm(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def collapse(s):
    # The broker keeps trailing punctuation as `_` and does not collapse runs the way
    # norm() does ("Imperva Inc." -> "imperva_inc_" -> "imperva_inc__securesphere"),
    # so compare normalized names with _-runs collapsed to avoid a single-vs-double-_
    # difference reading as a wrong routing literal.
    return re.sub(r"_+", "_", s or "")


def find_rule_dir(dataset):
    # Case-INSENSITIVE match: organize_rules_by_dataset.py sometimes stores a
    # dataset dir with different case than the YAML's dataset_name (e.g.
    # Cisco_SMA_raw, juniper_SRX_raw). A `dataset in os.listdir()` exact match
    # silently misses these on a case-sensitive FS (and an earlier queue-build
    # did exactly that, dropping juniper/vmware/Cisco-SMA from the run).
    dl = dataset.lower()
    for cat in os.listdir(RBD):
        catp = RBD / cat
        if not catp.is_dir():
            continue
        for d in os.listdir(catp):
            if d.lower() == dl:
                return catp / d, cat
    return None, None


def load_rules(rule_dir):
    mr = ""
    for f in sorted(rule_dir.glob("modeling*.xif")):
        mr += f.read_text(errors="ignore") + "\n"
    p = rule_dir / "parsing.xif"
    pr = p.read_text(errors="ignore") if p.is_file() else ""
    return mr, pr


def parse_ingest(pr):
    m = re.search(r'\[INGEST:[^\]]*vendor\s*=\s*"([^"]+)"[^\]]*product\s*=\s*"([^"]+)"', pr)
    return (m.group(1), m.group(2)) if m else (None, None)


def analyze_mr(mr):
    xdm = sorted(set(re.findall(r"(?:xdm|XDM)\.[A-Za-z0-9_.]+", mr)))
    endpoint = any(f.startswith("XDM.Endpoint") for f in xdm)
    json_native = ("json_extract_scalar" in mr) or (" -> " in mr)
    gates = []
    for ln in re.findall(r"^\s*\|?\s*filter\s+(.+)$", mr, re.M):
        ln = ln.strip().rstrip(";")
        if ln and ln not in gates:
            gates.append(ln)
    jm = re.search(r'json_extract_scalar\([^,]+,\s*"(\$[^"]+)"', mr) or re.search(r"(\w+\s*->\s*\w[\w.]*)", mr)
    sample_access = jm.group(1) if jm else None
    return xdm, endpoint, json_native, gates, sample_access


def summarize_gate(gates):
    if not gates:
        return None
    for g in gates:
        if re.search(r"\b(in|=|contains|~=)\b", g):
            return g[:160]
    return gates[0][:160]


# ── composite-leaf field reconciliation ──────────────────────────
_NUM_LEAF = re.compile(r'to_(?:number|integer)\(\s*json_extract_scalar\(\s*([A-Za-z_]\w*)\s*,\s*"\$\.([^"]+)"')
_STR_LEAF = re.compile(r'json_extract_(?:scalar|array)\(\s*([A-Za-z_]\w*)\s*,\s*"\$\.([^"]+)"')
_ARROW_LEAF = re.compile(r"\b([A-Za-z_]\w*)\s*->\s*([A-Za-z_][\w.]*)")


def extract_leaves(mr):
    out: dict[str, dict] = {}
    for col, path in _NUM_LEAF.findall(mr):
        out.setdefault(col, {})[path] = "number"
    for col, path in _STR_LEAF.findall(mr):
        out.setdefault(col, {}).setdefault(path, "string_short")
    for col, path in _ARROW_LEAF.findall(mr):
        out.setdefault(col, {}).setdefault(path, "string_short")
    return out


def insert_leaves(txt, mr, field_names):
    leaves = extract_leaves(mr)
    composites = {n for n in field_names if "." not in n}
    blocks, added = [], []
    for col, paths in sorted(leaves.items()):
        if col not in composites:
            continue
        for leaf, typ in sorted(paths.items()):
            fname = f"{col}.{leaf}"
            if fname in field_names:
                continue
            ex = "42" if typ == "number" else "sample value"
            blocks.append(f"- name: {fname}\n  type: {typ}\n  "
                          f"description: Nested leaf of `{col}` — the modeling rule reads it at $.{leaf}.\n"
                          f"  example: {ex}\n")
            added.append(fname)
    if not blocks:
        return txt, []
    m = re.search(r"^fields:\s*?\n", txt, re.M)
    if not m:
        return txt, []
    ins = m.end()
    return txt[:ins] + "".join(blocks) + txt[ins:], added


def build_block(vendor, product, dataset, xdm, endpoint, json_native, gates,
                sample_access, manifest, match, expected, stem, broad_ingest=False):
    prefix = "XDM.Endpoint." if endpoint else "xdm."
    n = len(xdm)
    samples = ", ".join(f"`{f}`" for f in xdm[:6] if not f.endswith(".provider")) or f"`{prefix}*`"
    preset = "the **Endpoint** data model (`XDM.Endpoint.*`)" if endpoint else "the unified data model (`xdm.*`)"
    gate = summarize_gate(gates)
    gate_line = (f"- **Modeling-rule gate**: `{gate}` — seed that field with an accepted value or the rule drops the row (XDM stays 0)."
                 if gate else "- **Modeling-rule gate**: none — the rule maps every routed row unconditionally.")
    if json_native:
        shape = ("**JSON-native.** The modeling rule reads nested JSON"
                 + (f" (e.g. `{sample_access}`)" if sample_access else "")
                 + ". CEF/syslog routes + lands and the broker extracts top-level columns; the nested reads "
                   "need the composite present, so Phantom's worker JSON-stringifies `type: json` composites "
                   "onto the wire (keep the dotted-leaf fields).")
    else:
        shape = ("**Flat / CEF-compatible.** The modeling rule reads flat top-level columns (no nested-JSON "
                 "access). A CEF event routes in and the broker auto-extracts those columns, so this source "
                 "maps from Phantom's existing CEF path once the dataset is XDM-bound.")
    setup = (manifest.get("operator_setup_notes")
             or "Onboard the vendor content pack so the dataset is XDM-enabled (the marketplace modeling "
                "rule binds to it); broker-auto-created datasets stay raw-only.").strip()
    if match:
        routing = (f"**Required CEF header for XSIAM**:\n"
                   f"  - **vendor**: `{vendor}`\n"
                   f"  - **product**: `{product}`\n\n"
                   f"  These normalize → `{dataset}`.")
    elif broad_ingest:
        routing = (f"**Not a simple CEF vendor/product route.** The parsing rule ingests under the broad "
                   f"identity `{vendor}`/`{product}` (which normalizes to `{expected}_raw`, a parent "
                   f"dataset) and splits events into per-channel datasets — `{dataset}` is one of them — by "
                   f"event channel/category downstream. A single CEF `deviceVendor`/`deviceProduct` header "
                   f"does NOT by itself land events in `{dataset}`. Ingest the source via its native path "
                   f"(Windows agent / WEC, or Azure diagnostic settings) so the rule routes the specific "
                   f"channel to `{dataset}`.")
    else:
        routing = (f"**Required CEF header for XSIAM** — the header must normalize to `{stem}`. "
                   f"The marketplace pack's display name `{vendor}` / `{product}` normalizes to "
                   f"`{expected}_raw`, a **different dataset** (vendor rename / legacy CEF identity), so use the "
                   f"vendor's actual CEF `deviceVendor`/`deviceProduct` that yields `{stem}` and confirm which "
                   f"dataset the events land in.")
    return f"""## {vendor} {product.replace('_', ' ')} → Cortex XSIAM (dataset `{dataset}`)

  **Routing** — the broker lowercases the CEF/syslog header `vendor`/`product`, replaces
  non-alphanumerics with `_`, and appends `_raw` to choose the dataset (target: `{dataset}`).

  {routing}

  **Ingestion shape**: {shape}

  {gate_line}

  **XDM mapping**: ~{n} fields mapped to {preset}, including: {samples}.

  **Operator setup**: {setup}

  **Status**: Routing, gate and field inventory are derived from the parsing/modeling rules. **Not yet XDM-validated** (no `validated` pill); validate by
  streaming a CEF batch and confirming a rich `{prefix}*` count over a wide window.

  **Verify** (once the dataset is XDM-bound, wide ≥7d window):

      config timeframe = 30d | datamodel dataset = {dataset} | sort desc _time | fields {prefix}* | limit 20
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true", help="rebuild how_to_use even if present")
    ap.add_argument("--only", help="comma-separated slugs to regenerate, bypassing the queue slice")
    args = ap.parse_args()

    if args.only:
        # synthesize queue rows for the named slugs (dataset = the slug's final segment)
        batch = [["--", "--", "--", s, s.rsplit("__", 1)[-1]] for s in args.only.split(",")]
    else:
        rows = [l.split("\t") for l in QUEUE.read_text().splitlines()[1:]]
        batch = rows[args.start:args.start + args.count]
    applied, skipped, mismatches = [], [], []
    for idx, status, cat, slug, dataset in batch:
        yf = DS / slug / "data_source.yaml"
        if not yf.is_file():
            skipped.append((slug, "yaml missing")); continue
        txt = yf.read_text()
        has_htu = bool(re.search(r"^how_to_use:", txt, re.M))
        rule_dir, rcat = find_rule_dir(dataset)
        if not rule_dir:
            skipped.append((slug, "no rule dir")); continue
        manifest = {}
        mf = rule_dir / "manifest.json"
        if mf.is_file():
            manifest = json.loads(mf.read_text())
        mr, pr = load_rules(rule_dir)
        vendor = manifest.get("vendor") or slug.split("__")[0]
        product = manifest.get("product") or slug.split("__")[1]
        iv, ip = parse_ingest(pr)
        if iv and ip:
            vendor, product = iv, ip
        stem = dataset[:-4] if dataset.endswith("_raw") else dataset
        expected = f"{norm(vendor)}_{norm(product)}"
        # match ONLY when the routing literal actually normalizes to the dataset — a
        # broad [INGEST:] identity (e.g. Microsoft/Windows split by channel) that does
        # not normalize to the sub-dataset must NOT be asserted as the routing literal.
        match = (collapse(expected) == collapse(stem))
        broad_ingest = bool(iv and ip) and not match
        if not match:
            mismatches.append((slug, f"{vendor}/{product}->{expected}_raw != {dataset}"
                                     + (" [broad-ingest]" if broad_ingest else "")))
        xdm, endpoint, jn, gates, sa = analyze_mr(mr)
        field_names = set(re.findall(r"^\s*-\s*name:\s*(\S+)", txt, re.M))
        txt, leaves_added = insert_leaves(txt, mr, field_names)
        print(f"[{idx}] {slug}  routing={vendor}/{product} match={match} "
              f"shape={'JSON' if jn else 'flat'} xdm={len(xdm)} gate={summarize_gate(gates)} "
              f"leaves+={len(leaves_added)} htu={'present' if has_htu else 'NEW'}")
        if not txt.endswith("\n"):
            txt += "\n"
        write_htu = (not has_htu) or args.force
        if write_htu:
            if has_htu and args.force:
                txt = re.sub(r"\nhow_to_use: \|\n(?:  .*\n?|\n)*\Z", "\n", txt)
            block = build_block(vendor, product, dataset, xdm, endpoint, jn, gates, sa, manifest, match, expected, stem, broad_ingest)
            txt += "how_to_use: |\n  " + block.replace("\n", "\n  ").rstrip() + "\n"
        changed = bool(leaves_added) or write_htu
        if args.apply and changed:
            yf.write_text(txt)
            applied.append(slug)
        elif not changed:
            skipped.append((slug, "already complete"))
    print(f"\n{'APPLIED' if args.apply else 'PREVIEW'}: {len(applied)} written, {len(skipped)} skipped, "
          f"{len(mismatches)} routing-mismatch (flagged in block)")
    for s, m in mismatches:
        print(f"  MISMATCH {s}: {m}")


if __name__ == "__main__":
    main()
