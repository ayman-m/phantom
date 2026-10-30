"""Exp 15: shape-tuning variants for the detectors that did NOT fire in Exp 8-14.

Each variant uses a distinct target user/host so alert attribution tells us which shape worked.
  A. Kerberos relay - 4 variants (loopback IP, Kerberos pkg, DC self-relay, machine account)
  B. LDAP admin enum - heavier: 15x 1644, big visited-entries, admin filters
  C. sAMAccountName spoof full sequence: 4781 rename + 4768 TGT for renamed + 4769 ticket
  D. 4742 SPN-cleared + delegation with complete Changed Attributes
  E. 4616 time change on the DC itself
  F. 4724 sensitive reset x3 (attempt pattern)
  G. Short-lived account 4720->4726 three minutes apart
  H. 4662 System Management Container access (#53)
  I. 4768 PKINIT (certificate fields populated) (#26)
  J. Single-account lockout storm: 12x 4740 same user (#16)
"""
import json, os, sys, datetime
sys.path.insert(0, os.path.expanduser("~/Documents/Phantom"))
from stc_api import call_tool

NOW = datetime.datetime.now(datetime.timezone.utc)
def ts(d): return (NOW - datetime.timedelta(seconds=d)).strftime("%Y-%m-%dT%H:%M:%SZ")
DOM, DC, SEC = "PHANTOM", "PHDC02", "Microsoft-Windows-Security-Auditing"
SID = "S-1-5-21-3623811015-3361044348-30300820"
ADMIN = {"SubjectUserSid": SID + "-1128", "SubjectUserName": "adm.malwadi",
         "SubjectDomainName": DOM, "SubjectLogonId": "0x73B226"}

def sec(eid, computer, t, data, msg, task):
    return {"event_id": eid, "computer": computer, "time": t, "provider": SEC,
            "rendering": {"message": msg, "task": task}, "event_data": data}

def subj(name="adm.malwadi", sid=SID + "-1128", logon="0x73B226"):
    return (f"\tSecurity ID:\t\t{sid}\n\tAccount Name:\t\t{name}\n"
            f"\tAccount Domain:\t\t{DOM}\n\tLogon ID:\t\t{logon}\n")

events = []

# ---- A. Kerberos relay variants (4624) ---------------------------------------
def relay(computer, t, target_user, target_sid, src_ip, src_ws, pkg, proc):
    return {"event_id": 4624, "computer": computer, "time": t, "event_data": {
        "SubjectUserSid": "S-1-5-18", "SubjectUserName": computer + "$",
        "SubjectDomainName": DOM, "SubjectLogonId": "0x3E7",
        "TargetUserSid": target_sid, "TargetUserName": target_user,
        "TargetDomainName": DOM, "TargetLogonId": "0x%x" % (abs(hash((target_user, t))) % 0xFFFFFF),
        "LogonType": "3", "LogonProcessName": proc, "AuthenticationPackageName": pkg,
        "WorkstationName": src_ws, "IpAddress": src_ip, "IpPort": "49871"}}
# v1 literal loopback
events.append(relay("PHSRV-FS01", ts(900), "relay.v1.loopback", SID + "-3301", "127.0.0.1", "PHSRV-FS01", "NTLM", "NtLmSsp"))
# v2 kerberos package, workstation == target
events.append(relay("PHSRV-FS01", ts(880), "relay.v2.krb", SID + "-3302", "10.20.16.10", "PHSRV-FS01", "Kerberos", "Kerberos"))
# v3 DC self-relay: logon on DC sourced from DC IP
events.append(relay(DC, ts(860), "relay.v3.dcself", SID + "-3303", "10.20.0.12", DC, "NTLM", "NtLmSsp"))
# v4 machine account relayed onto itself
events.append(relay("PHSRV-APP01", ts(840), "PHSRV-APP01$", SID + "-1401", "10.20.16.40", "PHSRV-APP01", "NTLM", "NtLmSsp"))

