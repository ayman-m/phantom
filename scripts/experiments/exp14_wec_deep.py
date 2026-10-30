"""Exp 14: deep WEC threat story, attacker persona PHWS-021 / k.alsayed (10.20.63.21).

Kerberoast burst, relay loopbacks, DCSync, lockout storms, short-lived account,
group add/remove, local group enumeration, LDAP admin enumeration, SMS Admins, sensitive reset.
Times spread over the last ~20 min so 10-min/1-h detector windows are hot on arrival.
"""
import json, os, sys, datetime
sys.path.insert(0, os.path.expanduser("~/Documents/Phantom"))
from stc_api import call_tool

NOW = datetime.datetime.now(datetime.timezone.utc)
def ts(d): return (NOW - datetime.timedelta(seconds=d)).strftime("%Y-%m-%dT%H:%M:%SZ")

DOM, DC, SEC = "PHANTOM", "PHDC02", "Microsoft-Windows-Security-Auditing"
SID = "S-1-5-21-3623811015-3361044348-30300820"
ATK_HOST, ATK_IP, ATK_USER, ATK_SID = "PHWS-021", "10.20.63.21", "k.alsayed", SID + "-3210"
ATK_LOGON = "0xD40001"

def sec_evt(eid, computer, t, data, msg, task):
    return {"event_id": eid, "computer": computer, "time": t, "provider": SEC,
            "rendering": {"message": msg, "task": task}, "event_data": data}

def subj(name=ATK_USER, sid=ATK_SID, logon=ATK_LOGON, dom=DOM):
    return f"\tSecurity ID:\t\t{sid}\n\tAccount Name:\t\t{name}\n\tAccount Domain:\t\t{dom}\n\tLogon ID:\t\t{logon}\n"

events = []

# 1) Kerberoast: 20x 4769 RC4, one user, distinct SPNs (10 min)
SPNS = ["MSSQLSvc/PHSRV-SQL0%d.phantom.lab:1433" % i for i in range(1, 6)] + \
       ["HTTP/web%02d.phantom.lab" % i for i in range(1, 8)] + \
       ["CIFS/PHSRV-FS0%d.phantom.lab" % i for i in range(1, 5)] + \
       ["LDAP/PHDC0%d.phantom.lab" % i for i in range(1, 4)]
M4769 = ("A Kerberos service ticket was requested.\n\nAccount Information:\n"
         "\tAccount Name:\t\t{u}@PHANTOM.LAB\n\tAccount Domain:\t\tPHANTOM.LAB\n\tLogon GUID:\t\t{{{g}}}\n\n"
         "Service Information:\n\tService Name:\t\t{s}\n\tService ID:\t\t{sid}-1105\n\n"
         "Network Information:\n\tClient Address:\t\t::ffff:{ip}\n\tClient Port:\t\t{p}\n\n"
         "Additional Information:\n\tTicket Options:\t\t0x40810000\n\tTicket Encryption Type:\t0x17\n"
         "\tFailure Code:\t\t0x0\n\tTransited Services:\t-")
for i, spn in enumerate(SPNS):
    g = "%08x-b22c-4e5f-8a00-%012x" % (0x47690000 + i, i)
    events.append(sec_evt(4769, DC, ts(1100 - i * 25), {
        "TargetUserName": ATK_USER + "@PHANTOM.LAB", "TargetDomainName": "PHANTOM.LAB",
        "ServiceName": spn, "ServiceSid": SID + "-1105", "TicketOptions": "0x40810000",
        "TicketEncryptionType": "0x17", "IpAddress": "::ffff:" + ATK_IP,
        "IpPort": str(55000 + i), "Status": "0x0", "LogonGuid": "{" + g + "}",
        "TransmittedServices": "-"},
        M4769.format(u=ATK_USER, g=g, s=spn, sid=SID, ip=ATK_IP, p=55000 + i),
        "Kerberos Service Ticket Operations"))

