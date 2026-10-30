"""Exp 4: AD admin-group enumeration via LDAP search — Windows 1644 via CEF.

Verified recipe from the MicrosoftWindowsEvents how_to_use: provider_name
Microsoft-Windows-ActiveDirectory_DomainService, channel OMITTED (model gate clears on provider),
numbered params, filter swept across admin groups from ONE client -> administrator-groups-
enumerated-via-ldap (ungated, Test Period: N/A — single event, T1087).
"""
import json, datetime
from stc_api import call_tool

fields = json.load(open("win_schema_fields.json"))
byname = {f["name"]: f for f in fields}

DEST = "logdest:217fa292-3beb-49fd-ba8b-5cbd9e84341f"
ACTOR = "STC\\ahmed.alharbi"
CLIENT = "10.20.14.11:59300"
BASE_DN = "DC=stc,DC=local"
FILTERS = [
    " (&(objectClass=group)(cn=Domain Admins))",
    " (&(objectClass=group)(cn=Enterprise Admins))",
    " (&(objectClass=group)(cn=Schema Admins))",
    " (&(objectClass=group)(cn=Administrators))",
    " (&(objectClass=user)(adminCount=1))",
]
ATTRS = "member,sAMAccountName,objectSid,adminCount,memberOf,distinguishedName"

def msg1644(filt):
    return (
        "Internal event: A client issued a search operation with the following options. \n \n "
        "Client:\n" + CLIENT + " \nStarting node:\n" + BASE_DN + " \nFilter:\n" + filt +
        " \nSearch scope:\n subtree \nAttribute selection:\n" + ATTRS +
        " \nServer controls:\n \nVisibility of deleted objects:\n0 \nSearch flags:\n0 \n"
        "Attributes read:\n14 \nSearch time (ms):\n7 \nUser:\n" + ACTOR + " \n"
    )

now = datetime.datetime.now(datetime.timezone.utc)
tc = now.strftime("%Y-%m-%dT%H:%M:%SZ")

WANT = ["time_created", "provider_name", "event_id", "event_result",
        "activity_id", "computer_name", "host_name", "log_level", "opcode",
        "os_subtype", "provider_guid", "record_id",
        "event_data.param1", "event_data.param2", "event_data.param3", "event_data.param4",
        "event_data.param5", "event_data.param6", "event_data.param7", "event_data.param9",
        "event_data.param17", "message"]
missing = [w for w in WANT if w not in byname]
if missing:
    raise SystemExit("missing schema fields: %s" % missing)

obs = {
    "time_created": [tc],
    "provider_name": ["Microsoft-Windows-ActiveDirectory_DomainService"],
    "event_id": ["1644"],
    "event_result": ["success"],
    "activity_id": ["{7d3a91f2-4c8b-4e21-a6d5-b0c416440001}"],
    "computer_name": ["DC01.stc.local"],
    "host_name": ["DC01"],
    "log_level": ["Information"],
    "opcode": ["Info"],
    "os_subtype": ["Windows Server 2022"],
    "provider_guid": ["{54849625-5478-4994-A5BA-3E3B0328C30D}"],
    "record_id": [str(3900400 + i) for i in range(len(FILTERS))],
    "event_data.param1": [BASE_DN],
    "event_data.param2": FILTERS,
    "event_data.param3": ["0"],
    "event_data.param4": ["0"],
    "event_data.param5": [CLIENT],
    "event_data.param6": ["subtree"],
    "event_data.param7": [ATTRS],
    "event_data.param9": ["idx_objectClass:0:N;"],
    "event_data.param17": [ACTOR],
    "message": [msg1644(f) for f in FILTERS],
}

args = {
    "type": "CEF", "vendor": "microsoft", "product": "windows",
    "destination": DEST, "count": len(FILTERS), "interval": 1,
    "duration_seconds": 30, "max_events": len(FILTERS),
    "schema_override": [byname[n] for n in WANT],
    "observables_dict": obs,
}
r = call_tool("xlog.create_data_worker", args, timeout=90)
print("time_created:", tc)
print(json.dumps(r.get("result"), indent=1)[:400])