# ---- B. LDAP admin enum, heavier ----------------------------------------------
FILTERS = ["(adminCount=1)", "(&(objectClass=group)(name=Domain Admins))",
           "(memberOf=CN=Domain Admins,CN=Users,DC=phantom,DC=lab)",
           "(&(objectClass=group)(name=Enterprise Admins))",
           "(memberOf=CN=Administrators,CN=Builtin,DC=phantom,DC=lab)",
           "(&(objectClass=user)(adminCount=1))",
           "(&(objectClass=group)(name=Schema Admins))",
           "(memberOf=CN=Enterprise Admins,CN=Users,DC=phantom,DC=lab)",
           "(&(objectClass=group)(name=Account Operators))",
           "(memberOf=CN=Schema Admins,CN=Users,DC=phantom,DC=lab)",
           "(&(objectClass=group)(name=Backup Operators))",
           "(memberOf=CN=Account Operators,CN=Builtin,DC=phantom,DC=lab)",
           "(&(objectClass=user)(memberOf=*Admins*))",
           "(&(objectClass=group)(adminCount=1))",
           "(memberOf=CN=Backup Operators,CN=Builtin,DC=phantom,DC=lab)"]
for i, f in enumerate(FILTERS):
    events.append({
        "event_id": 1644, "computer": DC, "time": ts(800 - i * 12),
        "channel": "Directory Service",
        "provider": "Microsoft-Windows-ActiveDirectory_DomainService",
        "rendering": {"task": "LDAP Interface Events", "message":
            "Internal event: A client issued a search operation with the following options.\n\n"
            "Client:\n\t10.20.63.25:54%03d\nStarting node:\n\tDC=phantom,DC=lab\n"
            "Filter:\n\t %s\nSearch scope:\n\tsubtree\n"
            "Attribute selection:\n\tmemberOf;name;sAMAccountName\n"
            "Server controls:\n\t1.2.840.113556.1.4.319\nVisited entries:\n\t28450\n"
            "Returned entries:\n\t127" % (100 + i, f)},
        "event_data": ["4", "10.20.63.25:54%03d" % (100 + i), "DC=phantom,DC=lab", f,
                       "subtree", "memberOf;name;sAMAccountName", "1.2.840.113556.1.4.319",
                       "28450", "127"]})

# ---- C. sAMAccountName spoof sequence -----------------------------------------
# rename machine to DC-looking name, request TGT + service ticket for it, rename back
M4781 = ("The name of an account was changed:\n\nSubject:\n" + subj() + "\n"
         "Account Whose Name Was Changed:\n\tSecurity ID:\t\t" + SID + "-3115\n"
         "\tOld Account Name:\t{old}\n\tNew Account Name:\t{new}")
for old, new, t in [("PHWS-115$", "PHDC02$", 700), ("PHDC02$", "PHWS-115$", 400)]:
    events.append(sec(4781, DC, ts(t), {**ADMIN, "OldTargetUserName": old,
        "NewTargetUserName": new, "TargetSid": SID + "-3115"},
        M4781.format(old=old, new=new), "User Account Management"))
M4768 = ("A Kerberos authentication ticket (TGT) was requested.\n\nAccount Information:\n"
         "\tAccount Name:\t\tPHDC02$\n\tSupplied Realm Name:\t\tPHANTOM.LAB\n"
         "\tUser ID:\t\t\t" + SID + "-3115\n\nService Information:\n\tService Name:\t\tkrbtgt\n"
         "\tService ID:\t\t" + SID + "-502\n\nNetwork Information:\n"
         "\tClient Address:\t\t::ffff:10.20.63.115\n\tClient Port:\t\t57100\n\n"
         "Additional Information:\n\tTicket Options:\t\t0x40810010\n\tResult Code:\t\t0x0\n"
         "\tTicket Encryption Type:\t0x12\n\tPre-Authentication Type:\t2\n\n"
         "Certificate Information:\n\tCertificate Issuer Name:\t\t-\n"
         "\tCertificate Serial Number:\t-\n\tCertificate Thumbprint:\t\t-")
events.append(sec(4768, DC, ts(650), {
    "TargetUserName": "PHDC02$", "TargetDomainName": "PHANTOM.LAB", "TargetSid": SID + "-3115",
    "ServiceName": "krbtgt", "ServiceSid": SID + "-502", "TicketOptions": "0x40810010",
    "Status": "0x0", "TicketEncryptionType": "0x12", "PreAuthType": "2",
    "IpAddress": "::ffff:10.20.63.115", "IpPort": "57100"}, M4768,
    "Kerberos Authentication Service"))

