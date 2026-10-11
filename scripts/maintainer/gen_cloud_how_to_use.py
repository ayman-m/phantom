#!/usr/bin/env python3
"""Generate reverse-engineered how_to_use blocks for the cloud-provider sources.

The cloud-provider modeling rules (GCP/AWS/Azure) are JSON-native: they read
nested JSON via `->` / `json_extract_scalar(...)`, and several target the
Endpoint preset (`XDM.Endpoint.*`) rather than unified `xdm.*`. Flat CEF over
syslog routes + lands + column-extracts, but cannot populate nested-JSON field
reads, and broker-auto-created datasets don't bind their marketplace MR anyway.

So these sources are documented (routing literal + gate + XDM field inventory +
the two tenant-side prerequisites), NOT marked validated — the same treatment as Netskope. Idempotent: skips a YAML that already has how_to_use.
"""
from __future__ import annotations
import re, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DS = ROOT / "bundles" / "spark" / "data-sources"
XIFD = ROOT / "scripts" / "maintainer" / "modeling_rules"

# (dir, dataset, vendor-literal, product-literal, xif-basename-candidates)
TEN = [
 ("GoogleCloudLogging__GoogleCloudLogging__google_cloud_logging_raw","google_cloud_logging_raw","Google","Cloud_Logging",["GoogleCloudLogging__GoogleCloudLogging"]),
 ("GoogleCloudSCC__GoogleCloudSCC__google_scc_raw","google_scc_raw","Google","SCC",["GoogleCloudSCC__GoogleCloudSCC"]),
 ("GoogleCloudLogging__GoogleCloudLogging__google_dns_raw","google_dns_raw","Google","DNS",["GoogleCloudLogging__GoogleCloudLogging"]),
 ("GoogleApigee__GoogleApigee__google_apigee_raw","google_apigee_raw","Google","Apigee",["GoogleApigee__GoogleApigee"]),
 ("GoogleDrive__GoogleDrive__google_workspace_drive_raw","google_workspace_drive_raw","Google","Workspace_Drive",["GoogleDrive__GoogleDrive_1_3","GoogleDrive__GoogleDrive"]),
 ("GoogleChrome__GoogleChrome__google_workspace_chrome_raw","google_workspace_chrome_raw","Google","Workspace_Chrome",["GoogleChrome__GoogleChrome"]),
 ("AWS-GuardDuty__AWSGuardDutyModelingRules__aws_guardduty_raw","aws_guardduty_raw","AWS","GuardDuty",["AWS-GuardDuty__AWSGuardDutyModelingRules"]),
 ("AWS_ELB__AWS_ELB__aws_elb_raw","aws_elb_raw","AWS","ELB",["AWS_ELB__AWS_ELB"]),
 ("AzureSecurityCenter__MicrosoftDefenderForCloudModelingRules__microsoft_defender_for_cloud_raw","microsoft_defender_for_cloud_raw","Microsoft","Defender_for_Cloud",["AzureSecurityCenter__MicrosoftDefenderForCloudModelingRules"]),
 ("AzureFirewall__AzureFirewall__msft_azure_firewall_raw","msft_azure_firewall_raw","msft","Azure_Firewall",["AzureFirewall__AzureFirewall"]),
]

def load_xif(cands):
    for c in cands:
        p = XIFD / f"{c}.xif"
        if p.is_file():
            return p.read_text()
    return ""

def analyze_xif(text, dataset):
    fields = sorted(set(re.findall(r"(?:xdm|XDM)\.[A-Za-z0-9_.]+", text)))
    endpoint = any(f.startswith("XDM.Endpoint") for f in fields)
    preset = "Endpoint preset (`XDM.Endpoint.*`)" if endpoint else "unified XDM (`xdm.*`)"
    json_native = ("json_extract_scalar" in text) or (" -> " in text)
    # a representative nested-JSON access for the prose
    m = re.search(r"(json_extract_scalar\([^,]+,\s*\"\$[^\"]+\")", text) or re.search(r"(\w+\s*->\s*\w[\w.]*)", text)
    sample_access = m.group(1) if m else "nested JSON fields"
    # gate: first filter line, if any
    fm = re.search(r"^\s*filter\s+(.+)$", text, re.M)
    gate = fm.group(1).strip()[:120] if fm else None
    sample_fields = [f for f in fields if not f.endswith(".provider")][:8]
    return fields, preset, json_native, sample_access, gate, sample_fields

