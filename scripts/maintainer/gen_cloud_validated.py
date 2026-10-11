#!/usr/bin/env python3
"""Promote a cloud source to validated after live XDM verification.

For each source in VALIDATED: strip the prior 'blocked/prerequisites' how_to_use
(everything from the `how_to_use:` line to EOF — the generator appended it there),
set `validated: true`, write a validated how_to_use (routing + gate + JSON-composite
note + verify query), and add the dataset to the manifest. Idempotent-ish: re-running
rewrites the trailing how_to_use cleanly.

Populate VALIDATED with the live-verified field counts, then run.
"""
from __future__ import annotations
import re, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DS = ROOT / "bundles" / "spark" / "data-sources"
MANIFEST = ROOT / "tooling" / "validate" / "validated_data_sources.txt"

# dir : dict(dataset, vendor, product, pack, count, gate, json_native, ns)
VALIDATED = {
 "GoogleCloudSCC__GoogleCloudSCC__google_scc_raw":
   dict(dataset="google_scc_raw", vendor="Google", product="SCC", pack="Google Cloud SCC",
        count=21, gate=None, json_native=True, ns="xdm."),
 "GoogleDrive__GoogleDrive__google_workspace_drive_raw":
   dict(dataset="google_workspace_drive_raw", vendor="Google", product="Workspace_Drive", pack="Google Workspace / Drive",
        count=22, gate=None, json_native=True, ns="xdm."),
 "GoogleApigee__GoogleApigee__google_apigee_raw":
   dict(dataset="google_apigee_raw", vendor="Google", product="Apigee", pack="Google Apigee",
        count=10, gate=None, json_native=True, ns="xdm."),
 "AzureFirewall__AzureFirewall__msft_azure_firewall_raw":
   dict(dataset="msft_azure_firewall_raw", vendor="msft", product="Azure_Firewall", pack="Azure Firewall",
        count=20, gate='category in ("AZFWApplicationRule", "AZFWNetworkRule", "AZFWDnsQuery", ...)', json_native=True, ns="xdm."),
 "GoogleCloudLogging__GoogleCloudLogging__google_cloud_logging_raw":
   dict(dataset="google_cloud_logging_raw", vendor="Google", product="Cloud_Logging", pack="Google Cloud Logging",
        count=52, gate='logName (computed) — seed a realistic GCP log path, e.g. projects/P/logs/cloudaudit.googleapis.com%2Factivity', json_native=True, ns="xdm."),
 "GoogleCloudLogging__GoogleCloudLogging__google_dns_raw":
   dict(dataset="google_dns_raw", vendor="Google", product="DNS", pack="Google Cloud Logging (DNS subset)",
        count=30, gate='logName (computed) — seed a realistic GCP log path, e.g. projects/P/logs/dns.googleapis.com%2Fdns_queries', json_native=True, ns="xdm."),
 # GuardDuty added after the Endpoint-preset count lands (ns="xdm.endpoint.")
}

def how_to_use(v):
    gate_line = (f"\n  Modeling-rule gate: seed `{v['gate']}` (the AZFWApplicationRule branch is verified)."
                 if v["gate"] else "\n  Modeling rule: unconditional (no gate field).")
    json_note = ("\n  JSON-native MR: it reads nested JSON via `json_extract_scalar(...)`/`->`. The\n"
                 "  worker emits composite schema fields as JSON strings on the CEF wire, which the\n"
                 "  rule parses — so CEF-over-syslog populates these fields (no HTTP collector).\n"
                 if v["json_native"] else "\n")
    return (
f"""how_to_use: |
  ## {v['vendor']} {v['product'].replace('_',' ')} → Cortex XSIAM (dataset `{v['dataset']}`)

  **Validated** — maps **{v['count']} {v['ns'].rstrip('.')} fields** end-to-end
  via CEF-over-syslog on a tenant with the **{v['pack']}** content pack installed
  (the pack binds the modeling rule + parsing rule to the dataset).

  Required CEF header — the broker derives the dataset from it (lowercased):
  - vendor: `{v['vendor']}`
  - product: `{v['product']}`
  Broker derives -> `{v['dataset']}`.{gate_line}
{json_note}
  Verify (wide >=7d window):
      config timeframe = 30d | datamodel dataset = {v['dataset']} | sort desc _time | fields {v['ns']}* | limit 20
""")

def main():
    manifest_lines = MANIFEST.read_text().splitlines()
    manifest_set = {l.strip() for l in manifest_lines if l.strip() and not l.lstrip().startswith("#")}
    added = []
    for d, v in VALIDATED.items():
        yf = DS / d / "data_source.yaml"
        if not yf.is_file():
            print(f"  MISSING {d}"); continue
        txt = yf.read_text()
        # strip prior trailing how_to_use block (generator appended at EOF)
        txt = re.sub(r"\nhow_to_use:.*\Z", "\n", txt, flags=re.S)
        # ensure validated: true (idempotent)
        if re.search(r"^validated:", txt, re.M):
            txt = re.sub(r"^validated:.*$", "validated: true", txt, flags=re.M)
        else:
            if not txt.endswith("\n"): txt += "\n"
            txt += "validated: true\n"
        if not txt.endswith("\n"): txt += "\n"
        txt += how_to_use(v)
        yf.write_text(txt)
        if d not in manifest_set:
            added.append(d)
        print(f"  validated {v['dataset']:30s} {v['count']} {v['ns'].rstrip('.')} fields")
    if added:
        with MANIFEST.open("a") as f:
            for d in added:
                f.write(d + "\n")
        print(f"  + {len(added)} added to manifest")
    print(f"\n{len(VALIDATED)} sources promoted; manifest now {len(manifest_set)+len(added)}")

if __name__ == "__main__":
    main()
