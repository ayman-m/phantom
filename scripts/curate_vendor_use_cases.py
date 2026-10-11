"""Curate operator-meaningful `use_cases:` per bundled vendor.

Maintainer-only research/build tool per `scripts/CLAUDE.md`. Runtime
never re-runs it.

## Why

Vendor cards on `/data-sources` would otherwise show category badges
derived from the Cortex XSIAM platform taxonomy (`Analytics & SIEM`,
`Endpoint`, `Network Security`, etc.). That taxonomy describes WHICH
XSIAM module the pack ships under, not WHAT THE VENDOR'S PRODUCT
ACTUALLY DOES.

Operator wants vendor-meaningful product-type labels:
  > "Avaya would be network related devices, Box would be storage,
  >  F5 would be WAF and Load Balancer, Okta would be Identity and
  >  MFA, CyberArk would be PAM."

This script encodes a curated map (137 vendors → 1-3 use_cases each)
into a NEW `use_cases:` field on each `data_source.yaml`. The catalog
row exposes the new field; the UI surfaces it as the badge text.

The old `categories:` field stays on the YAML but is no longer the
operator-visible source. Future maintainers can prune or repurpose
it.

## Taxonomy (canonical use_cases enum)

Short labels, one or two words max, grouped by domain. Vendors carry
the labels their products fit — not platform deployment categories.

  Network            — switches, routers, WLC, generic network gear
  Firewall           — NGFW, perimeter firewalls
  WAF                — web application firewalls
  LoadBalancer       — application delivery / load balancers
  SDWAN              — SD-WAN platforms
  VPN                — VPN concentrators / remote access
  Proxy              — forward proxies / SWG
  DNS                — DNS servers / DDI
  IDS                — IPS/IDS systems
  DDoS               — DDoS protection

  EDR                — endpoint detection + response
  AV                 — antivirus
  Endpoint           — broad endpoint telemetry (Sysmon, Auditd)
  Forensics          — endpoint forensics + IR

  Identity           — IAM, SSO, directory services
  MFA                — multi-factor authentication
  PAM                — privileged access management
  AD                 — Active Directory security
  CIAM               — customer IAM

  Email              — email security gateways + anti-spam
  DLP                — data loss prevention
  CASB               — cloud access security broker

  Cloud              — IaaS (AWS, Azure, GCP)
  SaaS               — SaaS app telemetry
  Container          — Kubernetes, K8s networking
  Virtualization     — hypervisors (ESXi, vCenter)
  CSPM               — cloud security posture mgmt

  Database           — DB audit + DB mgmt

  Storage            — file storage / cloud drives / backup
  Collab             — Slack, Teams, Zoom, file sharing
  DevOps             — GitHub, GitLab, Atlassian, CI/CD

  WebServer          — Apache, NGINX, IIS
  AppServer          — Tomcat, JBoss

  SIEM               — log aggregation platforms
  SOAR               — orchestration platforms
  XDR                — extended detection + response
  ThreatIntel        — threat intel platforms
  Vuln               — vulnerability mgmt
  ASM                — attack surface mgmt

  OS                 — operating system logs
  Honeypot           — deception / canary
  ICS                — industrial control systems
  PhysSec            — physical access control
  Voice              — VoIP / PBX / UC
  Analytics          — BI / data viz
  CTEM               — continuous threat exposure mgmt

  Other              — fallback when nothing else fits

## How to update

Edit the `CURATION` dict below. Re-run:

    python3 scripts/curate_vendor_use_cases.py

The script writes the `use_cases:` field into each matching YAML
(matched by the `vendor:` field after vendor rebucketing). YAMLs
not mentioned in `CURATION` get `use_cases: ["Other"]`. Re-running
is idempotent.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_SOURCES_DIR = REPO_ROOT / "bundles" / "spark" / "data-sources"

# ─── Canonical taxonomy ────────────────────────────────────────────────
#
# Every value in CURATION[vendor] MUST appear in this set. The script
# enforces. Keeps drift to a minimum.

CANONICAL_USE_CASES = {
    # Network
    "Network", "Firewall", "WAF", "LoadBalancer", "SDWAN", "VPN", "Proxy",
    "DNS", "IDS", "DDoS",
    # Endpoint
    "EDR", "AV", "Endpoint", "Forensics",
    # Identity
    "Identity", "MFA", "PAM", "AD", "CIAM",
    # Email & Data
    "Email", "DLP", "CASB",
    # Cloud
    "Cloud", "SaaS", "Container", "Virtualization", "CSPM",
    # Apps
    "Database", "Storage", "Collab", "DevOps", "WebServer", "AppServer",
    # Security ops
    "SIEM", "SOAR", "XDR", "ThreatIntel", "Vuln", "ASM", "CTEM",
    # Specialty
    "OS", "Honeypot", "ICS", "PhysSec", "Voice", "Analytics",
    # Fallback
    "Other",
}

# ─── Curation map ──────────────────────────────────────────────────────
#
# Vendor display name (matches the `vendor:` field in data_source.yaml
# AFTER vendor rebucketing) → list of use_cases (in priority order
# — first one appears most prominently on the vendor card).

CURATION: dict[str, list[str]] = {
    # Curated for the EXACT vendor strings that appear in the YAMLs
    # after vendor rebucketing. To find a vendor that hasn't been
    # curated yet, run the script and check the "Fell to 'Other'" list.
    #
    # First entry in each list is the most distinguishing label (shown
    # most prominently on the vendor card). Order matters.
    "1Password":               ["MFA", "Identity"],
    "Abnormal Security":       ["Email"],
    "Absolute Software":       ["Endpoint"],
    "Admin By Request":        ["PAM"],
    "Akamai":                  ["WAF", "DDoS"],
    "Alibaba":                 ["Cloud"],
    "Amazon":                  ["Cloud", "SaaS"],
    "Amazon Web Services":     ["Cloud"],
    "Apache":                  ["WebServer", "AppServer"],
    "Apple":                   ["OS", "Endpoint"],
    "Arista":                  ["Network"],
    "Armis":                   ["ASM", "Vuln"],
    "Atlassian":               ["DevOps", "Collab"],
    "Avaya":                   ["Voice"],
    "Barracuda":               ["Email", "WAF", "Firewall"],
    "BeyondTrust":             ["PAM"],
    "Bitbucket":               ["DevOps"],
    "Bitsight":                ["CTEM"],
    "Bitwarden":               ["Identity", "MFA"],
    "Bluecat":                 ["DNS"],
    "Box":                     ["Storage", "Collab"],
    "Brocade":                 ["Network"],
    "CYFIRMA DeCYFIR":         ["ThreatIntel"],
    "Carbon Black":            ["EDR"],
    "Celonis":                 ["Analytics"],
    "Check Point":             ["Firewall", "Network"],
    "Cisco":                   ["Network", "Firewall", "EDR"],
    "Citrix":                  ["LoadBalancer"],
    "Claroty":                 ["ICS"],
    "Clearswift":              ["DLP", "Email"],
    "Cloudflare":              ["WAF", "DDoS", "DNS"],
    "Code42":                  ["DLP"],
    "Cohesity":                ["Storage"],
    "Corelight":               ["IDS", "Network"],
    "CybelAngel":              ["ASM", "ThreatIntel"],
    "CyberArk":                ["PAM"],
    "Darktrace":               ["XDR"],
    "Delinea":                 ["PAM"],
    "Dell EMC":                ["Storage"],
    "Digital Guardian":        ["DLP"],
    "DocuSign":                ["SaaS"],
    "Dragos":                  ["ICS"],
    "Dropbox":                 ["Storage", "Collab"],
    "Druva":                   ["Storage"],
    "Duo Security":            ["MFA"],
    "Exabeam":                 ["SIEM"],
    "ExtraHop":                ["IDS", "XDR"],
    "F5":                      ["WAF", "LoadBalancer"],
    "FireEye":                 ["EDR", "Email"],
    "Forcepoint":              ["DLP", "Proxy"],
    "Forescout":               ["ASM"],
    "Fortinet":                ["Firewall", "Network", "WAF"],
    "Genesys":                 ["SaaS", "Voice"],
    "Genetec":                 ["PhysSec"],
    "GitGuardian":             ["DevOps"],
    "GitHub":                  ["DevOps"],
    "GitLab":                  ["DevOps"],
    "Google":                  ["Cloud", "SaaS"],
    "HPE":                     ["Network"],
    "HashiCorp":               ["DevOps"],
    "Hello World (Demo)":      ["Other"],
    "Huawei":                  ["Network"],
    "IBM":                     ["Database", "OS"],
    "Illusive Networks":       ["Honeypot"],
    "Imperva":                 ["WAF", "Database"],
    "Infoblox":                ["DNS"],
    "Ironscales":              ["Email"],
    "Ivanti":                  ["VPN", "Endpoint"],
    "Jamf":                    ["Endpoint"],
    "Juniper":                 ["Firewall", "Network"],
    "Keeper Security":         ["MFA", "Identity"],
    "Kiteworks":               ["Storage", "Collab"],
    "KnowBe4":                 ["Email"],
    "Kubernetes":              ["Container"],
    "LenelS2":                 ["PhysSec"],
    "Linux":                   ["OS"],
    "Lookout":                 ["Endpoint"],
    "ManageEngine":            ["Identity", "Endpoint"],
    "McAfee":                  ["AV", "EDR", "Email"],
    "Microsoft":               ["Cloud", "SaaS", "Identity"],
    "Mimecast":                ["Email"],
    "MongoDB":                 ["Database"],
    "MySQL":                   ["Database"],
    "NGINX":                   ["WebServer"],
    "NVIDIA":                  ["Endpoint"],
    "Nasuni":                  ["Storage"],
    "NetBox":                  ["Network"],
    "Netmotion":               ["VPN"],
    "Netskope":                ["CASB", "Proxy"],
    "Okta":                    ["Identity", "MFA"],
    "OneLogin":                ["Identity", "MFA"],
    "Oracle":                  ["Database"],
    "Orca Security":           ["CSPM", "Cloud"],
    "Palo Alto Networks":      ["Firewall", "XDR"],
    "Portnox":                 ["Identity"],
    "Proofpoint":              ["Email", "DLP"],
    "Qualys":                  ["Vuln"],
    "RSA":                     ["MFA"],
    "Radware":                 ["WAF", "DDoS"],
    "Reblaze":                 ["WAF"],
    "Recorded Future":         ["ThreatIntel"],
    "ReliaQuest":              ["SIEM"],
    "Retarus":                 ["Email"],
    "SailPoint":               ["Identity"],
    "Salesforce":              ["SaaS"],
    "Saviynt":                 ["Identity"],
    "SecureAuth":              ["Identity", "MFA"],
    "Semperis":                ["AD", "Identity"],
    "ServiceNow":              ["SaaS"],
    "Shodan":                  ["ASM", "ThreatIntel"],
    "Siemens":                 ["PhysSec", "ICS"],
    "Silverfort":              ["MFA", "Identity"],
    "Slack":                   ["Collab"],
    "SonicWall":               ["Firewall"],
    "SpecterOps BloodHound":   ["AD"],
    "Squid":                   ["Proxy"],
    "Symantec":                ["AV", "EDR", "Email", "DLP", "CASB"],
    "Synopsys":                ["DevOps", "Vuln"],
    "Tableau":                 ["Analytics"],
    "Tanium":                  ["EDR", "Endpoint"],
    "TeamViewer":              ["Collab"],
    "Tenable":                 ["Vuln"],
    "Thales":                  ["MFA"],
    "Thinkst":                 ["Honeypot"],
    "Tigera":                  ["Container"],
    "Trend Micro":             ["AV", "EDR"],
    "Ubiquiti":                ["Network"],
    "VMware":                  ["Virtualization", "Container"],
    "Vectra AI":               ["XDR"],
    "WatchGuard":              ["Firewall"],
    "WithSecure":              ["EDR", "AV"],
    "Workday":                 ["Identity"],
    "Zero Networks":           ["Network", "Identity"],
    "Zoom":                    ["Collab"],
    "Zscaler":                 ["Proxy", "CASB"],
    "monday.com":              ["SaaS", "Collab"],
    "runZero":                 ["ASM"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Sanity-check the curation map against the canonical taxonomy.
    bad: list[tuple[str, str]] = []
    for vendor, uc_list in CURATION.items():
        for uc in uc_list:
            if uc not in CANONICAL_USE_CASES:
                bad.append((vendor, uc))
    if bad:
        print("ERROR: curation map has use_cases not in CANONICAL_USE_CASES:", file=sys.stderr)
        for v, u in bad:
            print(f"  {v!r} → {u!r}", file=sys.stderr)
        return 1

    if not DATA_SOURCES_DIR.is_dir():
        print(f"ERROR: {DATA_SOURCES_DIR} not found", file=sys.stderr)
        return 1

    # vendor counts seen in the actual YAMLs
    vendor_seen: dict[str, int] = {}
    updated_count = 0
    skipped_unchanged = 0
    fallback_other: list[str] = []

    for d in sorted(DATA_SOURCES_DIR.iterdir()):
        if not d.is_dir():
            continue
        yaml_path = d / "data_source.yaml"
        if not yaml_path.is_file():
            continue
        try:
            doc = yaml.safe_load(yaml_path.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue

        vendor = doc.get("vendor")
        if not vendor:
            continue
        vendor_seen[vendor] = vendor_seen.get(vendor, 0) + 1

        # Curation lookup. Fall back to "Other" when we haven't curated it.
        use_cases = CURATION.get(vendor)
        if use_cases is None:
            use_cases = ["Other"]
            fallback_other.append(f"{vendor} ({d.name})")

        # Idempotent: skip if already correct.
        existing = doc.get("use_cases")
        if existing == use_cases:
            skipped_unchanged += 1
            continue

        doc["use_cases"] = use_cases
        if not args.dry_run:
            with yaml_path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)
        updated_count += 1

    print(f"=== Curation summary ===")
    print(f"  YAMLs updated:       {updated_count}")
    print(f"  YAMLs unchanged:     {skipped_unchanged}")
    print(f"  Distinct vendors:    {len(vendor_seen)}")
    print(f"  Vendors in CURATION: {len(CURATION)}")
    print(f"  Fell to 'Other':     {len(fallback_other)}")

    # Sanity check: which CURATION entries had no matching YAML
    unused = [v for v in CURATION if v not in vendor_seen]
    if unused:
        print()
        print(f"=== CURATION entries with no matching vendor in YAMLs ({len(unused)}) ===")
        for v in sorted(unused):
            print(f"  {v}")
        print("  (these are dead entries; remove them or correct the spelling)")

    if fallback_other:
        print()
        print(f"=== Vendors that fell to 'Other' ({len(fallback_other)}) ===")
        # Group by unique vendor
        unique_vendors = sorted(set(line.split(" (")[0] for line in fallback_other))
        for v in unique_vendors:
            print(f"  {v}")
        print("  (add these to CURATION to get a meaningful use_case)")

    if args.dry_run:
        print("\n(dry-run; no files written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
