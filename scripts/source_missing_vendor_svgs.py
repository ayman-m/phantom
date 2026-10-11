"""Source SVGs for vendors with no baked asset from simple-icons.

Per scripts/CLAUDE.md framing: MAINTAINER-ONLY research/build tool.
Runtime never re-runs it.

## Why

After the inline-embed pass (inline_embed_baked_logos.py), some
data_source.yaml files still have `logo: null` because the baked cortex-content tree has no asset
for those packs (Apache, Apple, Arista, Brocade, Citrix, Dell EMC,
NGINX, Kubernetes, IBM, MySQL, etc.).

Simple Icons (https://simpleicons.org/) maintains an MIT-licensed
collection of brand SVGs for major tech vendors. Pulling from
simple-icons covers most of our gap with one-color brand marks that
look correct on a neutral background.

## Mapping

Per-pack-name → simple-icons slug. A mismatch (e.g. simple-icons has
`apachetomcat` not `apache-tomcat`) requires explicit mapping; for
most vendors the slug is just the canonical vendor name lowercased
+ stripped of spaces/hyphens.

This script consults a hand-maintained mapping table — adding a new
vendor here is intentional, not magic.

## Cadence

Run when the YAML logo coverage gaps need filling. Idempotent: skips
any YAML with an existing inline logo.
"""
from __future__ import annotations

import argparse
import base64
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_SOURCES_DIR = REPO_ROOT / "bundles" / "spark" / "data-sources"

# Simple Icons CDN root. Each slug → /icons/<slug>.svg
SIMPLE_ICONS_CDN = "https://cdn.jsdelivr.net/npm/simple-icons@latest/icons"

# Pack name → simple-icons slug. The lookup is by PACK NAME (matching
# what's in the YAML's `pack_name:` field), not by display vendor —
# different packs from the same vendor may need different slugs (or
# just one shared one).
PACK_TO_SLUG: dict[str, str] = {
    # Apache family — all share the apache feather slug
    "ApacheTomcat": "apachetomcat",
    "ApacheWebServer": "apache",
    # Apple
    "MacOS": "apple",
    # Amazon
    "AWS_ELB": "amazonaws",
    # Network / switches
    "AristaSwitch": "arista",
    "BrocadeSwitch": "brocade",  # may not exist; fallback to None below
    "CiscoASR": "cisco",
    "CiscoISR": "cisco",
    "CiscoNexus": "cisco",
    "Cisco_Wireless_LAN_Controller": "cisco",
    "HPESwitch": "hewlettpackardenterprise",
    "HuaweiNetworkDevices": "huawei",
    "JuniperSRX": "junipernetworks",
    "FortiManager": "fortinet",
    # Cloud / orchestration
    "CitrixADC": "citrix",
    "Kubernetes": "kubernetes",
    "DellEMCUnity": "dell",
    # Identity / auth
    "RSASecureID": "rsasoftware",
    "BeyondTrustPrivilegedRemoteAccess": "beyondtrust",
    "BeyondTrustRemoteSupport": "beyondtrust",
    # Misc tech vendors
    "Auditd": "linux",
    "MySQLEnterprise": "mysql",
    "NGINXWebServer": "nginx",
    "HashiCorp-Vault": "hashicorp",
    "IBM_AIX": "ibm",
    "Squid": "squid",
    "Tableau": "tableau",
    "TigeraCalico": "tigera",  # might not exist
    "TrendMicroInterScanWebSecurity": "trendmicro",
    "Avaya": "avaya",  # might not exist
    "AvayaAuraCommunicationManager": "avaya",
    "Kiteworks": "kiteworks",  # might not exist
    # Sec vendors that may not be in simple-icons
    "F5APM": "f5",
    "F5BigIPAWAF": "f5",
    "BarracudaEmailProtection": "barracuda",  # may not exist
    "BarracudaWAF": "barracuda",
    "BarracudaWAFAS": "barracuda",
    "ClearswiftDLP": None,        # explicitly null = skip; not in simple-icons
    "SecureAuthIdentityPlatform": None,
    "SemperisDSP": None,
    "Siemens_SiPass": "siemens",
    "SonicWallNSv": "sonicwall",
    "ManageEngine-ADManager": "zoho",   # ManageEngine is Zoho's
    "BluecatAddressManager": None,
    # Extended mappings, confirmed available on the simple-icons CDN.
    "MicrosoftIISWebServer": "microsoft",
    "MicrosoftNPS": "microsoft",
    "MicrosoftWSUS": "microsoft",
    "OktaOAG": "okta",
    "VMwareESXi": "vmware",
    "VMwareVCenter": "vmware",
    # Probe-confirmed gaps (return None to avoid the fetch attempt):
    "IvantiConnectSecure": None,
    "IvantiPulseSecureVTM": None,
    "RadwareCloudServices": None,
    # F5ASM already has an inline base64 logo — don't override
    "F5ASM": None,
}


