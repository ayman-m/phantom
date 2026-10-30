"""Exp 3: Kerberoasting sweep via Windows CEF — 15x 4769 (TGS) with RC4 (0x17) against AES256
baseline, spread over 5 service-account SPNs, from one user. Uses the verified 4769 template from
the MicrosoftWindowsEvents how_to_use."""
import json, datetime
from stc_api import call_tool

fields = json.load(open("win_schema_fields.json"))
byname = {f["name"]: f for f in fields}

SID = "S-1-5-21-1004336348-1177238915-682003330-1100"
USER = "ahmed.alharbi"
DEST = "logdest:217fa292-3beb-49fd-ba8b-5cbd9e84341f"
N = 15

SPNS = [
    ("MSSQLSvc/FS-01.stc.local:1433", "S-1-5-21-1004336348-1177238915-682003330-1601"),
    ("HTTP/intranet.stc.local", "S-1-5-21-1004336348-1177238915-682003330-1602"),
    ("CIFS/FS-02.stc.local", "S-1-5-21-1004336348-1177238915-682003330-1603"),
    ("ldap/DC01.stc.local", "S-1-5-21-1004336348-1177238915-682003330-1604"),
    ("TERMSRV/TS-01.stc.local", "S-1-5-21-1004336348-1177238915-682003330-1605"),
]

def msg4769(spn, spn_sid):
    return (
        "A Kerberos service ticket was requested.\n\n"
        "Account Information:\n\tAccount Name:\t\t" + USER + "@STC.LOCAL\n"
        "\tAccount Domain:\t\tSTC.LOCAL\n\tLogon GUID:\t\t{00000000-0000-0000-0000-000000000000}\n\n"
        "Service Information:\n\tService Name:\t\t" + spn + "\n\tService ID:\t\t" + spn_sid + "\n\n"
        "Network Information:\n\tClient Address:\t\t::ffff:10.20.14.11\n\tClient Port:\t\t52431\n\n"
        "Additional Information:\n\tTicket Options:\t\t0x40810000\n"
        "\tTicket Encryption Type:\t0x17\n\tFailure Code:\t\t0x0\n\tTransited Services:\t-"
    )

now = datetime.datetime.now(datetime.timezone.utc)
tc = now.strftime("%Y-%m-%dT%H:%M:%SZ")

WANT = ["time_created", "provider_name", "channel", "event_id", "event_result",
        "activity_id", "computer_name", "host_name", "log_level", "opcode",
        "os_subtype", "process_pid", "process_thread_id", "provider_guid", "record_id",
        "event_data.Domain", "event_data.FQDN", "event_data.IpAddress",
        "event_data.SID", "event_data.SubjectDomainName", "event_data.SubjectUserName",
        "event_data.SubjectUserSid", "event_data.TargetDomainName", "event_data.TargetUserName",
        "event_data.TargetUserSid", "event_data.TicketEncryptionType", "event_data.User",
        "event_data.UserSid", "event_data.WorkstationName",
        "user.domain", "user.identifier", "user.name", "user.type", "message"]
missing = [w for w in WANT if w not in byname]
if missing:
    raise SystemExit("missing schema fields: %s" % missing)

obs = {
    "time_created": [tc],
    "provider_name": ["Microsoft-Windows-Security-Auditing"],
    "channel": ["Security"],
    "event_id": ["4769"],
    "event_result": ["success"],
    "activity_id": ["{7d3a91f2-4c8b-4e21-a6d5-b0c447690001}"],
    "computer_name": ["WS-1001.stc.local"],
    "host_name": ["WS-1001"],
    "log_level": ["Information"],
    "opcode": ["Info"],
    "os_subtype": ["Windows 10 Enterprise"],
    "process_pid": ["488"],
    "process_thread_id": ["6104"],
    "provider_guid": ["{54849625-5478-4994-A5BA-3E3B0328C30D}"],
    "record_id": [str(3900300 + i) for i in range(N)],
    "event_data.Domain": ["STC"],
    "event_data.FQDN": ["WS-1001.stc.local"],
    "event_data.IpAddress": ["10.20.14.11"],
    "event_data.SID": [SID],
    "event_data.SubjectDomainName": ["STC"],
    "event_data.SubjectUserName": [USER],
    "event_data.SubjectUserSid": [SID],
    "event_data.TargetDomainName": ["STC"],
    "event_data.TargetUserName": [USER],
    "event_data.TargetUserSid": [SID],
    "event_data.TicketEncryptionType": ["0x17"],
    "event_data.User": [USER],
    "event_data.UserSid": [SID],
    "event_data.WorkstationName": ["WS-1001"],
    "user.domain": ["STC"],
    "user.identifier": [SID],
    "user.name": [USER],
    "user.type": ["User"],
    "message": [msg4769(s, sid) for s, sid in SPNS],
}

args = {
    "type": "CEF", "vendor": "microsoft", "product": "windows",
    "destination": DEST, "count": N, "interval": 1,
    "duration_seconds": 60, "max_events": N,
    "schema_override": [byname[n] for n in WANT],
    "observables_dict": obs,
}
r = call_tool("xlog.create_data_worker", args, timeout=90)
print("time_created:", tc)
print(json.dumps(r.get("result"), indent=1)[:400])
