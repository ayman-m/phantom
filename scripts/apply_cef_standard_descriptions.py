#!/usr/bin/env python3
"""Apply CEF (ArcSight Common Event Format)
standard field descriptions to bundled YAMLs.

# Why

Many CEF-based vendors (Check Point, Cloudflare, FireEye, F5,
McAfee, etc.) use the standard ArcSight CEF custom-string/number/
header field set: cs1-cs6, cn1-cn3, src, dst, spt, dpt, proto, app,
act, suser, duser, fname, etc. These have well-defined meanings per
the CEF spec; one curated dictionary unlocks descriptions across many
vendors at once.

# Strategy

For each field in each YAML without a description:
  1. Look up the exact field name in CEF_STANDARD
  2. If hit, write that description
  3. If miss, leave for the vendor-specific dictionaries

Skips fields with existing descriptions (manually curated or XDM-derived
ones are never overwritten).

# Source

Official CEF spec field reference (Micro Focus / ArcSight):
https://www.microfocus.com/documentation/arcsight/arcsight-smartconnectors-8.3/cef-implementation-standard/Content/CEF/Chapter%201%20What%20is%20CEF.htm
"""

from __future__ import annotations
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from extend_data_source_fields import update_one_yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_ROOT = REPO_ROOT / "bundles" / "spark" / "data-sources"


# ─── CEF standard field → description dictionary ────────────────


CEF_STANDARD: dict[str, str] = {
    # CEF header (always present)
    "cefName": "CEF event name",
    "cefSeverity": "CEF severity (0-10)",
    "cefseverity": "CEF severity (0-10)",
    "cefDeviceVendor": "CEF device vendor",
    "cefDeviceProduct": "CEF device product",
    "cefDeviceVersion": "CEF device version",
    "cefSignatureId": "CEF event class id (signature)",

    # Core network 5-tuple
    "src": "Source IPv4 address",
    "dst": "Destination IPv4 address",
    "spt": "Source port",
    "dpt": "Destination port",
    "proto": "Network protocol (e.g. tcp/udp/icmp)",
    "in": "Bytes inbound (from src toward dst)",
    "out": "Bytes outbound (from dst toward src)",
    "cnt": "Event count (aggregation)",

    # Application + service
    "app": "Application protocol or service name",
    "service_id": "Service identifier",
    "request": "HTTP request URL",
    "requestMethod": "HTTP request method (GET/POST/...)",
    "requestClientApplication": "HTTP user agent / client app",
    "requestContext": "HTTP request context (e.g. session/page)",

    # Hosts + identity
    "shost": "Source hostname",
    "dhost": "Destination hostname",
    "dvc": "Reporting device address",
    "dvchost": "Reporting device hostname",
    "smac": "Source MAC address",
    "dmac": "Destination MAC address",
    "suser": "Source username",
    "duser": "Destination username",
    "suid": "Source user id",
    "duid": "Destination user id",
    "spriv": "Source user privileges",
    "dpriv": "Destination user privileges",
    "sproc": "Source process name",
    "dproc": "Destination process name",
    "spid": "Source process id",
    "dpid": "Destination process id",

    # Files
    "fname": "File name",
    "fsize": "File size (bytes)",
    "filePath": "File path",
    "fileType": "File type",
    "fileHash": "File hash",
    "fileId": "File id",
    "fileCreateTime": "File create time",
    "fileModificationTime": "File modification time",

    # Time
    "rt": "Event receipt time",
    "start": "Event start time",
    "end": "Event end time",
    "deviceReceiptTime": "Device receipt time",

    # Identifiers
    "externalID": "Vendor-side event id",
    "externalId": "Vendor-side event id",
    "deviceExternalId": "Reporting device id",
    "sourceServiceName": "Source service name",

    # Action + outcome
    "act": "Action taken (allow/deny/block/...)",
    "outcome": "Event outcome",
    "reason": "Reason for event",
    "msg": "Event message",
    "cat": "Event category",

    # CEF custom strings + their labels
    # The Label field describes what the corresponding cs<N> contains
    # (e.g. cs1Label='ApplicationName' means cs1 holds an application name).
    # Without per-vendor context we describe them generically.
    "cs1": "Device custom string 1 (see cs1Label)",
    "cs2": "Device custom string 2 (see cs2Label)",
    "cs3": "Device custom string 3 (see cs3Label)",
    "cs4": "Device custom string 4 (see cs4Label)",
    "cs5": "Device custom string 5 (see cs5Label)",
    "cs6": "Device custom string 6 (see cs6Label)",
    "cs1Label": "Label/name for cs1",
    "cs2Label": "Label/name for cs2",
    "cs3Label": "Label/name for cs3",
    "cs4Label": "Label/name for cs4",
    "cs5Label": "Label/name for cs5",
    "cs6Label": "Label/name for cs6",

    # CEF custom numbers
    "cn1": "Device custom number 1 (see cn1Label)",
    "cn2": "Device custom number 2 (see cn2Label)",
    "cn3": "Device custom number 3 (see cn3Label)",
    "cn1Label": "Label/name for cn1",
    "cn2Label": "Label/name for cn2",
    "cn3Label": "Label/name for cn3",

    # CEF custom floating points
    "cfp1": "Device custom float 1 (see cfp1Label)",
    "cfp2": "Device custom float 2 (see cfp2Label)",
    "cfp3": "Device custom float 3 (see cfp3Label)",
    "cfp4": "Device custom float 4 (see cfp4Label)",

    # IPv6 variants
    "c6a1": "Device custom IPv6 1 (see c6a1Label)",
    "c6a2": "Device custom IPv6 2 (see c6a2Label)",
    "c6a3": "Device custom IPv6 3 (see c6a3Label)",
    "c6a4": "Device custom IPv6 4 (see c6a4Label)",
    "c6a1Label": "Label/name for c6a1",
    "c6a2Label": "Label/name for c6a2",
    "c6a3Label": "Label/name for c6a3",
    "c6a4Label": "Label/name for c6a4",

    # Flex variants
    "flexString1": "Flexible string 1 (see flexString1Label)",
    "flexString2": "Flexible string 2 (see flexString2Label)",
    "flexString1Label": "Label/name for flexString1",
    "flexString2Label": "Label/name for flexString2",
    "flexNumber1": "Flexible number 1 (see flexNumber1Label)",
    "flexNumber2": "Flexible number 2 (see flexNumber2Label)",
    "flexDate1": "Flexible date 1 (see flexDate1Label)",

    # Source/destination geographic
    "sourceTranslatedAddress": "Source translated (post-NAT) IPv4",
    "destinationTranslatedAddress": "Destination translated (post-NAT) IPv4",
    "sourceTranslatedPort": "Source translated (post-NAT) port",
    "destinationTranslatedPort": "Destination translated (post-NAT) port",
    "deviceInboundInterface": "Reporting device inbound interface",
    "deviceOutboundInterface": "Reporting device outbound interface",

    # Web/proxy specific
    "destinationServiceName": "Destination service name",
    "destinationDnsDomain": "Destination DNS domain",
    "sourceDnsDomain": "Source DNS domain",
    "destinationUserPrivileges": "Destination user privileges",
    "sourceUserPrivileges": "Source user privileges",
    "categorySignificance": "Event category significance",
    "categoryBehavior": "Event category behavior",
    "categoryDeviceType": "Event category device type",
    "categoryOutcome": "Event category outcome",
    "categoryObject": "Event category object",
    "categoryDeviceGroup": "Event category device group",
}