# 2) Relay: 12x 4624 NTLM loopback onto PHSRV-FS01 (catalogued id -> rendering free)
for i in range(12):
    events.append({"event_id": 4624, "computer": "PHSRV-FS01", "time": ts(1000 - i * 8),
        "event_data": {"SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHSRV-FS01$",
            "SubjectDomainName": DOM, "SubjectLogonId": "0x3E7",
            "TargetUserSid": ATK_SID, "TargetUserName": ATK_USER,
            "TargetDomainName": DOM, "TargetLogonId": "0x%x" % (0xD50000 + i * 0x111),
            "LogonType": "3", "LogonProcessName": "NtLmSsp",
            "AuthenticationPackageName": "NTLM", "WorkstationName": "PHSRV-FS01",
            "IpAddress": "10.20.16.10", "IpPort": str(56000 + i)}})

# 3) DCSync: logon story + 4x 4662 replication GUIDs from the attacker
GUIDS = ("{1131f6aa-9c07-11d1-f79f-00c04fc2dcd2}; {1131f6ad-9c07-11d1-f79f-00c04fc2dcd2}; "
         "{1131f6ae-9c07-11d1-f79f-00c04fc2dcd2}; {89e95b76-444d-4c62-991a-0facbeda640c}")
KRBTGT = "CN=krbtgt,CN=Users,DC=phantom,DC=lab"
events.append({"event_id": 4624, "computer": DC, "time": ts(950), "event_data": {
    "SubjectUserSid": "S-1-5-18", "SubjectUserName": DC + "$", "SubjectDomainName": DOM,
    "SubjectLogonId": "0x3E7", "TargetUserSid": ATK_SID, "TargetUserName": ATK_USER,
    "TargetDomainName": DOM, "TargetLogonId": ATK_LOGON, "LogonType": "3",
    "LogonProcessName": "Kerberos", "AuthenticationPackageName": "Kerberos",
    "WorkstationName": ATK_HOST, "IpAddress": ATK_IP, "IpPort": "56100"}})
M4662 = ("An operation was performed on an object.\n\nSubject :\n" + subj() + "\n"
         "Object:\n\tObject Server:\t\tDS\n\tObject Type:\t\t%{bf967aba-0de6-11d0-a285-00aa003049e2}\n"
         f"\tObject Name:\t\t{KRBTGT}\n\tHandle ID:\t\t0x0\n\n"
         "Operation:\n\tOperation Type:\t\tObject Access\n\tAccess Mask:\t\t0x100\n"
         f"\tProperties:\t\t{GUIDS}\n\t\t\t{KRBTGT}\n\n"
         "Additional Information:\n\tParameter 1:\t\t-\n\tParameter 2:\t\t-")
for i in range(4):
    events.append(sec_evt(4662, DC, ts(940 - i * 4), {
        "SubjectUserSid": ATK_SID, "SubjectUserName": ATK_USER, "SubjectDomainName": DOM,
        "SubjectLogonId": ATK_LOGON, "ObjectServer": "DS",
        "ObjectType": "%{bf967aba-0de6-11d0-a285-00aa003049e2}", "ObjectName": KRBTGT,
        "HandleId": "0x0", "OperationType": "Object Access", "AccessMask": "0x100",
        "Properties": GUIDS, "Parameter1": "-", "Parameter2": "-"}, M4662,
        "Directory Service Access"))

# 4) Lockouts: 10 distinct users + 6x same user, caller = attacker host
LOCK_USERS = ["a.hindi", "r.qahtani", "s.dossari", "n.shammari", "l.otaibi",
              "h.anazi", "f.harbi", "m.shehri", "j.mutairi", "t.ghamdi"]
def m4740(u, caller=ATK_HOST):
    return ("A user account was locked out.\n\nSubject:\n" + subj("SYSTEM", "S-1-5-18", "0x3E7") + "\n"
            "Account That Was Locked Out:\n\tSecurity ID:\t\t" + SID + "-4%03d\n"
            "\tAccount Name:\t\t%s\n\nAdditional Information:\n\tCaller Computer Name:\t\t%s" % (hash(u) % 900, u, caller))
for i, u in enumerate(LOCK_USERS):
    events.append(sec_evt(4740, DC, ts(900 - i * 30), {
        "SubjectUserSid": "S-1-5-18", "SubjectUserName": DC + "$", "SubjectDomainName": DOM,
        "SubjectLogonId": "0x3E7", "TargetUserName": u, "TargetDomainName": DOM,
        "TargetSid": SID + "-4%03d" % (abs(hash(u)) % 900)}, m4740(u), "User Lockout"))
