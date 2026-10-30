"""Exp 9: P1 single-event Windows threats over native WEC (batch 2).

Detectors (docs/experiments/2026-10-03-wec-detector-picklist.md):
  #13 password never expires (4738)        #56 system time changed (4616)
  #3  default account enabled (4722 Guest) #2  local "Administrator" created (4720)
  #14 sensitive acct pwd reset (4724)      #30/#28 sAMAccountName DC-spoof rename (4781)
  #31 SPNs cleared (4742)                  #33 delegation change (4742)
All Security channel, phantom.lab domain, PHDC02 DC unless noted. Non-catalogued ids carry
their own provider + rendering (message is load-bearing for the parsing rules).
"""
import json, os, sys, datetime
sys.path.insert(0, os.path.expanduser("~/Documents/Phantom"))
from stc_api import call_tool

NOW = datetime.datetime.now(datetime.timezone.utc)
def ts(delta_s): return (NOW - datetime.timedelta(seconds=delta_s)).strftime("%Y-%m-%dT%H:%M:%SZ")

DOM, DC = "PHANTOM", "PHDC02"
SEC = "Microsoft-Windows-Security-Auditing"
SID = "S-1-5-21-3623811015-3361044348-30300820"
ADMIN = {"SubjectUserSid": SID + "-1128", "SubjectUserName": "adm.malwadi",
         "SubjectDomainName": DOM, "SubjectLogonId": "0x73B226"}

def subj_block(name="adm.malwadi", sid=SID + "-1128", logon="0x73B226"):
    return (f"\tSecurity ID:\t\t{sid}\n\tAccount Name:\t\t{name}\n"
            f"\tAccount Domain:\t\t{DOM}\n\tLogon ID:\t\t{logon}\n")

events = []

# #13 — 4738 password never expires on svc.report
events.append({
    "event_id": 4738, "computer": DC, "time": ts(90), "provider": SEC,
    "rendering": {"task": "User Account Management", "message":
        "A user account was changed.\n\nSubject:\n" + subj_block() +
        "\nTarget Account:\n\tSecurity ID:\t\t" + SID + "-3205\n"
        "\tAccount Name:\t\tsvc.report\n\tAccount Domain:\t\t" + DOM + "\n\n"
        "Changed Attributes:\n\tSAM Account Name:\tsvc.report\n"
        "\tUser Account Control:\t'Don't Expire Password - Enabled'\n\n"
        "Additional Information:\n\tPrivileges:\t\t-"},
    "event_data": {**ADMIN, "TargetUserName": "svc.report", "TargetDomainName": DOM,
                   "TargetSid": SID + "-3205", "SamAccountName": "svc.report",
                   "UserAccountControl": "Don't Expire Password - Enabled",
                   "PrivilegeList": "-"},
})

# #56 — 4616 system time changed on a workstation
events.append({
    "event_id": 4616, "computer": "PHWS-007", "time": ts(80), "provider": SEC,
    "rendering": {"task": "Security State Change", "message":
        "The system time was changed.\n\nSubject:\n" + subj_block("j.tan", SID + "-3206", "0x8F1102") +
        "\nProcess Information:\n\tProcess ID:\t\t0x4f4\n"
        "\tProcess Name:\t\tC:\\Windows\\System32\\svchost.exe\n\n"
        "New Time:\t\t" + ts(80) + "\nPrevious Time:\t\t2026-10-01T02:30:00.000Z"},
    "event_data": {"SubjectUserSid": SID + "-3206", "SubjectUserName": "j.tan",
                   "SubjectDomainName": DOM, "SubjectLogonId": "0x8F1102",
                   "ProcessId": "0x4f4",
                   "ProcessName": "C:\\Windows\\System32\\svchost.exe",
                   "NewTime": ts(80), "PreviousTime": "2026-10-01T02:30:00.000Z"},
})

# #3 — 4722 Guest enabled
events.append({
    "event_id": 4722, "computer": "PHSRV-FS01", "time": ts(70), "provider": SEC,
    "rendering": {"task": "User Account Management", "message":
        "A user account was enabled.\n\nSubject:\n" + subj_block() +
        "\nTarget Account:\n\tSecurity ID:\t\tS-1-5-21-3623811015-3361044348-30300820-501\n"
        "\tAccount Name:\t\tGuest\n\tAccount Domain:\t\t" + DOM},
    "event_data": {**ADMIN, "TargetUserName": "Guest", "TargetDomainName": DOM,
                   "TargetSid": SID + "-501"},
})

