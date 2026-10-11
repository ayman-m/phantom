#!/usr/bin/env python3
"""Build 6 PANW NGFW data_source.yaml packs from hand-curated field schemas.

PANW NGFW is the first multi-dataset vendor we've onboarded — one vendor produces
6 distinct dataset destinations (globalprotect, hipmatch, traffic, filedata, threat,
url) via Cortex's CEF auto-routing pattern.

Why hand-curated (not auto-extracted from the MR):
  - Generator script auto-extraction yields generic "Vendor-emitted field 'X'.
    Free-form text..." descriptions. PANW NGFW is too important for that — operators
    need to understand what each field MEANS, not just that it exists.
  - The MR also doesn't expose nuance like "this field uses the special sentinel
    `00000000000000000000ffff00000000` for empty IPv6" — only cognitive analysis catches that.

Operator setup needed:
  - The broker VM must have a Syslog Applet configured: vendor=panw, product=ngfw_cef,
    on a dedicated port (e.g. 1516+). Without that, events land in unknown_unknown_raw.
  - Cortex's upstream PANW NGFW parsing rule includes per-log_type INGEST routing
    (filter=log_type=="traffic" → panw_ngfw_traffic_raw, etc.) — that's where the
    actual 6-dataset split happens. Our pasted PR is the no-hit catch-all only;
    customers install the upstream PANW NGFW Cortex pack which provides the per-log_type
    routing.

Usage:
    python3 scripts/maintainer/build_panw_ngfw_packs.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit("ERROR: PyYAML required. pip install pyyaml")

OUTPUT_DIR = Path(__file__).parent / "generated_data_sources"

# ============================================================
# Field schemas (hand-curated, per dataset)
# ============================================================
# Format: field_name -> (type, description, example)
# Examples are chosen to be test-friendly (trigger the MR's enum branches
# where possible, satisfy length checks for hash branches, etc.)

# Shared base fields used by traffic, filedata, threat, url (via `ngfw_standalone` RULE)
NGFW_STANDALONE_FIELDS: dict[str, tuple[str, str, str]] = {
    "action": ("string", "Action taken by the firewall on the session/packet. Common values: allow, deny, drop, reset-client, reset-server, reset-both, block-url, block-continue, continue, override.", "allow"),
    "app": ("string", "Application identified by App-ID (PANW's content classification engine). Examples: web-browsing, ssl, ssh, smtp, dns, ms-rdp, microsoft-teams.", "web-browsing"),
    "app_category": ("string", "High-level application category (App-ID tier 1). Examples: general-internet, business-systems, networking, collaboration, media.", "general-internet"),
    "app_sub_category": ("string", "App-ID tier 2 subcategory. Examples: internet-utility, file-sharing, encrypted-tunnel, ip-protocol.", "internet-utility"),
    "dest_device_category": ("string", "Device category of the destination host (when PANW Device-ID identifies it). Examples: server, mobile, iot, router, switch.", "server"),
    "dest_device_host": ("string", "Hostname of the destination host as resolved by PANW Device-ID. Used for `xdm.target.host.hostname` only if it doesn't contain ':' (which would suggest a MAC).", "dst-host.corp.example.com"),
    "dest_device_mac": ("string", "MAC address of the destination host (Device-ID). Six colon-separated hex octets.", "00:50:56:aa:bb:02"),
    "dest_device_model": ("string", "Device model string from PANW Device-ID inventory. Examples: VMware ESXi, MacBookPro18,3, iPhone13,4.", "Dell PowerEdge R740"),
    "dest_device_os": ("string", "Operating system of the destination host (Device-ID). Free-form, vendor-supplied.", "Ubuntu 22.04"),
    "dest_device_osfamily": ("string", "OS family of destination host. Drives `xdm.target.host.os_family` enum: Windows, MacOS/Mac, ios/iOS, Chromeos, Linux, Android.", "Linux"),
    "dest_device_vendor": ("string", "Hardware vendor of the destination host (Device-ID). Examples: Dell, Apple, Cisco, HP.", "Dell Inc."),
    "dest_ip": ("string", "Destination IP address — IPv4 or IPv6. The MR detects IPv6 by the presence of ':' and routes to `xdm.target.ipv6` accordingly. Sentinel value `00000000000000000000ffff00000000` is treated as empty.", "10.20.30.40"),
    "dest_port": ("integer", "Destination TCP/UDP port (1-65535). Cast to integer in the MR; non-numeric values become null.", "443"),
    "dest_user": ("string", "Destination user as identified by PANW User-ID (LDAP/AD/RADIUS lookup on dest_ip). Examples: corp\\\\jdoe, jdoe@example.com.", "corp\\\\bob"),
    "from_zone": ("string", "Source security zone (the firewall zone the session originated from). Examples: trust, untrust, dmz, internal, guest.", "trust"),
    "inbound_if": ("string", "Inbound interface name (the firewall interface that received the session). Examples: ethernet1/1, ae1.100, tunnel.5.", "ethernet1/1"),
    "is_nat": ("string", "Whether source/dest NAT was applied to the session. Cast to boolean. Values: 'true', 'false', 'True', 'False'.", "false"),
    "is_proxy": ("string", "Whether the firewall proxied the session (e.g. SSL decrypt, explicit proxy). Cast to boolean. When true, `xdm.intermediate.ipv4/ipv6/port` get populated from dest_ip/dest_port.", "false"),
    "log_source": ("string", "Log source type identifier (PANW's Cortex Cloud Identity Engine value or similar). Maps to `xdm.observer.type`.", "panw-ngfw"),
    "log_source_id": ("string", "Unique identifier of the log source instance (serial number or UUID of the firewall emitting the log).", "001801000001"),
    "log_source_name": ("string", "Friendly name of the log source (firewall hostname or assigned name).", "pa-fw-hq-01"),
    "log_type": ("string", "PANW log subsystem that produced this event. Drives `xdm.event.type`. Common values: traffic, threat, url, file, hipmatch, globalprotect, system, config.", "traffic"),
    "outbound_if": ("string", "Outbound interface name (the firewall interface forwarding the session). Examples: ethernet1/2, ae2.200.", "ethernet1/2"),
    "protocol": ("string", "IP protocol — lowercase string. The MR maps icmp/tcp/udp to XDM enums; other values pass through as-is.", "tcp"),
    "rule_matched": ("string", "Name of the security policy rule that matched this session. Maps to `xdm.network.rule`.", "Allow-Web-Browsing"),
    "session_id": ("string", "Unique session identifier (PANW's session number for this flow). Maps to `xdm.event.id` AND `xdm.session_context_id` in the standalone RULE.", "1234567"),
    "source_device_category": ("string", "Device category of the source host (Device-ID). Examples: workstation, mobile, iot, server.", "workstation"),
    "source_device_host": ("string", "Hostname of the source host (Device-ID). Used for `xdm.source.host.hostname` only if it doesn't contain ':' (which would suggest a MAC).", "src-host.corp.example.com"),
    "source_device_mac": ("string", "MAC address of the source host (Device-ID).", "00:50:56:aa:bb:01"),
    "source_device_model": ("string", "Device model of the source host (Device-ID).", "MacBookPro18,3"),
    "source_device_os": ("string", "OS of the source host (Device-ID).", "macOS 14.0"),
    "source_device_osfamily": ("string", "OS family of source host. Drives `xdm.source.host.os_family` enum.", "MacOS"),
    "source_device_vendor": ("string", "Hardware vendor of the source host (Device-ID).", "Apple Inc."),
    "source_ip": ("string", "Source IP address — IPv4 or IPv6. IPv6 detected by ':'.", "10.1.2.3"),
    "source_port": ("integer", "Source TCP/UDP port.", "54321"),
    "source_user": ("string", "Source user (PANW User-ID).", "corp\\\\alice"),
    "sub_type": ("string", "Log subtype — discriminator within a log_type. For traffic: start, end, drop, deny. For threat: vulnerability, virus, spyware, wildfire-virus, file. For url: url. Maps to `xdm.event.operation_sub_type`.", "end"),
    "to_zone": ("string", "Destination security zone.", "untrust"),
}

PANW_NGFW_DATASETS: dict[str, dict[str, Any]] = {
    "panw_ngfw_traffic_raw": {
        "vendor": "Palo Alto Networks",
        "product": "NGFW Traffic",
        "pack_name": "PANW_NGFW",
        "rule_name": "PANW_NGFW",
        "description": "Palo Alto Networks Next-Generation Firewall — session traffic logs (flow start/end/drop/deny with bytes/packets accounting).",
        "categories": ["Network Security", "Firewall"],
        "extra_fields": {
            "bytes_received": ("integer", "Total bytes received from server → client during the session. Maps to `xdm.target.sent_bytes`.", "16384"),
            "bytes_sent": ("integer", "Total bytes sent from client → server. Maps to `xdm.source.sent_bytes`.", "4096"),
            "packets_received": ("integer", "Packet count received (server → client). Maps to `xdm.target.sent_packets`.", "42"),
            "packets_sent": ("integer", "Packet count sent (client → server). Maps to `xdm.source.sent_packets`.", "28"),
            "total_time_elapsed": ("integer", "Session duration in SECONDS (vendor-emitted unit). MR multiplies by 1000 to produce `xdm.event.duration` in milliseconds.", "60"),
        },
        "mr_notes": "Traffic-specific outcome: when sub_type IN ('drop','deny'), xdm.event.outcome = FAILED. Other sub_types leave outcome null (the MR has no else branch).",
    },
    "panw_ngfw_filedata_raw": {
        "vendor": "Palo Alto Networks",
        "product": "NGFW File Data",
        "pack_name": "PANW_NGFW",
        "rule_name": "PANW_NGFW",
        "description": "Palo Alto Networks NGFW — file inspection events (WildFire submissions, file blocking, content inspection).",
        "categories": ["Network Security", "Firewall", "Malware Analysis"],
        "extra_fields": {
            "container_id": ("string", "Container/sandbox identifier when the file was analyzed in WildFire. Maps to `xdm.source.process.container_id`.", "wf-container-abc123"),
            "content_version": ("string", "PANW content database version at time of inspection. Maps to `xdm.observer.content_version`.", "8650-7926"),
            "dest_uuid": ("string", "UUID assigned to the destination host (Device-ID identity). Maps to `xdm.target.host.hardware_uuid`.", "dst-uuid-90abcdef"),
            "file_name": ("string", "Name of the inspected file. Extension is auto-extracted (last component after '.'). Maps to `xdm.target.file.filename`.", "invoice.pdf"),
            "file_sha_256": ("string", "SHA-256 hash of the file (64 hex chars). Maps to `xdm.target.file.sha256`.", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
            "file_type": ("string", "MIME-style file type as classified by PANW (e.g. PE32, PDF, MSI, ELF, MachO).", "PDF"),
            "file_url": ("string", "Original URL from which the file was retrieved (if applicable). Maps to `xdm.target.file.path`.", "https://example.com/downloads/invoice.pdf"),
            "source_uuid": ("string", "UUID of the source host (Device-ID). Maps to `xdm.source.host.hardware_uuid`.", "src-uuid-12345678"),
            "url_category": ("string", "PANW URL category for the source/destination URL (e.g. business-and-economy, malware, phishing). Maps to `xdm.network.http.url_category`.", "business-and-economy"),
            "vendor_severity": ("string", "PANW-assigned severity for the file finding. Values: informational, low, medium, high, critical. Maps to `xdm.alert.severity`.", "high"),
        },
        "mr_notes": "Filename extension is parsed by `arrayindex(split(file_name, '.'), -1)` — won't fire if file_name lacks a '.'.",
    },
    "panw_ngfw_threat_raw": {
        "vendor": "Palo Alto Networks",
        "product": "NGFW Threat",
        "pack_name": "PANW_NGFW",
        "rule_name": "PANW_NGFW",
        "description": "Palo Alto Networks NGFW — threat detection events (IPS signatures, antivirus, anti-spyware, WildFire verdicts, DNS security).",
        "categories": ["Network Security", "Firewall", "IDS/IPS"],
        "extra_fields": {
            "file_name": ("string", "Filename when threat involves a file artifact. When file_sha_256 is non-null, maps to `xdm.target.file.filename`; otherwise maps to `xdm.network.http.url` (treated as the URL the threat was found on).", "malware.exe"),
            "file_sha_256": ("string", "SHA-256 hash of the threat artifact. Maps to `xdm.target.file.sha256`.", "44d88612fea8a8f36de82e1278abb02f8c6f3a0a8c70b1cd62f0d8bf2e1f00ab"),
            "file_type": ("string", "File type of the threat artifact.", "PE32"),
            "http_method": ("string", "HTTP method when threat detected on HTTP traffic. Lowercase enum routed by `url_threat_common_fields` RULE: get/post/connect/head/put/delete/options. Maps to `xdm.network.http.method`.", "get"),
            "severity": ("string", "Threat severity assigned by PANW. Values: informational, low, medium, high, critical. Maps to `xdm.alert.severity`.", "high"),
            "subject_of_email": ("string", "Subject line when threat detected in email (SMTP traffic). Maps to `xdm.email.subject`.", "Urgent: Invoice attached"),
            "threat_category": ("string", "Threat category — lowercased and mapped to XDM enum. Recognized values include: apk, dmg, flash, java-class, macho, office, openoffice, pdf, pe, pkg, adware, autogen, backdoor, botnet, browser-hijack, cryptominer, data-theft, dns, dns-security, dns-wildfire, downloader, fraud, hacktool, keylogger, networm, phishing-kit, post-exploitation, webshell, spyware, brute force (with space), code execution, code-obfuscation, dos, exploit-kit, info-leak, insecure-credentials, overflow, phishing, protocol-anomaly, sql-injection. Unrecognized values fall through as the raw string.", "backdoor"),
            "threat_id": ("string", "Unique PANW threat ID (signature ID for IPS, hash ID for AV, etc.). Cast to string. Maps to `xdm.alert.original_threat_id`.", "31337"),
            "threat_name": ("string", "Human-readable threat name (e.g. signature title). Maps to `xdm.alert.original_threat_name`.", "Generic.Trojan.Backdoor"),
            "url_domain": ("string", "Domain extracted from the URL where the threat was observed. Maps to `xdm.source.host.fqdn`.", "malicious-host.example"),
            "verdict": ("string", "WildFire verdict for files (malicious, benign, grayware, phishing) or other vendor verdict string. Maps to `xdm.alert.description`.", "malicious"),
        },
        "mr_notes": "Threat-category mapping: 'brute force' (with space) is the literal MR expects — NOT 'brute-force' (with hyphen). The MR also has 'sql-injection' (with hyphen). Honor existing literals exactly.",
        "anomalies": [
            {
                "type": "literal_space_vs_hyphen",
                "severity": "info",
                "field": "threat_category",
                "description": "The MR matches 'brute force' (space) and 'code execution' (space) but 'code-obfuscation' (hyphen), 'sql-injection' (hyphen). Vendor inconsistency — honor exact literals when constructing payloads.",
            }
        ],
    },
    "panw_ngfw_url_raw": {
        "vendor": "Palo Alto Networks",
        "product": "NGFW URL Filtering",
        "pack_name": "PANW_NGFW",
        "rule_name": "PANW_NGFW",
        "description": "Palo Alto Networks NGFW — URL filtering events (web traffic categorization, block/allow decisions, content inspection).",
        "categories": ["Network Security", "Firewall", "Web Filtering"],
        "extra_fields": {
            "content_type": ("string", "HTTP Content-Type header value. Maps to `xdm.network.http.content_type`.", "text/html"),
            "http_method": ("string", "HTTP method — lowercase enum (get/post/connect/head/put/delete/options) from `url_threat_common_fields` RULE.", "get"),
            "referer": ("string", "HTTP Referer header value (note: vendor preserves original HTTP misspelling). Maps to `xdm.network.http.referrer`.", "https://search.example.com/results"),
            "uri": ("string", "Full request URI (path + query string). Maps to `xdm.network.http.url`.", "/index.html?session=abc"),
            "url_category": ("string", "PANW URL category for the requested URL. Maps to `xdm.network.http.url_category`.", "search-engines"),
            "url_domain": ("string", "Domain from the requested URL. Maps to `xdm.network.http.domain`.", "example.com"),
            "user_agent": ("string", "HTTP User-Agent header. Maps to `xdm.source.user_agent`.", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"),
        },
        "mr_notes": "URL `action` field has a richer enum than ngfw_standalone — adds block-url, block-continue, continue, block-override, override-lockout, override. Each maps to a specific `xdm.event.outcome` (SUCCESS/FAILED/PARTIAL).",
    },
    "panw_ngfw_globalprotect_raw": {
        "vendor": "Palo Alto Networks",
        "product": "NGFW GlobalProtect VPN",
        "pack_name": "PANW_NGFW",
        "rule_name": "PANW_NGFW",
        "description": "Palo Alto Networks NGFW — GlobalProtect VPN client events (connect, disconnect, authentication, gateway selection).",
        "categories": ["Network Security", "VPN", "Authentication"],
        "extra_fields": {
            "auth_method": ("string", "Authentication method used by the VPN client. Examples: SAML, LDAP, RADIUS, CertificateBased, KerberosV5. Maps to `xdm.auth.auth_method`.", "SAML"),
            "connection_error": ("string", "Reason text when the connection failed. Maps to `xdm.event.outcome_reason`.", "Authentication failed: invalid SAML response"),
            "endpoint_device_name": ("string", "Hostname of the GlobalProtect client device. Maps to `xdm.source.host.hostname`.", "alice-mbp.corp.example.com"),
            "endpoint_gp_version": ("string", "GlobalProtect agent version on the client. Cast to string. Maps to `xdm.source.application.version`.", "6.2.4"),
            "endpoint_os_type": ("string", "Client OS type — drives `xdm.source.host.os_family` enum. Recognized values: Windows, macOS/Mac, Linux. Other values pass through as uppercase(endpoint_os_version).", "macOS"),
            "endpoint_os_version": ("string", "Client OS version string. Maps to `xdm.source.host.os`. Also used as os_family fallback for non-canonical os_type values.", "14.0.1 (23A344)"),
            "event_id": ("string", "VPN event identifier. Maps to `xdm.event.description` — used as a freeform description, NOT a numeric ID.", "GP_USER_CONNECT_SUCCESS"),
            "gateway": ("string", "GlobalProtect gateway hostname the client connected to. Maps to `xdm.target.host.hostname`.", "gp-gateway-us-west.corp.example.com"),
            "host_id": ("string", "Unique host identifier — either UUID format OR MAC address (detected by presence of ':'). When MAC, also populates `xdm.source.host.mac_addresses`.", "12345678-1234-1234-1234-123456789abc"),
            "log_source": ("string", "Log source type. Maps to `xdm.observer.type`.", "panw-globalprotect"),
            "log_source_id": ("string", "Unique log source instance identifier.", "001801000002"),
            "log_source_name": ("string", "Friendly log source name. Maps to `xdm.observer.name`.", "pa-fw-hq-01"),
            "login_duration": ("integer", "VPN session duration in SECONDS. MR multiplies by 1000 → `xdm.event.duration` (milliseconds).", "3600"),
            "private_ip": ("string", "VPN-assigned private IPv4. Treated as empty if equal to sentinel `00000000000000000000ffff00000000`. Maps to `xdm.network.vpn.allocated_ipv4`.", "10.100.50.25"),
            "private_ipv6": ("string", "VPN-assigned private IPv6 (sentinel `00000000000000000000ffff00000000` treated as empty). Maps to `xdm.network.vpn.allocated_ipv6`.", "2001:db8:vpn::1"),
            "public_ip": ("string", "Client's public IPv4 at connection time. Sentinel-aware. Maps to `xdm.source.ipv4`.", "203.0.113.45"),
            "public_ipv6": ("string", "Client's public IPv6 at connection time. Sentinel-aware. Maps to `xdm.source.ipv6`.", "2001:db8:client::1"),
            "sequence_no": ("integer", "Monotonic event sequence number from the firewall. Cast to string for `xdm.event.id`.", "987654321"),
            "source_region": ("string", "Two-letter country code of the client public IP (only populates `xdm.source.location.country` when len()==2).", "US"),
            "source_user": ("string", "VPN authenticated user. Maps to BOTH `xdm.source.user.username` AND `xdm.source.identity.username`.", "alice@corp.example.com"),
            "source_user_info_domain": ("string", "User's AD domain. Maps to `xdm.source.user.domain` AND `xdm.source.identity.domain`.", "corp.example.com"),
            "stage": ("string", "Connection stage. Examples: before-login, login, tunnel-up, pre-tunnel, tunnel-down, gateway-selected. Maps to `xdm.event.operation`.", "tunnel-up"),
            "status": ("string", "Connection status. Drives `xdm.event.outcome` enum: 'success' → SUCCESS, 'failure' → FAILED, anything else → UNKNOWN.", "success"),
        },
        "mr_notes": "STANDALONE model — does NOT call ngfw_standalone. Has its own field shape entirely. The `_empty_ip` sentinel ('00000000000000000000ffff00000000') is used as a marker for unset IPv6 addresses.",
        "anomalies": [
            {
                "type": "ipv6_sentinel",
                "severity": "info",
                "fields": ["private_ip", "private_ipv6", "public_ip", "public_ipv6"],
                "description": "MR treats the literal string '00000000000000000000ffff00000000' as 'empty IPv6'. Send any non-sentinel value to populate the corresponding XDM target.",
            }
        ],
    },
    "panw_ngfw_hipmatch_raw": {
        "vendor": "Palo Alto Networks",
        "product": "NGFW HIP Match",
        "pack_name": "PANW_NGFW",
        "rule_name": "PANW_NGFW",
        "description": "Palo Alto Networks NGFW — Host Information Profile (HIP) match events. HIP profiles assert client posture (AV running, disk encrypted, etc.) and these events fire when a session's client posture matches a HIP profile.",
        "categories": ["Network Security", "Endpoint Posture", "Compliance"],
        "extra_fields": {
            "config_version": ("string", "HIP profile configuration version on the client. Maps to `xdm.source.application.version`.", "1.5.2"),
            "endpoint_device_name": ("string", "Hostname of the endpoint with the HIP profile evaluated.", "bob-thinkpad.corp.example.com"),
            "endpoint_os_type": ("string", "Endpoint OS — space-separated; first token becomes the os_family discriminator (case-insensitive). Recognized: windows, macos/mac, ios/iOS, chromeos, linux, android. Other values pass through.", "Windows 11 Pro"),
            "endpoint_serial_number": ("string", "Hardware serial number of the endpoint. Maps to `xdm.source.host.hardware_uuid`.", "MJ04ABCDEF12"),
            "hip_match_name": ("string", "Name of the matched HIP profile. Maps to `xdm.event.type`.", "Corp-AV-Encrypted-Disk"),
            "host_id": ("string", "Unique host identifier (preferred — used over source_device_mac if present). Maps to `xdm.source.host.device_id`.", "hip-host-abcdef123456"),
            "log_source": ("string", "Log source type. Maps to `xdm.observer.type`.", "panw-hip"),
            "log_source_id": ("string", "Unique log source instance identifier.", "001801000003"),
            "log_source_name": ("string", "Friendly log source name. Maps to `xdm.observer.name`.", "pa-fw-hq-01"),
            "sequence_no": ("integer", "Monotonic event sequence number. Cast to string for `xdm.event.id`.", "111222333"),
            "source_device_mac": ("string", "MAC address — fallback when host_id is null. Routes through both device_id AND mac_addresses if it contains ':'.", "00:50:56:aa:bb:03"),
            "source_ip": ("string", "Source IPv4 address. Maps to `xdm.source.ipv4` directly (no sentinel check in this MR).", "10.5.5.50"),
            "source_ip_v6": ("string", "Source IPv6 address — populates `xdm.source.ipv6` only when contains ':'.", "2001:db8:hip::5"),
            "source_user": ("string", "Source username (often empty for HIP events — HIP is endpoint-keyed). Note: MR doesn't read this field; the user fields come from `source_user_info_name` below.", ""),
            "source_user_info_domain": ("string", "User's AD domain (when User-ID mapping was made). Maps to both `xdm.source.user.domain` AND `xdm.source.identity.domain`.", "corp.example.com"),
            "source_user_info_name": ("string", "Username. Maps to BOTH `xdm.source.user.username` AND `xdm.source.identity.username`.", "bob"),
            "sub_type": ("string", "HIP event subtype. Maps to `xdm.target.application.name` (unusual mapping — HIP profile types are treated as 'applications' for downstream querying).", "hip-match"),
        },
        "mr_notes": "STANDALONE model — does NOT call ngfw_standalone. The `_os_family` extraction takes the FIRST whitespace-delimited token of endpoint_os_type and lowercases it. So 'Windows 11 Pro' → 'windows' → XDM_CONST.OS_FAMILY_WINDOWS.",
    },
}


# ============================================================
# Pack builder
# ============================================================

def build_pack(dataset_name: str, defn: dict[str, Any]) -> dict[str, Any]:
    """Build a single data_source.yaml dict from a dataset definition."""
    # Determine which fields apply
    if dataset_name in ("panw_ngfw_globalprotect_raw", "panw_ngfw_hipmatch_raw"):
        # Standalone datasets — don't inherit ngfw_standalone
        all_fields = defn["extra_fields"]
    else:
        # Chained datasets — inherit ngfw_standalone
        all_fields = {**NGFW_STANDALONE_FIELDS, **defn["extra_fields"]}

    # Build fields[] list, sorted by name
    fields_list = []
    for fname in sorted(all_fields):
        ftype, fdesc, fexample = all_fields[fname]
        fields_list.append({
            "name": fname,
            "type": ftype,
            "description": fdesc,
            "example": fexample,
        })

    # Pack metadata
    pack: dict[str, Any] = {
        "schema_version": 1,
        "id": f"PANW_NGFW_{dataset_name.replace('panw_ngfw_', '').replace('_raw', '').title()}",
        "pack_name": defn["pack_name"],
        "rule_name": defn["rule_name"],
        "dataset_name": dataset_name,
        "vendor": defn["vendor"],
        "product": defn["product"],
        "description": defn["description"],
        "categories": defn["categories"],
        "version": "1.0.0",
        "origin": "manual",
        "author": "phantom-maintainer (PANW NGFW hand-curated)",
        "formats": ["CEF", "SYSLOG"],
        "is_rawlog_only": False,
        "transport_intent": {
            "category": "direct_mapped_cef",
            "wire_format": "CEF over UDP syslog",
            "broker_destination": "udp:<broker-ip>:<dedicated-panw-port>",
            "operator_setup_required": True,
            "notes": (
                "Operator setup REQUIRED: configure a Broker VM Syslog Applet "
                "with vendor=`panw`, product=`ngfw_cef`, on a dedicated port "
                "(commonly 1516 or higher — NOT 514 which is reserved). "
                "Cortex's upstream PANW NGFW Marketplace pack must also be installed "
                "in the tenant — that's what provides the per-log_type INGEST routing "
                "(filter=log_type==`traffic` → panw_ngfw_traffic_raw, etc.). Without "
                "the Cortex pack installed, events land in panw_ngfw_cef_raw catch-all."
            ),
        },
        "broker_routing": {
            "cef_header_vendor": "panw",
            "cef_header_product": "ngfw_cef",
            "resulting_dataset": dataset_name,
            "discriminator_field": "log_type" if dataset_name not in ("panw_ngfw_hipmatch_raw", "panw_ngfw_globalprotect_raw") else "sub_type",
            "discriminator_value": {
                "panw_ngfw_traffic_raw": "traffic",
                "panw_ngfw_threat_raw": "threat",
                "panw_ngfw_url_raw": "url",
                "panw_ngfw_filedata_raw": "file",
                "panw_ngfw_globalprotect_raw": "globalprotect",
                "panw_ngfw_hipmatch_raw": "hipmatch",
            }[dataset_name],
            "source": "hand_curated_per_log_type_inspection",
            "case_sensitivity_note": (
                "CEF header vendor + product are matched case-sensitively by the broker "
                "applet config. PANW NGFW uses lowercase: `panw|ngfw_cef`."
            ),
        },
        "pr_field_whitelist": {
            "note": (
                "PANW NGFW's PR is just the no-hit catch-all (no `| fields` directive). "
                "All fields in the CEF event reach the MR — no whitelist filtering at the PR layer."
            ),
        },
        "mr_anomalies": defn.get("anomalies", []),
        "mr_anomalies_note": "Known quirks in the MR. Honor existing behavior; don't try to 'fix' them in payloads.",
        "marker_field": {
            "cef_field": "session_id",
            "xdm_target": "xdm.event.id" + (" / xdm.session_context_id" if dataset_name not in ("panw_ngfw_hipmatch_raw", "panw_ngfw_globalprotect_raw") else ""),
            "note": (
                "Recommended carrier for E2E saturation testing. Use a unique session_id; "
                "verify XDM landing via `datamodel dataset = " + dataset_name + " | "
                "filter xdm.event.id contains \"<marker>\" | fields xdm.* | limit 1`."
            ),
        },
        "mr_specific_notes": defn["mr_notes"],
        "field_count": len(fields_list),
        "fields": fields_list,
    }
    return pack


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for dataset_name, defn in PANW_NGFW_DATASETS.items():
        pack = build_pack(dataset_name, defn)
        out_dir = OUTPUT_DIR / dataset_name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "data_source.yaml"
        with out_path.open("w") as f:
            yaml.safe_dump(pack, f, sort_keys=False, default_flow_style=False, width=120, allow_unicode=True)
        print(f"  ✓ wrote {out_path} ({pack['field_count']} fields)")
        written += 1
    print(f"\nGenerated {written} PANW NGFW data_source.yaml packs under {OUTPUT_DIR}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
