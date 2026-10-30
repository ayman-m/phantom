"""Exp 2: Windows 4662 (Directory Service Access, replication GUIDs) via CEF -> 'Possible DCSync from a non domain controller'.

Single worker, 4 identical-shape 4662 events targeting krbtgt, logged by attacker workstation identity
(ahmed.alharbi / WS-1001 / 10.20.14.11 - the identity binding verified in the data-source how_to_use).
Replication GUIDs ride in `message` -> xdm.event.description (the only XDM carrier).
"""
import json, os, time, datetime
from stc_api import call_tool

fields = json.load(open("win_schema_fields.json"))
byname = {f["name"]: f for f in fields}

now = datetime.datetime.now(datetime.timezone.utc)
tc = now.strftime("%Y-%m-%dT%H:%M:%SZ")

SID = os.environ.get("EXP2_SID", "S-1-5-21-1004336348-1177238915-682003330-1100")
USER = os.environ.get("EXP2_USER", "ahmed.alharbi")
HOST = os.environ.get("EXP2_HOST", "WS-1001")
IP = os.environ.get("EXP2_IP", "10.20.14.11")
LOGON = os.environ.get("EXP2_LOGON", "0x1A2B3C")

GUIDS = ("{1131f6aa-9c07-11d1-f79f-00c04fc2dcd2}\n    "
         "{1131f6ad-9c07-11d1-f79f-00c04fc2dcd2}\n    "
         "{1131f6ae-9c07-11d1-f79f-00c04fc2dcd2}\n    "
         "{89e95b76-444d-4c62-991a-0facbeda640c}")
OBJ = "CN=krbtgt,CN=Users,DC=stc,DC=local"

MESSAGE = (
    "An operation was performed on an object.\n\n"
    "Subject :\n"
    f"\tSecurity ID:\t\t{SID}\n"
    f"\tAccount Name:\t\t{USER}\n"
    "\tAccount Domain:\t\tSTC\n"
    f"\tLogon ID:\t\t{LOGON}\n\n"
    "Object:\n"
    "\tObject Server:\t\tDS\n"
    "\tObject Type:\t\t%{bf967aba-0de6-11d0-a285-00aa003049e2}\n"
    f"\tObject Name:\t\t{OBJ}\n"
    "\tHandle ID:\t\t0x0\n\n"
    "Operation:\n"
    "\tOperation Type:\t\tObject Access\n"
    "\tAccess Mask:\t\t0x100\n"
    f"\tProperties:\t\t{GUIDS}\n"
    f"\t\t\t{OBJ}\n\n"
    "Additional Information:\n"
    "\tParameter 1:\t\t-\n"
    "\tParameter 2:\t\t-"
)

WANT = ["time_created", "provider_name", "channel", "event_id", "event_result",
        "activity_id", "computer_name", "host_name", "log_level", "opcode",
        "os_subtype", "process_pid", "process_thread_id", "provider_guid", "record_id",
        "event_data.Domain", "event_data.FQDN", "event_data.IpAddress",
        "event_data.SID", "event_data.SubjectDomainName", "event_data.SubjectUserName",
        "event_data.SubjectUserSid", "user.domain", "user.identifier", "user.name", "user.type",
        "AccessMask", "ObjectName", "ObjectType", "message"]
missing = [w for w in WANT if w not in byname]
if missing:
    raise SystemExit("missing schema fields: %s" % missing)
schema_override = [byname[n] for n in WANT]

obs = {
    "time_created": [tc],
    "provider_name": ["Microsoft-Windows-Security-Auditing"],
    "channel": ["Security"],
    "event_id": ["4662"],
    "event_result": ["success"],
    "activity_id": ["{7d3a91f2-4c8b-4e21-a6d5-dcsync46620001}".replace("dcsync", "b0c4")],
    "computer_name": [HOST + ".stc.local"],
    "host_name": [HOST],
    "log_level": ["Information"],
    "opcode": ["Info"],
    "os_subtype": ["Windows 10 Enterprise"],
    "process_pid": ["488"],
    "process_thread_id": ["6104"],
    "provider_guid": ["{54849625-5478-4994-A5BA-3E3B0328C30D}"],
    "record_id": [str(3900100 + i) for i in range(4)],
    "event_data.Domain": ["STC"],
    "event_data.FQDN": [HOST + ".stc.local"],
    "event_data.IpAddress": [IP],
    "event_data.SID": [SID],
    "event_data.SubjectDomainName": ["STC"],
    "event_data.SubjectUserName": [USER],
    "event_data.SubjectUserSid": [SID],
    "user.domain": ["STC"],
    "user.identifier": [SID],
    "user.name": [USER],
    "user.type": ["User"],
    "AccessMask": ["0x100"],
    "ObjectName": [OBJ],
    "ObjectType": ["%{bf967aba-0de6-11d0-a285-00aa003049e2}"],
    "message": [MESSAGE],
}

args = {
    "type": "CEF",
    "vendor": "microsoft",
    "product": "windows",
    "destination": "logdest:217fa292-3beb-49fd-ba8b-5cbd9e84341f",
    "count": 4,
    "interval": 1,
    "duration_seconds": 30,
    "max_events": 4,
    "schema_override": schema_override,
    "observables_dict": obs,
}
r = call_tool("xlog.create_data_worker", args, timeout=90)
print("time_created:", tc)
print(json.dumps(r, indent=1)[:600])
