"""Exp 13: port-scan canary + deep multi-stage attack story.

Canary: the historically-proven Port Scan shape (FortiGate, 150 events, privileged ports),
on FRESH hosts to dodge the 1-day dedup.

Story persona (all stages): foothold WS-STCE-21 / 10.20.63.21 / stc\\k.alsayed
(WEC side: PHWS-021.phantom.lab / k.alsayed@phantom.lab).
Stages overlap like a real intrusion: beacon -> recon sweep -> lateral -> exfil,
plus slow-burn spam-bot job (3-day window).
"""
import json, os, sys
sys.path.insert(0, os.path.expanduser("~/Documents/Phantom"))
from stc_api import call_tool

DEST = "logdest:217fa292-3beb-49fd-ba8b-5cbd9e84341f"
PAN_SCHEMA = [{"name": n, "type": t} for n, t in [
    ("action", "string"), ("app", "string"), ("dest_ip", "ipv4"), ("dest_port", "integer"),
    ("protocol", "string"), ("source_device_host", "string"), ("source_ip", "ipv4"),
    ("source_port", "integer"), ("source_user", "string"), ("bytes_sent", "integer"),
    ("bytes_received", "integer"), ("log_type", "string"), ("sub_type", "string"),
    ("rule_matched", "string"), ("from_zone", "string"), ("to_zone", "string"),
    ("packets_sent", "integer"), ("packets_received", "integer"),
    ("total_time_elapsed", "integer"), ("session_id", "integer")]]

def pan_obs(**over):
    obs = {
        "log_type": ["TRAFFIC"], "sub_type": ["end"], "protocol": ["tcp"],
        "action": ["allow"], "rule_matched": ["allow-internal"],
        "from_zone": ["trust"], "to_zone": ["trust"],
        "source_port": ["51000", "52000", "53000"],
        "bytes_sent": ["2400", "9600"], "bytes_received": ["48000", "180000"],
        "packets_sent": ["30", "120"], "packets_received": ["45", "200"],
        "total_time_elapsed": ["3", "12", "45"],
        "session_id": [str(900000 + i) for i in range(200)],
    }
    obs.update(over)
    return obs

def worker(name, vendor, product, count, interval, obs, schema=None, extra=None):
    args = {"type": "CEF", "vendor": vendor, "product": product, "destination": DEST,
            "name": name, "tags": ["experiment", "exp13"], "count": count,
            "interval": interval, "observables_dict": obs}
    if schema is None and product.startswith("ngfw"): schema = PAN_SCHEMA
    if schema: args["schema_override"] = schema
    if extra: args.update(extra)
    r = call_tool("xlog.create_data_worker", args, timeout=120)
    res = r["result"][0] if isinstance(r.get("result"), list) else {}
    if not isinstance(res, dict):
        print(f'{name:28s} ERROR {str(r.get("result"))[:200]}')
        return
    print(f'{name:28s} {res.get("worker")} {res.get("status")} n={res.get("count")}')

# ---------- 1. CANARY: port scan, proven shape, fresh hosts (already fired 2x; CANARY=1 to refire)
for label, src in ([("ext", "192.0.2.99"), ("int", "10.20.63.99")] if os.environ.get("CANARY") == "1" else []):
    worker(f"exp13-canary-portscan-{label}", "Fortinet", "FortiGate", 150, 1, {
        "sourceIp": [src],
        "destinationIp": ["10.10.30.1", "10.10.30.5", "10.10.30.10",
                          "10.10.30.20", "10.10.30.42", "10.10.30.50"],
        "destinationPort": ["22", "23", "80", "135", "443", "445", "1433", "3389", "8080"],
        "protocol": ["tcp"], "action": ["deny", "deny", "deny", "allow"],
        "tcpFlags": ["SYN", "RST"], "threatScore": ["35", "60"]})

# ---------- 2. STORY STAGES (panw traffic) --------------------------------------
ATK_IP, ATK_HOST, ATK_USER = "10.20.63.21", "WS-STCE-21", "stc\\k.alsayed"

# Stage 1: C2 beacon — same rare external IP, 60 s heartbeat, uniform small bytes, 90 min
worker("exp13-c2-beacon", "panw", "ngfw_traffic", 90, 60, pan_obs(
    source_ip=[ATK_IP], source_device_host=[ATK_HOST], source_user=[ATK_USER],
    dest_ip=["45.155.204.99"], dest_port=["443"], app=["ssl"],
    to_zone=["untrust"], rule_matched=["allow-outbound"],
    bytes_sent=["312"], bytes_received=["1024"],
    packets_sent=["4"], packets_received=["6"], total_time_elapsed=["1"]), schema=PAN_SCHEMA)

# Stage 2: internal recon sweep — 50 hosts, privileged ports, 12 min
worker("exp13-recon-sweep", "panw", "ngfw_traffic", 100, 7, pan_obs(
    source_ip=[ATK_IP], source_device_host=[ATK_HOST], source_user=[ATK_USER],
    dest_ip=["10.20.30.%d" % i for i in range(1, 51)],
    dest_port=["445", "3389", "22", "135", "5985"],
    app=["smb", "ms-rdp", "ssh", "ms-rpc", "winrm"]), schema=PAN_SCHEMA)

# Stage 3: lateral movement — SMB/RDP onto servers and the DC, 45 min
worker("exp13-lateral", "panw", "ngfw_traffic", 30, 90, pan_obs(
    source_ip=[ATK_IP], source_device_host=[ATK_HOST], source_user=[ATK_USER],
    dest_ip=["10.20.0.10", "10.20.0.20", "10.20.30.25", "10.20.30.30"],
    dest_port=["445", "3389"], app=["smb", "ms-rdp"],
    bytes_sent=["45000", "120000"], bytes_received=["380000", "920000"],
    total_time_elapsed=["300", "900"]), schema=PAN_SCHEMA)

# Stage 4: exfil — 2.5 GB HTTPS out over 60 min + DNS-tunnel-shaped queries to odd resolver
worker("exp13-exfil-https", "panw", "ngfw_traffic", 24, 150, pan_obs(
    source_ip=[ATK_IP], source_device_host=[ATK_HOST], source_user=[ATK_USER],
    dest_ip=["104.18.32.7"], dest_port=["443"], app=["ssl", "web-browsing"],
    to_zone=["untrust"], rule_matched=["allow-outbound"],
    bytes_sent=[str(100_000_000 + i * 2_000_000) for i in range(24)],
    bytes_received=["15000"], packets_sent=["90000"], packets_received=["9000"],
    total_time_elapsed=["2400"]), schema=PAN_SCHEMA)
worker("exp13-exfil-dns", "panw", "ngfw_traffic", 30, 60, pan_obs(
    source_ip=[ATK_IP], source_device_host=[ATK_HOST], source_user=[ATK_USER],
    dest_ip=["198.51.100.53"], dest_port=["53"], app=["dns"], protocol=["udp"],
    to_zone=["untrust"], rule_matched=["allow-outbound"],
    bytes_sent=["512"], bytes_received=["240"], total_time_elapsed=["1"]), schema=PAN_SCHEMA)