# ---- D. 4742 SPN-cleared + delegation, complete shape --------------------------
M4742_SPN = ("A computer account was changed.\n\nSubject:\n" + subj() + "\n"
    "Computer That Was Changed:\n\tSecurity ID:\t\t" + SID + "-3116\n"
    "\tAccount Name:\t\tPHSRV-ERP01$\n\tAccount Domain:\t\t" + DOM + "\n\n"
    "Changed Attributes:\n\tSAM Account Name:\tPHSRV-ERP01$\n"
    "\tService Principal Names:\n\t\tPrevious Value: MSSQLSvc/PHSRV-ERP01.phantom.lab:1433;HTTP/PHSRV-ERP01.phantom.lab\n"
    "\t\tNew Value: -\n\tUser Account Control:\t-\n")
events.append(sec(4742, DC, ts(600), {**ADMIN, "TargetUserName": "PHSRV-ERP01$",
    "TargetDomainName": DOM, "TargetSid": SID + "-3116", "SamAccountName": "PHSRV-ERP01$",
    "ServicePrincipalNames": "-", "PrivilegeList": "-"}, M4742_SPN, "User Account Management"))
M4742_DEL = ("A computer account was changed.\n\nSubject:\n" + subj() + "\n"
    "Computer That Was Changed:\n\tSecurity ID:\t\t" + SID + "-3117\n"
    "\tAccount Name:\t\tPHWS-117$\n\tAccount Domain:\t\t" + DOM + "\n\n"
    "Changed Attributes:\n\tSAM Account Name:\tPHWS-117$\n"
    "\tAllowed To Delegate To:\n\t\tPrevious Value: -\n"
    "\t\tNew Value: cifs/PHDC02.phantom.lab;ldap/PHDC02.phantom.lab\n")
events.append(sec(4742, DC, ts(580), {**ADMIN, "TargetUserName": "PHWS-117$",
    "TargetDomainName": DOM, "TargetSid": SID + "-3117", "SamAccountName": "PHWS-117$",
    "AllowedToDelegateTo": "cifs/PHDC02.phantom.lab;ldap/PHDC02.phantom.lab",
    "PrivilegeList": "-"}, M4742_DEL, "User Account Management"))

# ---- E. 4616 on the DC ---------------------------------------------------------
events.append(sec(4616, DC, ts(550), {
    "SubjectUserSid": SID + "-3210", "SubjectUserName": "k.alsayed",
    "SubjectDomainName": DOM, "SubjectLogonId": "0xD40001", "ProcessId": "0x4f4",
    "ProcessName": "C:\\Windows\\System32\\w32time.exe",
    "NewTime": ts(550), "PreviousTime": "2026-09-28T11:00:00.000Z"},
    "The system time was changed.\n\nSubject:\n" + subj("k.alsayed", SID + "-3210", "0xD40001") +
    "\nProcess Information:\n\tProcess ID:\t\t0x4f4\n"
    "\tProcess Name:\t\tC:\\Windows\\System32\\w32time.exe\n\n"
    "New Time:\t\t" + ts(550) + "\nPrevious Time:\t\t2026-09-28T11:00:00.000Z",
    "Security State Change"))

# ---- F. 4724 sensitive reset attempts x3 ---------------------------------------
for i in range(3):
    events.append(sec(4724, DC, ts(520 - i * 25), {
        "SubjectUserSid": SID + "-3207", "SubjectUserName": "helpdesk.temp",
        "SubjectDomainName": DOM, "SubjectLogonId": "0x9C33%02d" % i,
        "TargetUserName": "adm.malwadi", "TargetDomainName": DOM, "TargetSid": SID + "-1128"},
        "An attempt was made to reset an account's password.\n\nSubject:\n" +
        subj("helpdesk.temp", SID + "-3207", "0x9C33%02d" % i) + "\n"
        "Target Account:\n\tSecurity ID:\t\t" + SID + "-1128\n"
        "\tAccount Name:\t\tadm.malwadi\n\tAccount Domain:\t\t" + DOM,
        "User Account Management"))

# ---- G. short-lived account, tight timing --------------------------------------
for eid, verb, t in [(4720, "created", 480), (4726, "deleted", 300)]:
    m = ("A user account was %s.\n\nSubject:\n" % verb) + subj() + "\n" + \
        ("New Account:" if eid == 4720 else "Target Account:") + \
        "\n\tSecurity ID:\t\t" + SID + "-3213\n\tAccount Name:\t\ttmp.deploy77\n" \
        "\tAccount Domain:\t\t" + DOM
    events.append(sec(eid, DC, ts(t), {**ADMIN, "TargetUserName": "tmp.deploy77",
        "TargetDomainName": DOM, "TargetSid": SID + "-3213",
        "SamAccountName": "tmp.deploy77", "PrivilegeList": "-"}, m, "User Account Management"))