for i in range(6):
    events.append(sec_evt(4740, DC, ts(850 - i * 40), {
        "SubjectUserSid": "S-1-5-18", "SubjectUserName": DC + "$", "SubjectDomainName": DOM,
        "SubjectLogonId": "0x3E7", "TargetUserName": "svc.print", "TargetDomainName": DOM,
        "TargetSid": SID + "-3211"}, m4740("svc.print"), "User Lockout"))

# 5) Short-lived account: 4720 then 4726 four minutes later
M4720 = ("A user account was created.\n\nSubject:\n" + subj() + "\n"
         "New Account:\n\tSecurity ID:\t\t" + SID + "-3212\n\tAccount Name:\t\ttmp.sync42\n"
         "\tAccount Domain:\t\t" + DOM + "\n\nAttributes:\n\tSAM Account Name:\ttmp.sync42")
M4726 = ("A user account was deleted.\n\nSubject:\n" + subj() + "\n"
         "Target Account:\n\tSecurity ID:\t\t" + SID + "-3212\n\tAccount Name:\t\ttmp.sync42\n"
         "\tAccount Domain:\t\t" + DOM)
common = {"SubjectUserSid": ATK_SID, "SubjectUserName": ATK_USER, "SubjectDomainName": DOM,
          "SubjectLogonId": ATK_LOGON}
events.append(sec_evt(4720, DC, ts(800), {**common, "TargetUserName": "tmp.sync42",
    "TargetDomainName": DOM, "TargetSid": SID + "-3212", "SamAccountName": "tmp.sync42",
    "PrivilegeList": "-"}, M4720, "User Account Management"))
events.append(sec_evt(4726, DC, ts(560), {**common, "TargetUserName": "tmp.sync42",
    "TargetDomainName": DOM, "TargetSid": SID + "-3212", "PrivilegeList": "-"},
    M4726, "User Account Management"))

# 6) Group add then remove: k.alsayed -> Helpdesk Admins
for eid, verb, t in [(4728, "added to", 700), (4729, "removed from", 240)]:
    m = ("A member was %s a security-enabled global group.\n\nSubject:\n" % verb) + subj() + "\n" \
        "Member:\n\tSecurity ID:\t\t" + ATK_SID + "\n\tAccount Name:\t\tCN=K. Alsayed,OU=Users,DC=phantom,DC=lab\n\n" \
        "Group:\n\tSecurity ID:\t\t" + SID + "-1210\n\tGroup Name:\t\tHelpdesk Admins\n\tGroup Domain:\t\t" + DOM + "\n\n" \
        "Additional Information:\n\tPrivileges:\t\t-"
    events.append(sec_evt(eid, DC, ts(t), {**common,
        "MemberName": "CN=K. Alsayed,OU=Users,DC=phantom,DC=lab", "MemberSid": ATK_SID,
        "TargetUserName": "Helpdesk Admins", "TargetDomainName": DOM,
        "TargetSid": SID + "-1210", "PrivilegeList": "-"}, m, "Security Group Management"))

# 7) Local group enumeration burst on the foothold: 8x 4798 + 7x 4799 (5 min)
for i in range(8):
    events.append(sec_evt(4798, ATK_HOST, ts(500 - i * 15), {**common,
        "TargetUserName": "Administrator", "TargetDomainName": ATK_HOST,
        "CallerProcessId": "0x15f4", "CallerProcessName": "C:\\Windows\\System32\\net.exe"},
        "A user's local group membership was enumerated.\n\nSubject:\n" + subj() + "\n"
        "Account Whose Groups Were Enumerated:\n\tAccount Name:\t\tAdministrator\n\n"
        "Process Information:\n\tProcess ID:\t\t0x15f4\n\tProcess Name:\t\tC:\\Windows\\System32\\net.exe",
        "User Account Management"))
GROUPS = ["Administrators", "Remote Desktop Users", "Backup Operators", "Power Users",
          "Server Operators", "Account Operators", "Print Operators"]
