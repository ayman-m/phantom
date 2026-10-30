"""Exp 2 v2: DCSync full attack story via Windows CEF.

Fires the DCSync event sequence around the 4662s: 4624 (elevated network logon) -> 4672 (special
privileges) -> 4688 (mimikatz lsadump::dcsync process creation), all sharing Logon ID 0x1A2B3C
and the identity ahmed.alharbi / WS-1001 / {IP} / SID ...-1100 (verified binding from the
MicrosoftWindowsEvents how_to_use). Run exp2_dcsync.py right after this for the 4662 tail.
"""
import json, os, datetime, time
from stc_api import call_tool

fields = json.load(open("win_schema_fields.json"))
byname = {f["name"]: f for f in fields}

SID = os.environ.get("EXP2_SID", "S-1-5-21-1004336348-1177238915-682003330-1100")
USER = os.environ.get("EXP2_USER", "ahmed.alharbi")
HOST = os.environ.get("EXP2_HOST", "WS-1001")
IP = os.environ.get("EXP2_IP", "10.20.14.11")
LOGON = os.environ.get("EXP2_LOGON", "0x1A2B3C")
DEST = "logdest:217fa292-3beb-49fd-ba8b-5cbd9e84341f"

BASE_FIELDS = ["time_created", "provider_name", "channel", "event_id", "event_result",
               "activity_id", "computer_name", "host_name", "log_level", "opcode",
               "os_subtype", "process_pid", "process_thread_id", "provider_guid", "record_id",
               "event_data.Domain", "event_data.FQDN", "event_data.IpAddress",
               "event_data.SID", "event_data.SubjectDomainName", "event_data.SubjectUserName",
               "event_data.SubjectUserSid", "user.domain", "user.identifier", "user.name",
               "user.type", "message"]

def base_obs(tc, event_id, record_id, activity):
    return {
        "time_created": [tc],
        "provider_name": ["Microsoft-Windows-Security-Auditing"],
        "channel": ["Security"],
        "event_id": [event_id],
        "event_result": ["success"],
        "activity_id": [activity],
        "computer_name": [HOST + ".stc.local"],
        "host_name": [HOST],
        "log_level": ["Information"],
        "opcode": ["Info"],
        "os_subtype": ["Windows 10 Enterprise"],
        "process_pid": ["488"],
        "process_thread_id": ["6104"],
        "provider_guid": ["{54849625-5478-4994-A5BA-3E3B0328C30D}"],
        "record_id": [str(record_id)],
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
    }

def fire(tag, extra_fields, obs):
    names = BASE_FIELDS + [f for f in extra_fields if f not in BASE_FIELDS]
    missing = [n for n in names if n not in byname]
    if missing:
        raise SystemExit(f"{tag}: missing schema fields {missing}")
    args = {
        "type": "CEF", "vendor": "microsoft", "product": "windows",
        "destination": DEST, "count": 1, "interval": 1,
        "duration_seconds": 20, "max_events": 1,
        "schema_override": [byname[n] for n in names],
        "observables_dict": obs,
    }
    r = call_tool("xlog.create_data_worker", args, timeout=90)
    w = (r.get("result") or [{}])[0]
    print(tag, "->", w.get("worker"), w.get("status"))

now = datetime.datetime.now(datetime.timezone.utc)

