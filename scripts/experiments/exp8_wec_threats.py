"""Exp 8: P1 Windows threat batch over native WEC via wec-sender.send_events.

Step 2 of the Kerberos relay two-step test (Exp 7 was the syslog leg) plus the first crafted
WEC threats from docs/experiments/2026-10-03-wec-detector-picklist.md:
  A. kerberos_relay            #54 ungated  - 12x 4624 NTLM type-3, source IP == target host
  B. dcsync                    #40          - 4624 story + 4x 4662 replication GUIDs, non-DC subject
  C. machine_account_to_da     #17 Medium   - 4728 adding PHWS-110$ to Domain Admins

Domain: PHANTOM / phantom.lab (wec-sender synthetic domain). DC: PHDC02.phantom.lab.
"""
import json, os, sys, datetime
sys.path.insert(0, os.path.expanduser("~/Documents/Phantom"))
from stc_api import call_tool

NOW = datetime.datetime.now(datetime.timezone.utc)
def ts(delta_s):
    return (NOW - datetime.timedelta(seconds=delta_s)).strftime("%Y-%m-%dT%H:%M:%SZ")

DOM, DNS, DC = "PHANTOM", "phantom.lab", "PHDC02"
SEC_PROV = "Microsoft-Windows-Security-Auditing"
USER_SID = "S-1-5-21-3623811015-3361044348-30300820"

events = []

# --- A. Kerberos relay (#54): 4624 NTLM loopback on PHSRV-FS01 -------------------
FS, FS_IP = "PHSRV-FS01", "10.20.16.10"
RELAY_USERS = ["svc.backup", "adm.khalid", "m.alsaeed", "j.tan"]
for i in range(12):
    u = RELAY_USERS[i % len(RELAY_USERS)]
    events.append({
        "event_id": 4624, "computer": FS, "time": ts(600 - i * 5),
        "event_data": {
            "SubjectUserSid": "S-1-5-18", "SubjectUserName": FS + "$",
            "SubjectDomainName": DOM, "SubjectLogonId": "0x3E7",
            "TargetUserSid": f"{USER_SID}-{3201 + i % 4}", "TargetUserName": u,
            "TargetDomainName": DOM, "TargetLogonId": "0x%x" % (0xB10000 + i * 0x111),
            "LogonType": "3", "LogonProcessName": "NtLmSsp",
            "AuthenticationPackageName": "NTLM",
            "WorkstationName": FS, "IpAddress": FS_IP, "IpPort": str(49000 + i),
        },
    })

# --- B. DCSync (#40): 4624 story + 4x 4662 replication on the DC, non-DC subject --
ATK, ATK_IP, ATK_USER = "PHWS-105", "10.20.16.105", "phantom.repltest"
ATK_SID = USER_SID + "-3202"
GUIDS = ("{1131f6aa-9c07-11d1-f79f-00c04fc2dcd2}; "
         "{1131f6ad-9c07-11d1-f79f-00c04fc2dcd2}; "
         "{1131f6ae-9c07-11d1-f79f-00c04fc2dcd2}; "
         "{89e95b76-444d-4c62-991a-0facbeda640c}")
KRB_TGT = "CN=krbtgt,CN=Users,DC=phantom,DC=lab"

events.append({
    "event_id": 4624, "computer": DC, "time": ts(310),
    "event_data": {
        "SubjectUserSid": "S-1-5-18", "SubjectUserName": DC + "$",
        "SubjectDomainName": DOM, "SubjectLogonId": "0x3E7",
        "TargetUserSid": ATK_SID, "TargetUserName": ATK_USER,
        "TargetDomainName": DOM, "TargetLogonId": "0xC20001",
        "LogonType": "3", "LogonProcessName": "Kerberos",
        "AuthenticationPackageName": "Kerberos",
        "WorkstationName": ATK, "IpAddress": ATK_IP, "IpPort": "51510",
    },
})

MSG_4662 = (
    "An operation was performed on an object.\n\n"
    "Subject :\n"
    f"\tSecurity ID:\t\t{ATK_SID}\n"
    f"\tAccount Name:\t\t{ATK_USER}\n"
    f"\tAccount Domain:\t\t{DOM}\n"
    "\tLogon ID:\t\t0xC20001\n\n"
    "Object:\n"
    "\tObject Server:\t\tDS\n"
    "\tObject Type:\t\t%{bf967aba-0de6-11d0-a285-00aa003049e2}\n"
    f"\tObject Name:\t\t{KRB_TGT}\n"
    "\tHandle ID:\t\t0x0\n\n"
    "Operation:\n"
    "\tOperation Type:\t\tObject Access\n"
    "\tAccess Mask:\t\t0x100\n"
    f"\tProperties:\t\t{GUIDS}\n"
    f"\t\t\t{KRB_TGT}\n\n"
    "Additional Information:\n"
    "\tParameter 1:\t\t-\n"
    "\tParameter 2:\t\t-"
)
for i in range(4):
    events.append({
        "event_id": 4662, "computer": DC, "time": ts(300 - i * 4),
        "provider": SEC_PROV,
        "rendering": {"message": MSG_4662, "task": "Directory Service Access"},
        "event_data": {
            "SubjectUserSid": ATK_SID, "SubjectUserName": ATK_USER,
            "SubjectDomainName": DOM, "SubjectLogonId": "0xC20001",
            "ObjectServer": "DS",
            "ObjectType": "%{bf967aba-0de6-11d0-a285-00aa003049e2}",
            "ObjectName": KRB_TGT, "HandleId": "0x0",
            "OperationType": "Object Access", "AccessMask": "0x100",
            "Properties": GUIDS, "Parameter1": "-", "Parameter2": "-",
        },
    })

# --- C. Machine account to Domain Admins (#17): 4728 on the DC --------------------
MSG_4728 = (
    "A member was added to a security-enabled global group.\n\n"
    "Subject:\n"
    f"\tSecurity ID:\t\t{USER_SID}-1128\n"
    "\tAccount Name:\t\tadm.malwadi\n"
    f"\tAccount Domain:\t\t{DOM}\n"
    "\tLogon ID:\t\t0x73B226\n\n"
    "Member:\n"
    "\tSecurity ID:\t\t" + USER_SID + "-3110\n"
    "\tAccount Name:\t\tCN=PHWS-110,CN=Computers,DC=phantom,DC=lab\n\n"
    "Group:\n"
    f"\tSecurity ID:\t\t{USER_SID}-512\n"
    "\tGroup Name:\t\tDomain Admins\n"
    f"\tGroup Domain:\t\t{DOM}\n\n"
    "Additional Information:\n"
    "\tPrivileges:\t\t-"
)
events.append({
    "event_id": 4728, "computer": DC, "time": ts(120),
    "provider": SEC_PROV,
    "rendering": {"message": MSG_4728, "task": "Security Group Management"},
    "event_data": {
        "MemberName": "CN=PHWS-110,CN=Computers,DC=phantom,DC=lab",
        "MemberSid": USER_SID + "-3110",
        "SubjectUserSid": USER_SID + "-1128", "SubjectUserName": "adm.malwadi",
        "SubjectDomainName": DOM, "SubjectLogonId": "0x73B226",
        "TargetUserName": "Domain Admins", "TargetDomainName": DOM,
        "TargetSid": USER_SID + "-512", "PrivilegeList": "-",
    },
})

r = call_tool("wec-sender.send_events", {"events": events}, timeout=180)
print(json.dumps(r["result"], indent=1)[:1200])