def fetch_svg(slug: str) -> bytes | None:
    """Try to fetch one simple-icons SVG. Returns None on 404/error."""
    url = f"{SIMPLE_ICONS_CDN}/{slug}.svg"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "phantom-maintainer"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    yaml_dirs = sorted(d for d in DATA_SOURCES_DIR.iterdir() if d.is_dir())

    candidates: list[tuple[Path, str, str]] = []  # (yaml_path, pack_name, slug)
    skipped_has_logo = 0
    skipped_no_mapping: list[str] = []
    skipped_explicit_null: list[str] = []

    for d in yaml_dirs:
        yaml_path = d / "data_source.yaml"
        if not yaml_path.is_file():
            continue
        try:
            doc = yaml.safe_load(yaml_path.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        if doc.get("logo"):
            skipped_has_logo += 1
            continue
        pack_name = doc.get("pack_name")
        if pack_name is None:
            continue
        if pack_name not in PACK_TO_SLUG:
            skipped_no_mapping.append(pack_name)
            continue
        slug = PACK_TO_SLUG[pack_name]
        if slug is None:
            skipped_explicit_null.append(pack_name)
            continue
        candidates.append((yaml_path, pack_name, slug))

    print(f"=== Sourcing summary ===")
    print(f"  YAMLs already with inline logo (skipped): {skipped_has_logo}")
    print(f"  YAMLs with no slug mapping: {len(skipped_no_mapping)}")
    print(f"  YAMLs explicitly mapped to None (slug not on simple-icons): {len(skipped_explicit_null)}")
    print(f"  Candidates to fetch from simple-icons: {len(candidates)}")
    print()

    fetched = []
    not_found = []

    for yaml_path, pack_name, slug in candidates:
        svg_bytes = fetch_svg(slug)
        if svg_bytes is None:
            not_found.append((pack_name, slug))
            print(f"  ✗ {pack_name:50s} simpleicons/{slug} → 404")
            continue
        if args.dry_run:
            print(f"  ✓ {pack_name:50s} simpleicons/{slug} → {len(svg_bytes)} bytes (dry-run)")
            fetched.append((pack_name, slug, len(svg_bytes)))
            continue
        # Inline-embed into YAML
        doc = yaml.safe_load(yaml_path.read_text())
        doc["logo"] = {
            "mime_type": "image/svg+xml",
            "data": base64.b64encode(svg_bytes).decode("ascii"),
            "source": f"simpleicons:{slug}",
            "license": "CC0-1.0",
            "fidelity": "monochrome-brand",
        }
        with yaml_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)
        print(f"  ✓ {pack_name:50s} simpleicons/{slug} → {len(svg_bytes)} bytes")
        fetched.append((pack_name, slug, len(svg_bytes)))

    print(f"\n=== Results ===")
    print(f"  Newly inline-embedded: {len(fetched)}")
    print(f"  Not in simple-icons:   {len(not_found)}")
    if not_found:
        print(f"\nNot found (need alternative source):")
        for pn, sl in not_found:
            print(f"  {pn} (tried slug={sl})")
    if skipped_no_mapping:
        print(f"\nPacks with no slug mapping in PACK_TO_SLUG (add manually):")
        for pn in skipped_no_mapping[:30]:
            print(f"  {pn}")
        if len(skipped_no_mapping) > 30:
            print(f"  ... + {len(skipped_no_mapping) - 30} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