# --- 1. 4624 elevated network logon (LogonType 3, the DCSync operator's session) ---
tc = now.strftime("%Y-%m-%dT%H:%M:%SZ")
msg4624 = (
    "An account was successfully logged on.\n\n"
    "Subject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\t" + HOST + "$\n"
    "\tAccount Domain:\t\tSTC\n\tLogon ID:\t\t0x3E7\n\n"
    "Logon Information:\n\tLogon Type:\t\t3\n\tRestricted Admin Mode:\t-\n"
    "\tVirtual Account:\tNo\n\tElevated Token:\t\tYes\n\n"
    "Impersonation Level:\t\tImpersonation\n\n"
    "New Logon:\n\tSecurity ID:\t\t" + SID + "\n\tAccount Name:\t\t" + USER + "\n"
    "\tAccount Domain:\t\tSTC\n\tLogon ID:\t\t" + LOGON + "\n\n"
    "Process Information:\n\tProcess ID:\t\t0x2b8\n"
    "\tProcess Name:\t\tC:\\Windows\\System32\\svchost.exe\n\n"
    "Network Information:\n\tWorkstation Name:\t" + HOST + "\n"
    "\tSource Network Address:\t" + IP + "\n\tSource Port:\t\t52431\n\n"
    "Detailed Authentication Information:\n\tLogon Process:\t\tAdvapi  \n"
    "\tAuthentication Package:\tNegotiate\n\tKey Length:\t\t0"
)
obs = base_obs(tc, "4624", 3900200, "{7d3a91f2-4c8b-4e21-a6d5-b0c446240001}")
obs.update({
    "event_data.AuthenticationPackageName": ["Negotiate"],
    "event_data.ElevatedToken": ["%%1842"],
    "event_data.LogonProcessName": ["Advapi"],
    "event_data.LogonType": ["3"],
    "event_data.RestrictedAdminMode": ["-"],
    "event_data.VirtualAccount": ["%%1843"],
    "event_data.WorkstationName": [HOST],
    "event_data.TargetDomainName": ["STC"],
    "event_data.TargetUserName": [USER],
    "event_data.TargetUserSid": [SID],
    "event_data.User": [USER],
    "event_data.UserSid": [SID],
    "message": [msg4624],
})
fire("4624", ["event_data.AuthenticationPackageName", "event_data.ElevatedToken",
              "event_data.LogonProcessName", "event_data.LogonType",
              "event_data.RestrictedAdminMode", "event_data.VirtualAccount",
              "event_data.WorkstationName", "event_data.TargetDomainName",
              "event_data.TargetUserName", "event_data.TargetUserSid",
              "event_data.User", "event_data.UserSid"], obs)

# --- 2. 4672 special privileges assigned to the same logon ---
tc = (now + datetime.timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
msg4672 = (
    "Special privileges assigned to new logon.\n\n"
    "Subject:\n\tSecurity ID:\t\t" + SID + "\n\tAccount Name:\t\t" + USER + "\n"
    "\tAccount Domain:\t\tSTC\n\tLogon ID:\t\t" + LOGON + "\n\n"
    "Privileges:\t\tSeSecurityPrivilege\n\t\t\tSeBackupPrivilege\n"
    "\t\t\tSeRestorePrivilege\n\t\t\tSeTakeOwnershipPrivilege\n\t\t\tSeDebugPrivilege"
)
obs = base_obs(tc, "4672", 3900201, "{7d3a91f2-4c8b-4e21-a6d5-b0c446720001}")
obs["message"] = [msg4672]
fire("4672", [], obs)

# --- 3. 4688 mimikatz process creation ---
tc = (now + datetime.timedelta(seconds=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
msg4688 = (
    "A new process has been created.\n\n"
    "Creator Subject:\n\tSecurity ID:\t\t" + SID + "\n\tAccount Name:\t\t" + USER + "\n"
    "\tAccount Domain:\t\tSTC\n\tLogon ID:\t\t" + LOGON + "\n\n"
    "Target Subject:\n\tSecurity ID:\t\tS-1-0-0\n\tAccount Name:\t\t-\n"
    "\tAccount Domain:\t\t-\n\tLogon ID:\t\t0x0\n\n"
    "Process Information:\n\tNew Process ID:\t\t0x17f4\n"
    "\tNew Process Name:\tC:\\Users\\Public\\mimikatz.exe\n"
    "\tToken Elevation Type:\t%%1937\n"
    "\tMandatory Label:\t\tS-1-16-12288\n"
    "\tCreator Process ID:\t0x2b8\n"
    "\tCreator Process Name:\tC:\\Windows\\System32\\cmd.exe\n"
    "\tProcess Command Line:\tmimikatz.exe \"lsadump::dcsync /user:krbtgt\""
)
obs = base_obs(tc, "4688", 3900202, "{7d3a91f2-4c8b-4e21-a6d5-b0c446880001}")
obs["message"] = [msg4688]
fire("4688", [], obs)
