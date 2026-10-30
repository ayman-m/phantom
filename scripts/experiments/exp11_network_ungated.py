"""Exp 11: ungated network analytics detectors via panw/ngfw_traffic (no CIE needed).

From docs/research/analytics-detector-catalog-2026-09-30.json, module="" detectors bound to
PAN traffic / third-party-firewall sources. One worker per detector pattern; the recipe shape
copies the live baseline jobs (baseline-atkpool-internal, daily-engineering-pan-traffic).
"""
import json, os, sys
sys.path.insert(0, os.path.expanduser("~/Documents/Phantom"))
from stc_api import call_tool

DEST = "logdest:217fa292-3beb-49fd-ba8b-5cbd9e84341f"
SCHEMA = [{"name": n, "type": t} for n, t in [
    ("action", "string"), ("app", "string"), ("dest_ip", "ipv4"), ("dest_port", "integer"),
    ("protocol", "string"), ("source_device_host", "string"), ("source_ip", "ipv4"),
    ("source_port", "integer"), ("source_user", "string"), ("bytes_sent", "integer"),
    ("bytes_received", "integer"), ("log_type", "string"), ("sub_type", "string"),
    ("rule_matched", "string"), ("from_zone", "string"), ("to_zone", "string"),
    ("packets_sent", "integer"), ("packets_received", "integer"),
    ("total_time_elapsed", "integer"), ("session_id", "integer")]]

def base_obs(**over):
    obs = {
        "log_type": ["TRAFFIC"], "sub_type": ["end"], "protocol": ["tcp"],
        "action": ["allow"], "rule_matched": ["allow-outbound"],
        "from_zone": ["trust"], "to_zone": ["untrust"],
        "source_port": ["51000", "52000", "53000"],
        "bytes_sent": ["2400", "9600"], "bytes_received": ["48000", "180000"],
        "packets_sent": ["30", "120"], "packets_received": ["45", "200"],
        "total_time_elapsed": ["3", "12", "45"],
        "session_id": [str(700000 + i) for i in range(64)],
    }
    obs.update(over)
    return obs

WORKERS = [
    # Port Sweep (Info, 1h): one host -> 40 hosts on one privileged port
    ("exp11-port-sweep", 40, 2, base_obs(
        source_ip=["10.20.63.14"], source_device_host=["WS-STCE-14"],
        source_user=["stc\\f.alqahtani"],
        dest_ip=["10.20.30.%d" % i for i in range(1, 41)],
        dest_port=["445"], app=["smb"], to_zone=["trust"], rule_matched=["allow-internal"])),
    # Suspicious SMB connection from domain controller (Low, single event)
    ("exp11-smb-from-dc", 3, 5, base_obs(
        source_ip=["10.20.0.10"], source_device_host=["PHDC01"],
        source_user=["stc\\adm.malwadi"], dest_ip=["10.20.63.14"],
        dest_port=["445"], app=["smb"], to_zone=["trust"], rule_matched=["allow-internal"])),
    # A Torrent client was detected (Info, single event)
    ("exp11-torrent", 3, 5, base_obs(
        source_ip=["10.20.63.15"], source_device_host=["WS-STCE-15"],
        source_user=["stc\\r.alshammari"], dest_ip=["185.220.101.4", "185.220.101.9"],
        dest_port=["6881", "6889"], app=["bittorrent"])),
    # New FTP Server (Low, single event): untrust -> internal host on 21
    ("exp11-new-ftp-server", 3, 5, base_obs(
        source_ip=["203.0.113.77"], source_device_host=["ext-scanner"],
        source_user=["-"], dest_ip=["10.20.63.20"], dest_port=["21"],
        app=["ftp"], from_zone=["untrust"], to_zone=["trust"], rule_matched=["allow-inbound"])),
    # Large Upload HTTPS (Low, 1d): ~500 MB per session, 8 sessions
    ("exp11-large-upload", 8, 10, base_obs(
        source_ip=["10.20.63.16"], source_device_host=["WS-STCE-16"],
        source_user=["stc\\n.almutairi"], dest_ip=["104.18.32.7"],
        dest_port=["443"], app=["ssl", "web-browsing"],
        bytes_sent=[str(500_000_000 + i * 10_000_000) for i in range(8)],
        bytes_received=["12000"], packets_sent=["400000"], packets_received=["8000"],
        total_time_elapsed=["1800"])),
    # Uncommon SSH session (Low, single event)
    ("exp11-uncommon-ssh", 2, 5, base_obs(
        source_ip=["10.20.63.17"], source_device_host=["WS-STCE-17"],
        source_user=["stc\\h.aldossari"], dest_ip=["194.165.16.5"],
        dest_port=["22"], app=["ssh"])),
    # Weakly-Encrypted Kerberos (single + 10-min multiple): kerberos app burst to DC
    ("exp11-weak-kerberos", 12, 5, base_obs(
        source_ip=["10.20.63.18"], source_device_host=["WS-STCE-18"],
        source_user=["stc\\l.alanazi"], dest_ip=["10.20.0.10"],
        dest_port=["88"], app=["kerberos"], to_zone=["trust"], rule_matched=["allow-internal"])),
    # Possible DCSync from a non domain controller (Low, single): DRSUAPI to the DC
    ("exp11-dcsync-net", 4, 5, base_obs(
        source_ip=["10.20.63.19"], source_device_host=["WS-STCE-19"],
        source_user=["stc\\svc.repl"], dest_ip=["10.20.0.10"],
        dest_port=["135", "49666"], app=["ms-drsuapi", "ms-rpc"],
        to_zone=["trust"], rule_matched=["allow-internal"])),
]

for name, count, interval, obs in WORKERS:
    r = call_tool("xlog.create_data_worker", {
        "type": "CEF", "vendor": "panw", "product": "ngfw_traffic",
        "destination": DEST, "name": name, "tags": ["experiment", "exp11"],
        "count": count, "interval": interval,
        "duration_seconds": count * interval + 30, "max_events": count,
        "schema_override": SCHEMA, "observables_dict": obs,
    }, timeout=120)
    res = r["result"][0] if isinstance(r.get("result"), list) else r.get("result")
    print(f'{name:24s} worker={res.get("worker")} status={res.get("status")} count={res.get("count")}')
