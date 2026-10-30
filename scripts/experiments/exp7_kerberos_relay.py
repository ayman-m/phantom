"""Exp 7: Kerberos/NTLM relay pattern via CEF syslog -> 'Possible Kerberos relay attack' (ungated WEC detector).

Two-step test step 1 (research doc 8.1): fire the pattern over the existing microsoft/windows
syslog route first. If it alerts, transport doesn't matter for this detector; if not, the same
payload goes over WEC once wec-sender gains a threat scenario.

Pattern (per detector description "suspicious local network login"): 4624 LogonType 3,
AuthenticationPackageName NTLM, where the source IpAddress/WorkstationName IS the target host
itself (a relayed logon loops back onto the originating server).
"""
import json, os, datetime, sys
sys.path.insert(0, os.path.expanduser("~/Documents/Phantom"))
from stc_api import call_tool

fields = json.load(open(os.path.expanduser("~/Documents/Phantom/win_schema_fields.json")))
byname = {f["name"]: f for f in fields}

now = datetime.datetime.now(datetime.timezone.utc)
tc = now.strftime("%Y-%m-%dT%H:%M:%SZ")

# Target host: the file server already present in the tenant's WEC baseline traffic
HOST = os.environ.get("EXP7_HOST", "PHSRV-FS01")
FQDN = HOST + ".phantom.lab"
HOST_IP = os.environ.get("EXP7_HOST_IP", "10.20.16.10")
DOMAIN = "PHANTOM"
USERS = ["svc.backup", "adm.khalid", "m.alsaeed", "j.tan"]

WANT = ["time_created", "provider_name", "channel", "event_id", "event_result",
        "activity_id", "computer_name", "host_name", "log_level", "opcode",
        "os_subtype", "process_pid", "process_thread_id", "provider_guid", "record_id",
        "event_data.Domain", "event_data.FQDN", "event_data.IpAddress",
        "event_data.SID", "event_data.SubjectDomainName", "event_data.SubjectUserName",
        "event_data.SubjectUserSid", "user.domain", "user.identifier", "user.name", "user.type",
        "message",
        "event_data.TargetUserName", "event_data.TargetDomainName", "TargetLogonId",
        "event_data.LogonType", "event_data.LogonProcessName",
        "event_data.AuthenticationPackageName", "event_data.WorkstationName",
        "event_data.IpPort"]
missing = [w for w in WANT if w not in byname]
if missing:
    raise SystemExit("missing schema fields: %s" % missing)
schema_override = [byname[n] for n in WANT]

N = len(USERS) * 3  # 3 relayed logons per user

def message_for(user, logon_id):
    return (
        "An account was successfully logged on.\n\n"
        "Subject:\n"
        "\tSecurity ID:\t\tS-1-5-18\n"
        f"\tAccount Name:\t\t{HOST}$\n"
        f"\tAccount Domain:\t\t{DOMAIN}\n"
        "\tLogon ID:\t\t0x3E7\n\n"
        "New Logon:\n"
        "\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-3201\n"
        f"\tAccount Name:\t\t{user}\n"
        f"\tAccount Domain:\t\t{DOMAIN}\n"
        f"\tLogon ID:\t\t{logon_id}\n\n"
        "Network Information:\n"
        f"\tWorkstation Name:\t{HOST}\n"
        f"\tSource Network Address:\t{HOST_IP}\n"
        "\tSource Port:\t\t49871\n\n"
        "Detailed Authentication Information:\n"
        "\tLogon Process:\t\tNtLmSsp\n"
        "\tAuthentication Package:\tNTLM\n"
        "\tTransited Services:\t-\n"
        "\tPackage Name (NTLM only):\tNTLM V2\n"
        "\tKey Length:\t\t128"
    )

obs = {
    "time_created": [tc],
    "provider_name": ["Microsoft-Windows-Security-Auditing"],
    "channel": ["Security"],
    "event_id": ["4624"],
    "event_result": ["success"],
    "activity_id": ["{9f1c2a7e-relay-4624-aabb-ccdd%06d}" % i for i in range(N)],
    "computer_name": [FQDN],
    "host_name": [HOST],
    "log_level": ["Information"],
    "opcode": ["Info"],
    "os_subtype": ["Windows Server 2022"],
    "process_pid": ["694"],
    "process_thread_id": ["2748"],
    "provider_guid": ["{54849625-5478-4994-A5BA-3E3B0328C30D}"],
    "record_id": [str(238200000 + i) for i in range(N)],
    "event_data.Domain": [DOMAIN],
    "event_data.FQDN": [FQDN],
    # the relay signature: source address is the target host itself
    "event_data.IpAddress": [HOST_IP],
    "event_data.IpPort": [str(49000 + i) for i in range(N)],
    "event_data.SID": ["S-1-5-18"],
    "event_data.SubjectDomainName": [DOMAIN],
    "event_data.SubjectUserName": [HOST + "$"],
    "event_data.SubjectUserSid": ["S-1-5-18"],
    "user.domain": [DOMAIN],
    "user.identifier": ["S-1-5-21-3623811015-3361044348-30300820-3201"],
    "user.name": [USERS[i % len(USERS)] for i in range(N)],
    "user.type": ["user"],
    "event_data.TargetUserName": [USERS[i % len(USERS)] for i in range(N)],
    "event_data.TargetDomainName": [DOMAIN],
    "TargetLogonId": ["0x%x" % (0x9A0000 + i * 0x111) for i in range(N)],
    "event_data.LogonType": ["3"],
    "event_data.LogonProcessName": ["NtLmSsp"],
    "event_data.AuthenticationPackageName": ["NTLM"],
    "event_data.WorkstationName": [HOST],
    "message": [message_for(USERS[i % len(USERS)], "0x%x" % (0x9A0000 + i * 0x111)) for i in range(N)],
}

r = call_tool("xlog.create_data_worker", {
    "type": "CEF",
    "vendor": "microsoft",
    "product": "windows",
    "destination": "logdest:217fa292-3beb-49fd-ba8b-5cbd9e84341f",
    "count": N,
    "interval": 5,
    "duration_seconds": N * 5 + 30,
    "max_events": N,
    "schema_override": schema_override,
    "observables_dict": obs,
}, timeout=120)
print(json.dumps(r)[:500])