def block(vendor, product, dataset, preset, json_native, sample_access, gate, n_fields, sample_fields):
    xdm_prefix = "XDM.Endpoint." if "Endpoint" in preset else "xdm."
    gate_line = (f"\n  Modeling-rule gate: `{gate}` — seed that field accordingly."
                 if gate else "\n  Modeling rule: unconditional (no gate field).")
    samples = ", ".join(sample_fields[:6]) if sample_fields else f"{xdm_prefix}*"
    if json_native:
        shape = (f"Ingestion shape: **JSON-native.** This modeling rule reads **nested JSON**\n"
                 f"  (e.g. `{sample_access}`) and maps to the {preset}. {vendor}'s native path is\n"
                 f"  its HTTP/API collector emitting JSON, not flat CEF. A synthetic flat-CEF\n"
                 f"  event routes in and the broker extracts top-level columns, but the MR's\n"
                 f"  nested-JSON reads resolve to null — so XDM does not populate from CEF.")
        prereqs = (f"To populate XDM, **two** tenant-side prerequisites (neither is a Phantom change\n"
                   f"  — same class as the Netskope marketplace-MR finding):\n"
                   f"  1. Onboard the {vendor} content pack so `{dataset}` is XDM-enabled — the\n"
                   f"     marketplace modeling rule binds to the dataset. Broker-auto-created\n"
                   f"     datasets stay raw-only and the rule never applies (datamodel returns 0).\n"
                   f"  2. Ingest as JSON through an XSIAM HTTP Collector (dataset target + API key),\n"
                   f"     not the syslog broker — the nested-JSON MR needs JSON payloads. Phantom's\n"
                   f"     synthetic worker emits flat CEF/syslog today.")
    else:
        shape = (f"Ingestion shape: **flat / CEF-compatible.** This modeling rule reads flat\n"
                 f"  top-level columns (no nested-JSON access) and maps to the {preset}. A\n"
                 f"  synthetic flat-CEF event routes in and the broker extracts those columns,\n"
                 f"  so this source CAN map from Phantom's existing CEF path — the only missing\n"
                 f"  piece is the dataset binding.")
        prereqs = (f"To populate XDM, **one** tenant-side prerequisite (then the existing flat-CEF\n"
                   f"  stream suffices — same class as the Netskope marketplace-MR finding):\n"
                   f"  1. Onboard the {vendor} content pack so `{dataset}` is XDM-enabled — the\n"
                   f"     marketplace modeling rule binds to the dataset. Broker-auto-created\n"
                   f"     datasets stay raw-only and the rule never applies (datamodel returns 0).\n"
                   f"     Once bound, re-run the CEF simulate + verify over a wide window.")
    return f"""how_to_use: |
  ## {vendor} {product.replace('_',' ')} → Cortex XSIAM (dataset `{dataset}`)

  Routing — broker-derived from the CEF/syslog header (lowercased):
  - vendor: `{vendor}`
  - product: `{product}`
  Broker derives -> `{dataset}`.

  {shape}
  (Derived from the pack rules; routing/landing verified Phantom-side.
  NOT XDM-validated on a stock tenant — see prerequisite(s) below.)

  Maps to ~{n_fields} fields including: {samples}.{gate_line}

  {prereqs}

  Verify (once prerequisite(s) met, wide >=7d window):
      config timeframe = 30d | datamodel dataset = {dataset} | sort desc _time | fields {xdm_prefix}* | limit 20
"""

def main():
    done, skipped = [], []
    for d, dataset, vendor, product, cands in TEN:
        yf = DS / d / "data_source.yaml"
        if not yf.is_file():
            skipped.append((d, "yaml missing")); continue
        txt = yf.read_text()
        if re.search(r"^how_to_use:", txt, re.M):
            skipped.append((d, "how_to_use already present")); continue
        xif = load_xif(cands)
        if not xif:
            skipped.append((d, "xif missing")); continue
        fields, preset, jn, sa, gate, sample_fields = analyze_xif(xif, dataset)
        blk = block(vendor, product, dataset, preset, jn, sa, gate, len(fields), sample_fields)
        if not txt.endswith("\n"):
            txt += "\n"
        yf.write_text(txt + blk)
        done.append((dataset, len(fields), preset.split()[0], "JSON-native" if jn else "flat"))
    print("=== applied how_to_use ===")
    for ds, n, p, jn in done:
        print(f"  {ds:34s} {n:3d} fields  {p:9s} {jn}")
    if skipped:
        print("=== skipped ===")
        for d, why in skipped:
            print(f"  {d}: {why}")
    print(f"\n{len(done)} written, {len(skipped)} skipped")

if __name__ == "__main__":
    main()
