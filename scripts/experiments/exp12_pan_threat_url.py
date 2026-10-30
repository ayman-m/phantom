"""Exp 12: ungated PAN threat + URL detectors; also seeds the two empty datasets.

Targets (catalog, module-free):
  URL   - Non-browser access to a pastebin-like site (Low, single)
        - PowerShell Initiates a Network Connection to GitHub (Low, single)
        - A non-browser process accessed a website UI (Info, single)
        - Uncommon network tunnel creation (Info, single)
        - Rare connection by app using RMI-IIOP or LDAP (Info, single)
  THREAT- Analytics enhanced NGFW Rare Internal Firewall Vulnerability Threat Alert (Info, single)

CEF route per bundle how_to_use: vendor `panw`, product `ngfw_threat` / `ngfw_url`
(never `ngfw_cef` — that catch-all drops non-matching events).
"""
import json, os, sys
sys.path.insert(0, os.path.expanduser("~/Documents/Phantom"))
from stc_api import call_tool

DEST = "logdest:217fa292-3beb-49fd-ba8b-5cbd9e84341f"

URL_SCHEMA = [{"name": n, "type": t} for n, t in [
    ("action", "string"), ("app", "string"), ("dest_ip", "ipv4"), ("dest_port", "integer"),
    ("protocol", "string"), ("source_device_host", "string"), ("source_ip", "ipv4"),
    ("source_port", "integer"), ("source_user", "string"), ("log_type", "string"),
    ("sub_type", "string"), ("rule_matched", "string"), ("from_zone", "string"),
    ("to_zone", "string"), ("session_id", "integer"), ("uri", "string"),
    ("url_domain", "string"), ("url_category", "string"), ("user_agent", "string"),
    ("http_method", "string"), ("content_type", "string"), ("referer", "string")]]

THREAT_SCHEMA = [{"name": n, "type": t} for n, t in [
    ("action", "string"), ("app", "string"), ("dest_ip", "ipv4"), ("dest_port", "integer"),
    ("protocol", "string"), ("source_device_host", "string"), ("source_ip", "ipv4"),
    ("source_port", "integer"), ("source_user", "string"), ("log_type", "string"),
    ("sub_type", "string"), ("rule_matched", "string"), ("from_zone", "string"),
    ("to_zone", "string"), ("session_id", "integer"), ("severity", "string"),
    ("threat_category", "string"), ("threat_id", "string"), ("threat_name", "string"),
    ("verdict", "string"), ("url_domain", "string"), ("file_name", "string"),
    ("file_sha_256", "string"), ("file_type", "string")]]

def url_obs(**over):
    obs = {
        "log_type": ["URL"], "protocol": ["tcp"], "action": ["allow"],
        "rule_matched": ["allow-outbound"], "from_zone": ["trust"], "to_zone": ["untrust"],
        "source_port": ["51000"], "dest_port": ["443"], "app": ["web-browsing"],
        "http_method": ["GET"], "content_type": ["text/html"], "referer": ["-"],
        "session_id": [str(800000 + i) for i in range(32)],
        "sub_type": ["end"],
    }
    obs.update(over)
    return obs

def threat_obs(**over):
    obs = {
        "log_type": ["THREAT"], "protocol": ["tcp"], "action": ["alert"],
        "rule_matched": ["allow-internal"], "from_zone": ["trust"], "to_zone": ["trust"],
        "source_port": ["51000"], "session_id": [str(810000 + i) for i in range(32)],
        "verdict": ["-"], "file_name": ["-"], "file_sha_256": ["-"], "file_type": ["-"],
    }
    obs.update(over)
    return obs

WORKERS = [
    # --- URL detectors ---
    ("exp12-pastebin-nonbrowser", "ngfw_url", 3, 5, url_obs(
        source_ip=["10.20.63.15"], source_device_host=["WS-STCE-15"],
        source_user=["stc\\r.alshammari"], dest_ip=["104.20.1.85"],
        url_domain=["pastebin.com"], uri=["https://pastebin.com/raw/Ab3dEf9h"],
        url_category=["questionable"], user_agent=["curl/8.4.0", "python-requests/2.31.0"])),
    ("exp12-powershell-github", "ngfw_url", 3, 5, url_obs(
        source_ip=["10.20.63.16"], source_device_host=["WS-STCE-16"],
        source_user=["stc\\n.almutairi"], dest_ip=["140.82.112.3"],
        url_domain=["raw.githubusercontent.com"],
        uri=["https://raw.githubusercontent.com/tools/payloads/main/invoke.ps1"],
        url_category=["computer-and-internet-info"],
        user_agent=["Microsoft-PowerShell/7.4.6", "PowerShell/5.1"])),
    ("exp12-nonbrowser-webui", "ngfw_url", 3, 5, url_obs(
        source_ip=["10.20.63.17"], source_device_host=["WS-STCE-17"],
        source_user=["stc\\h.aldossari"], dest_ip=["151.101.1.69"],
        url_domain=["jenkins.corp-vendor.example.com"],
        uri=["https://jenkins.corp-vendor.example.com/login"],
        url_category=["web-hosting"], user_agent=["Wget/1.21.4"])),
    ("exp12-tunnel-creation", "ngfw_url", 3, 5, url_obs(
        source_ip=["10.20.63.18"], source_device_host=["WS-STCE-18"],
        source_user=["stc\\l.alanazi"], dest_ip=["45.137.155.20"],
        url_domain=["node74.psiphon3.net"], uri=["https://node74.psiphon3.net/tunnel"],
        url_category=["proxy-avoidance-and-anonymizers"], app=["psiphon"],
        user_agent=["Psiphon/3.0"])),
    ("exp12-rmi-ldap-external", "ngfw_url", 2, 5, url_obs(
        source_ip=["10.20.63.19"], source_device_host=["WS-STCE-19"],
        source_user=["stc\\svc.repl"], dest_ip=["193.29.15.120"],
        dest_port=["1099", "389"], app=["java-rmi", "ldap"],
        url_domain=["193.29.15.120"], uri=["-"], url_category=["unknown"],
        user_agent=["-"])),
    # --- THREAT detector: internal host triggers vulnerability threat on another internal host ---
    ("exp12-internal-vuln-threat", "ngfw_threat", 3, 5, threat_obs(
        source_ip=["10.20.63.14"], source_device_host=["WS-STCE-14"],
        source_user=["stc\\f.alqahtani"], dest_ip=["10.20.30.25"], dest_port=["445"],
        app=["smb"], sub_type=["vulnerability"], severity=["high"],
        threat_category=["code-execution"], threat_id=["95412"],
        threat_name=["Microsoft SMB Server Remote Code Execution Vulnerability"],
        url_domain=["-"])),
]

for name, product, count, interval, obs in WORKERS:
    schema = URL_SCHEMA if product == "ngfw_url" else THREAT_SCHEMA
    r = call_tool("xlog.create_data_worker", {
        "type": "CEF", "vendor": "panw", "product": product,
        "destination": DEST, "name": name, "tags": ["experiment", "exp12"],
        "count": count, "interval": interval,
        "duration_seconds": count * interval + 30, "max_events": count,
        "schema_override": schema, "observables_dict": obs,
    }, timeout=120)
    res = r["result"][0] if isinstance(r.get("result"), list) else r.get("result")
    print(f'{name:26s} {product:11s} worker={res.get("worker")} status={res.get("status")}')