# ---- H. 4662 System Management Container (#53) ---------------------------------
SMC = "CN=System Management,CN=System,DC=phantom,DC=lab"
M4662_SMC = ("An operation was performed on an object.\n\nSubject :\n" + subj() + "\n"
    "Object:\n\tObject Server:\t\tDS\n\tObject Type:\t\t%{9679f791-0de6-11d0-a285-00aa003049e2}\n"
    f"\tObject Name:\t\t{SMC}\n\tHandle ID:\t\t0x0\n\n"
    "Operation:\n\tOperation Type:\t\tObject Access\n\tAccess Mask:\t\t0x20\n"
    f"\tProperties:\t\t{{bf967950-0de6-11d0-a285-00aa003049e2}}\n\t\t\t{SMC}\n\n"
    "Additional Information:\n\tParameter 1:\t\t-\n\tParameter 2:\t\t-")
events.append(sec(4662, DC, ts(430), {
    "SubjectUserSid": SID + "-1128", "SubjectUserName": "adm.malwadi",
    "SubjectDomainName": DOM, "SubjectLogonId": "0x73B226", "ObjectServer": "DS",
    "ObjectType": "%{9679f791-0de6-11d0-a285-00aa003049e2}", "ObjectName": SMC,
    "HandleId": "0x0", "OperationType": "Object Access", "AccessMask": "0x20",
    "Properties": "{bf967950-0de6-11d0-a285-00aa003049e2}", "Parameter1": "-",
    "Parameter2": "-"}, M4662_SMC, "Directory Service Access"))

# ---- I. 4768 PKINIT (#26) -------------------------------------------------------
M4768_CERT = M4768.replace("Account Name:\t\tPHDC02$", "Account Name:\t\tpkinit.user").replace(
    SID + "-3115", SID + "-3310").replace("10.20.63.115", "10.20.63.30").replace(
    "Certificate Issuer Name:\t\t-", "Certificate Issuer Name:\t\tCN=phantom-PHDC02-CA, DC=phantom, DC=lab").replace(
    "Certificate Serial Number:\t-", "Certificate Serial Number:\t6A00F1B2C3D4E5").replace(
    "Certificate Thumbprint:\t\t-", "Certificate Thumbprint:\t\t9F8E7D6C5B4A39281706F5E4D3C2B1A09F8E7D6C")
events.append(sec(4768, DC, ts(410), {
    "TargetUserName": "pkinit.user", "TargetDomainName": "PHANTOM.LAB",
    "TargetSid": SID + "-3310", "ServiceName": "krbtgt", "ServiceSid": SID + "-502",
    "TicketOptions": "0x40810010", "Status": "0x0", "TicketEncryptionType": "0x12",
    "PreAuthType": "16", "IpAddress": "::ffff:10.20.63.30", "IpPort": "57200",
    "CertIssuerName": "CN=phantom-PHDC02-CA, DC=phantom, DC=lab",
    "CertSerialNumber": "6A00F1B2C3D4E5",
    "CertThumbprint": "9F8E7D6C5B4A39281706F5E4D3C2B1A09F8E7D6C"}, M4768_CERT,
    "Kerberos Authentication Service"))

# ---- J. single-account lockout storm -------------------------------------------
for i in range(12):
    events.append(sec(4740, DC, ts(380 - i * 20), {
        "SubjectUserSid": "S-1-5-18", "SubjectUserName": DC + "$",
        "SubjectDomainName": DOM, "SubjectLogonId": "0x3E7",
        "TargetUserName": "svc.monitoring", "TargetDomainName": DOM,
        "TargetSid": SID + "-3214"},
        "A user account was locked out.\n\nSubject:\n" + subj("SYSTEM", "S-1-5-18", "0x3E7") + "\n"
        "Account That Was Locked Out:\n\tSecurity ID:\t\t" + SID + "-3214\n"
        "\tAccount Name:\t\tsvc.monitoring\n\nAdditional Information:\n"
        "\tCaller Computer Name:\t\tPHWS-021", "User Lockout"))

r = call_tool("wec-sender.send_events", {"events": events}, timeout=240)
res = r["result"]
print(json.dumps({k: res.get(k) for k in ("ok", "events", "sent", "envelopes")}))
print("computers:", json.dumps(res.get("computers"))[:200])
