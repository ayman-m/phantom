"""Exp 1: FortiGate utm:dns burst shaped like DNS tunneling -> DNS Tunneling / Random-Looking Domain detectors."""
import json, os, random, string, time
from stc_api import call_tool

random.seed()

fields = json.load(open("fgt_schema_fields.json"))
byname = {f["name"]: f for f in fields}

WANT = ["FTNTFGTeventtime", "FTNTFGTduration", "FTNTFGTsubtype", "FTNTFGTeventtype",
        "FTNTFGTlogid", "FTNTFGTlevel", "FTNTFGTvd", "FTNTFGTqname", "FTNTFGTqtype",
        "FTNTFGTqclass", "FTNTFGTipaddr", "src", "spt", "dst", "dpt", "proto",
        "act", "app", "shost", "dhost", "dvchost", "deviceExternalId",
        "cefSeverity", "msg", "externalId", "out", "in"]
schema_override = [byname[n] for n in WANT]

B32 = "abcdefghijklmnopqrstuvwxyz234567"
def b32(n):
    return "".join(random.choice(B32) for _ in range(n))

SRC_HOST = os.environ.get("EXP1_SRC_HOST", "WS-STCE-12")
SRC_IP = os.environ.get("EXP1_SRC_IP", "10.20.63.12")
TUNNEL_DOMAIN = os.environ.get("EXP1_DOMAIN", "t.exfil-tunnel.net")
N = 80
qnames = [f"{b32(random.randint(32,48))}.{b32(random.randint(16,24))}.{TUNNEL_DOMAIN}" for _ in range(N)]

now = int(time.time())
obs = {
    "FTNTFGTeventtime": [str(now) + "000000000"],
    "FTNTFGTduration": ["0"],
    "FTNTFGTsubtype": ["dns-response"],
    "FTNTFGTeventtype": ["dns-response"],
    "FTNTFGTlogid": ["1501054600"],
    "FTNTFGTlevel": ["warning"],
    "FTNTFGTvd": ["root"],
    "FTNTFGTqname": qnames,
    "FTNTFGTqtype": ["TXT"]*6 + ["A"]*3 + ["CNAME"],
    "FTNTFGTqclass": ["IN"],
    "FTNTFGTipaddr": ["203.0.113.53", "203.0.113.54", "203.0.113.55"],
    "src": [SRC_IP],
    "shost": [SRC_HOST],
    "dst": ["203.0.113.53"],
    "dhost": ["dns.exfil-tunnel.net"],
    "dpt": ["53"],
    "proto": ["17"],
    "app": ["DNS"],
    "act": ["pass"],
    "spt": [str(random.randint(49152, 65535)) for _ in range(25)],
    "dvchost": ["FGT-EDGE-01.corp.stc.local"],
    "deviceExternalId": ["FGT60FT19015830"],
    "cefSeverity": ["3"],
    "msg": [f"DNS query for encoded label under {TUNNEL_DOMAIN}"],
    "externalId": [str(random.randint(2000000, 2999999)) for _ in range(4)],
    "out": [str(random.randint(180, 512)) for _ in range(10)],
    "in": [str(random.randint(200, 4000)) for _ in range(10)],
}

args = {
    "type": "CEF",
    "vendor": "Fortinet",
    "product": "Fortigate",
    "destination": "logdest:217fa292-3beb-49fd-ba8b-5cbd9e84341f",
    "count": N,
    "interval": 1,
    "duration_seconds": 120,
    "max_events": N,
    "schema_override": schema_override,
    "observables_dict": obs,
}
r = call_tool("xlog.create_data_worker", args, timeout=90)
print(json.dumps(r, indent=1)[:800])