for i, gname in enumerate(GROUPS):
    events.append(sec_evt(4799, ATK_HOST, ts(490 - i * 15), {**common,
        "TargetUserName": gname, "TargetDomainName": ATK_HOST,
        "CallerProcessId": "0x15f4", "CallerProcessName": "C:\\Windows\\System32\\net.exe"},
        "A security-enabled local group membership was enumerated.\n\nSubject:\n" + subj() + "\n"
        "Group:\n\tGroup Name:\t\t%s\n\nProcess Information:\n\tProcess ID:\t\t0x15f4\n"
        "\tProcess Name:\t\tC:\\Windows\\System32\\net.exe" % gname, "Security Group Management"))

# 8) LDAP admin-group enumeration: 6x 1644 on the DC from the attacker IP
FILTERS = ["(adminCount=1)", "(&(objectClass=group)(name=Domain Admins))",
           "(memberOf=CN=Domain Admins,CN=Users,DC=phantom,DC=lab)",
           "(&(objectClass=group)(name=Enterprise Admins))",
           "(memberOf=CN=Administrators,CN=Builtin,DC=phantom,DC=lab)",
           "(&(objectClass=user)(adminCount=1)(pwdLastSet=*))"]
for i, f in enumerate(FILTERS):
    events.append({
        "event_id": 1644, "computer": DC, "time": ts(400 - i * 20),
        "channel": "Directory Service",
        "provider": "Microsoft-Windows-ActiveDirectory_DomainService",
        "rendering": {"task": "LDAP Interface Events", "message":
            "Internal event: A client issued a search operation with the following options.\n\n"
            "Client:\n\t%s:53%03d\nStarting node:\n\tDC=phantom,DC=lab\nFilter:\n\t %s\n"
            "Search scope:\n\tsubtree\nAttribute selection:\n\tmemberOf;name;sAMAccountName\n"
            "Server controls:\n\t1.2.840.113556.1.4.319\nVisited entries:\n\t15200\n"
            "Returned entries:\n\t42" % (ATK_IP, 200 + i, f)},
        "event_data": ["4", "%s:53%03d" % (ATK_IP, 200 + i), "DC=phantom,DC=lab", f,
                       "subtree", "memberOf;name;sAMAccountName", "1.2.840.113556.1.4.319",
                       "15200", "42"]})

# 9) SMS Admins local group addition on PHSRV-FS01
events.append(sec_evt(4732, "PHSRV-FS01", ts(300), {**common,
    "MemberName": "-", "MemberSid": ATK_SID, "TargetUserName": "SMS Admins",
    "TargetDomainName": "PHSRV-FS01", "TargetSid": "S-1-5-32-1001", "PrivilegeList": "-"},
    "A member was added to a security-enabled local group.\n\nSubject:\n" + subj() + "\n"
    "Member:\n\tSecurity ID:\t\t" + ATK_SID + "\n\tAccount Name:\t\t-\n\n"
    "Group:\n\tSecurity ID:\t\tS-1-5-32-1001\n\tGroup Name:\t\tSMS Admins\n"
    "\tGroup Domain:\t\tPHSRV-FS01\n\nAdditional Information:\n\tPrivileges:\t\t-",
    "Security Group Management"))

# 10) Sensitive password reset: non-admin resets adm.malwadi
events.append(sec_evt(4724, DC, ts(200), {
    "SubjectUserSid": SID + "-3207", "SubjectUserName": "helpdesk.temp",
    "SubjectDomainName": DOM, "SubjectLogonId": "0x9C3310",
    "TargetUserName": "adm.malwadi", "TargetDomainName": DOM, "TargetSid": SID + "-1128"},
    "An attempt was made to reset an account's password.\n\nSubject:\n" +
    subj("helpdesk.temp", SID + "-3207", "0x9C3310") + "\n"
    "Target Account:\n\tSecurity ID:\t\t" + SID + "-1128\n\tAccount Name:\t\tadm.malwadi\n"
    "\tAccount Domain:\t\t" + DOM, "User Account Management"))

r = call_tool("wec-sender.send_events", {"events": events}, timeout=240)
res = r["result"]
print(json.dumps({k: res.get(k) for k in ("ok", "events", "sent", "envelopes")}, indent=1))
print("computers:", json.dumps(res.get("computers"))[:200])
