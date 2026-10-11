#!/usr/bin/env python3
"""Retype data-source fields whose `example` has a clear shape but whose
declared `type` is generic.

WHY THIS MATTERS. The generator resolves a value in this order:
observables_dict -> is_gate+example -> TYPE -> name heuristic -> random.
For a non-gate field the `example` is INERT — only the type steers generation.
So a field declared `type: string` with example "192.0.2.45" emits a random
token like 'TGkDtZFp', which no modeling rule can parse into xdm.source.ipv4.
On a lab tenant, FortiGate events shipped with xdm.source.ipv4 100% null
for exactly this reason.

Conservative by design: only rewrites when the example matches one shape
unambiguously, and never touches a field that already has a specific type.
"""
import re, sys, yaml, pathlib, collections

GENERIC = {"string", "string_short", "string_long"}
ROOT = pathlib.Path("/home/user/Documents/Projects/Phantom/bundles/spark/data-sources")

# ORDER MATTERS: mac before ipv6, or 00:50:56:aa:bb:02 is read as an address.
SHAPES = [
    ("mac",         re.compile(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$')),
    ("ipv4",        re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')),
    ("email",       re.compile(r'^[^@\s]+@[^@\s]+\.[a-z]{2,}$', re.I)),
    ("url",         re.compile(r'^https?://\S+$', re.I)),
    ("hash_sha256", re.compile(r'^[a-f0-9]{64}$', re.I)),
    ("hash_sha1",   re.compile(r'^[a-f0-9]{40}$', re.I)),
    ("hash_md5",    re.compile(r'^[a-f0-9]{32}$', re.I)),
    # Requires "::" or >=4 colons. A looser pattern read the clock time
    # "14:23:01" as an address (extrahop_revealx.create_time).
    ("ipv6",        re.compile(r'^(?=.*::|(?:[^:]*:){4})[0-9a-fA-F:]{2,39}$')),
    ("_int",        re.compile(r'^\d{1,6}$')),
]
PORT  = re.compile(r'(^|_)(port|spt|dpt|sport|dport)($|_)', re.I)
BYTES = re.compile(r'(byte|size|length|len)', re.I)
# A numeric example on a field NAMED url/email/host/time is a contradiction in
# the source data, not a typing bug — leave it alone rather than guess wrong.
# (abnormal_security.abxPortalUrl declares example "443".)
NOT_NUMERIC = re.compile(r'(url|uri|email|mail|host|domain|time|date|name|path)', re.I)


def wanted(field):
    ex = field.get("example")
    if ex is None:
        return None
    ex = str(ex).strip()
    if not ex:
        return None
    for name, rx in SHAPES:
        if not rx.match(ex):
            continue
        if name != "_int":
            return name
        # A numeric example is only useful if we can say WHICH numeric type.
        n = field.get("name", "")
        if NOT_NUMERIC.search(n):
            return None
        if PORT.search(n):
            return "integer_port"
        if BYTES.search(n):
            return "integer_byte_count"
        return "integer"
    return None


def main():
    apply = "--apply" in sys.argv
    changes = collections.Counter()
    touched = collections.Counter()
    samples = {}
    for d in sorted(ROOT.iterdir()):
        y = d / "data_source.yaml"
        if not y.is_file():
            continue
        text = y.read_text()
        doc = yaml.safe_load(text)
        edits = []
        for f in (doc.get("fields") or []):
            if f.get("type") not in GENERIC:
                continue
            w = wanted(f)
            if not w:
                continue
            edits.append((f["name"], f["type"], w))
            samples.setdefault(w, (d.name.split("__")[-1], f["name"], f.get("example")))
        if not edits:
            continue
        touched[d.name] = len(edits)
        for _, _, w in edits:
            changes[w] += 1
        if apply:
            lines = text.splitlines(keepends=True)
            for fname, old, new in edits:
                # find `- name: <fname>` then the `  type:` line inside that block
                i = next((k for k, l in enumerate(lines)
                          if l.rstrip() == f"- name: {fname}"), None)
                if i is None:
                    continue
                end = next((k for k in range(i + 1, len(lines))
                            if lines[k].startswith("- ")), len(lines))
                t = next((k for k in range(i + 1, end)
                          if re.match(r"^  type:\s", lines[k])), None)
                if t is not None:
                    lines[t] = f"  type: {new}\n"
            y.write_text("".join(lines))

    print(f"{'APPLIED' if apply else 'DRY RUN'} — {sum(changes.values())} fields "
          f"across {len(touched)} sources")
    for k, v in changes.most_common():
        s = samples[k]
        print(f"   -> {k:20s} {v:>4}   e.g. {s[0]}.{s[1]} example={s[2]!r}")


if __name__ == "__main__":
    main()