# #2 — 4720 local "Administrator" created on a member server (masquerade)
events.append({
    "event_id": 4720, "computer": "PHSRV-FS01", "time": ts(60), "provider": SEC,
    "rendering": {"task": "User Account Management", "message":
        "A user account was created.\n\nSubject:\n" + subj_block() +
        "\nNew Account:\n\tSecurity ID:\t\tS-1-5-21-7654321-7654321-7654321-1009\n"
        "\tAccount Name:\t\tAdministrator\n\tAccount Domain:\t\tPHSRV-FS01\n\n"
        "Attributes:\n\tSAM Account Name:\tAdministrator"},
    "event_data": {**ADMIN, "TargetUserName": "Administrator",
                   "TargetDomainName": "PHSRV-FS01",
                   "TargetSid": "S-1-5-21-7654321-7654321-7654321-1009",
                   "SamAccountName": "Administrator", "PrivilegeList": "-"},
})

# #14 — 4724 reset of a sensitive admin account by a non-admin
events.append({
    "event_id": 4724, "computer": DC, "time": ts(50), "provider": SEC,
    "rendering": {"task": "User Account Management", "message":
        "An attempt was made to reset an account's password.\n\nSubject:\n" +
        subj_block("helpdesk.temp", SID + "-3207", "0x9C3310") +
        "\nTarget Account:\n\tSecurity ID:\t\t" + SID + "-1128\n"
        "\tAccount Name:\t\tadm.malwadi\n\tAccount Domain:\t\t" + DOM},
    "event_data": {"SubjectUserSid": SID + "-3207", "SubjectUserName": "helpdesk.temp",
                   "SubjectDomainName": DOM, "SubjectLogonId": "0x9C3310",
                   "TargetUserName": "adm.malwadi", "TargetDomainName": DOM,
                   "TargetSid": SID + "-1128"},
})

# #30/#28 — 4781 machine account renamed to a DC's sAMAccountName
events.append({
    "event_id": 4781, "computer": DC, "time": ts(40), "provider": SEC,
    "rendering": {"task": "User Account Management", "message":
        "The name of an account was changed:\n\nSubject:\n" + subj_block() +
        "\nAccount Whose Name Was Changed:\n\tSecurity ID:\t\t" + SID + "-3110\n"
        "\tOld Account Name:\tPHWS-110$\n\tNew Account Name:\tPHDC02$"},
    "event_data": {**ADMIN, "OldTargetUserName": "PHWS-110$",
                   "NewTargetUserName": "PHDC02$", "TargetSid": SID + "-3110"},
})

# #31 — 4742 SPNs cleared from a machine account
events.append({
    "event_id": 4742, "computer": DC, "time": ts(30), "provider": SEC,
    "rendering": {"task": "User Account Management", "message":
        "A computer account was changed.\n\nSubject:\n" + subj_block() +
        "\nComputer That Was Changed:\n\tSecurity ID:\t\t" + SID + "-3111\n"
        "\tAccount Name:\t\tPHSRV-SQL01$\n\tAccount Domain:\t\t" + DOM + "\n\n"
        "Changed Attributes:\n\tSAM Account Name:\tPHSRV-SQL01$\n"
        "\tService Principal Names:\t-"},
    "event_data": {**ADMIN, "TargetUserName": "PHSRV-SQL01$", "TargetDomainName": DOM,
                   "TargetSid": SID + "-3111", "SamAccountName": "PHSRV-SQL01$",
                   "ServicePrincipalNames": "-", "PrivilegeList": "-"},
})

# #33 — 4742 delegation change on a user account
events.append({
    "event_id": 4742, "computer": DC, "time": ts(20), "provider": SEC,
    "rendering": {"task": "User Account Management", "message":
        "A computer account was changed.\n\nSubject:\n" + subj_block() +
        "\nComputer That Was Changed:\n\tSecurity ID:\t\t" + SID + "-3112\n"
        "\tAccount Name:\t\tPHWS-112$\n\tAccount Domain:\t\t" + DOM + "\n\n"
        "Changed Attributes:\n\tSAM Account Name:\tPHWS-112$\n"
        "\tAllowed To Delegate To:\tHTTP/PHSRV-FS01.phantom.lab"},
    "event_data": {**ADMIN, "TargetUserName": "PHWS-112$", "TargetDomainName": DOM,
                   "TargetSid": SID + "-3112", "SamAccountName": "PHWS-112$",
                   "AllowedToDelegateTo": "HTTP/PHSRV-FS01.phantom.lab",
                   "PrivilegeList": "-"},
})

r = call_tool("wec-sender.send_events", {"events": events}, timeout=180)
print(json.dumps(r["result"], indent=1)[:900])