def main() -> int:
    print("=== CEF standard description backfill ===")
    print(f"  CEF standard fields in dictionary: {len(CEF_STANDARD)}\n")

    import yaml

    filled = 0
    yamls_modified = 0
    fill_per_field: Counter[str] = Counter()

    for ds_dir in sorted(BUNDLE_ROOT.glob("*/")):
        yaml_path = ds_dir / "data_source.yaml"
        if not yaml_path.is_file():
            continue
        d = yaml.safe_load(yaml_path.read_text()) or {}
        fields = d.get("fields") or []
        if not fields:
            continue

        any_changed = False
        new_fields: list[dict[str, Any]] = []
        for f in fields:
            if not isinstance(f, dict):
                new_fields.append(f)
                continue
            existing = (f.get("description") or "").strip()
            if existing:
                new_fields.append(f)
                continue
            name = f.get("name")
            desc = CEF_STANDARD.get(name) if name else None
            if desc:
                nf = dict(f)
                nf["description"] = desc
                new_fields.append(nf)
                filled += 1
                fill_per_field[name] += 1
                any_changed = True
            else:
                new_fields.append(f)

        if any_changed:
            ok, msg = update_one_yaml(yaml_path, new_fields)
            if ok:
                yamls_modified += 1
            else:
                print(f"  ! write failed {ds_dir.name}: {msg}")

    print(f"  Newly filled (CEF standard) : {filled}")
    print(f"  YAMLs modified              : {yamls_modified}")
    print()
    print("  Top 15 most-impacted field names:")
    for name, count in fill_per_field.most_common(15):
        print(f"    {name:25s} {count} packs")

    return 0


if __name__ == "__main__":
    sys.exit(main())
