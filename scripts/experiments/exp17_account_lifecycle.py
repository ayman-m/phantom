"""Exp 17: account-lifecycle + Kerberos detector batch over native WEC.

Catalog-informed shapes for unfired WEC detectors (docs/research/analytics-detector-catalog-2026-09-30.json).
All are Identity Analytics / Identity Threat Module gated, but DCSync/lockouts/weak-tickets proved
that gating is not absolute. Distinct personas per variant for attribution.

  A. Suspicious hidden user created (Medium, single): 4720, account name ends in $
  B. Masquerading as a default local account (Low, single): 4720 local DefaultAccount + Guest
  C. Multiple suspicious user accounts created (Low, 1h): 6x 4720, one subject
  D. User added to a group and removed (Info, 10h): 4728 backdated -9h, 4729 now
  E. Multiple TGT requests w/o pre-auth / AS-REP (Info, 10min): 8x 4768 PreAuthType 0
  F. A user requested multiple service tickets (Info, 10min): 15x 4769 AES 0x12
  G. Suspicious dNSHostName change to DC name (Medium, single): 4742
  H. AdminSDHolder ACL (Low, single): 4662 WRITE_DAC on CN=AdminSDHolder
  I. SID History added (Info, single): 4765
  J. Computer promoted to DC (Low, single): 4742 UAC -> 0x82000
  K. Rare machine account creation (Info, single): 4741 by first-time creator
  L. Unusual user account unlock (Info, single): 4767 by unusual user
  M. Local group enumeration (Info, 5min): 10x 4799 on a fresh host
"""
import json, os, sys, datetime
sys.path.insert(0, os.path.expanduser("~/Documents/Phantom"))
from stc_api import call_tool

NOW = datetime.datetime.now(datetime.timezone.utc)
def ts(d): return (NOW - datetime.timedelta(seconds=d)).strftime("%Y-%m-%dT%H:%M:%SZ")
DOM, DC, SEC = "PHANTOM", "PHDC02", "Microsoft-Windows-Security-Auditing"
SID = "S-1-5-21-3623811015-3361044348-30300820"

def sec(eid, computer, t, data, msg, task):
    return {"event_id": eid, "computer": computer, "time": t, "provider": SEC,
            "rendering": {"message": msg, "task": task}, "event_data": data}

def subj(name, rid, logon):
    return (f"\tSecurity ID:\t\t{SID}-{rid}\n\tAccount Name:\t\t{name}\n"
            f"\tAccount Domain:\t\t{DOM}\n\tLogon ID:\t\t{logon}\n")

def actor(rid, name, logon):
    return {"SubjectUserSid": f"{SID}-{rid}", "SubjectUserName": name,
            "SubjectDomainName": DOM, "SubjectLogonId": logon}

events = []

# ---- A. hidden user: name mimics a machine account -------------------------------
events.append(sec(4720, DC, ts(600), {**actor(3501, "adm.zahrani", "0x7A1101"),
    "TargetUserName": "svcprint$", "TargetDomainName": DOM, "TargetSid": SID + "-3502",
    "SamAccountName": "svcprint$", "DisplayName": "-", "UserPrincipalName": "-",
    "PrivilegeList": "-"},
    "A user account was created.\n\nSubject:\n" + subj("adm.zahrani", 3501, "0x7A1101") + "\n"
    "New Account:\n\tSecurity ID:\t\t" + SID + "-3502\n\tAccount Name:\t\tsvcprint$\n"
    "\tAccount Domain:\t\t" + DOM + "\n\nAttributes:\n\tSAM Account Name:\tsvcprint$\n"
    "\tDisplay Name:\t\t-\n\tUser Principal Name:\t-",
    "User Account Management"))

# ---- B. default local account masquerade (DefaultAccount + Guest) ----------------
for name, rid, t in [("DefaultAccount", 3503, 580), ("Guest", 3504, 570)]:
    events.append(sec(4720, "PHSRV-WEB01", ts(t), {**actor(3501, "adm.zahrani", "0x7A1101"),
        "TargetUserName": name, "TargetDomainName": "PHSRV-WEB01",
        "TargetSid": "S-1-5-21-7654321-7654321-7654321-%d" % rid,
        "SamAccountName": name, "PrivilegeList": "-"},
        "A user account was created.\n\nSubject:\n" + subj("adm.zahrani", 3501, "0x7A1101") + "\n"
        "New Account:\n\tSecurity ID:\t\tS-1-5-21-7654321-7654321-7654321-%d\n" % rid +
        "\tAccount Name:\t\t" + name + "\n\tAccount Domain:\t\tPHSRV-WEB01\n\n"
        "Attributes:\n\tSAM Account Name:\t" + name, "User Account Management"))

# ---- C. multiple suspicious creations (1h) ----------------------------------------
for i in range(6):
    nm = "rare.svc%02d" % i
    events.append(sec(4720, DC, ts(560 - i * 20), {**actor(3505, "provision.bot", "0x7B2201"),
        "TargetUserName": nm, "TargetDomainName": DOM, "TargetSid": SID + "-36%02d" % i,
        "SamAccountName": nm, "DisplayName": "-", "UserPrincipalName": "-",
        "PrivilegeList": "-"},
        "A user account was created.\n\nSubject:\n" + subj("provision.bot", 3505, "0x7B2201") + "\n"
        "New Account:\n\tSecurity ID:\t\t" + SID + "-36%02d\n" % i +
        "\tAccount Name:\t\t" + nm + "\n\tAccount Domain:\t\t" + DOM,
        "User Account Management"))

# ---- D. group add (backdated 9h) then remove (now), 10h window --------------------
for eid, verb, t in [(4728, "added to", 32400), (4729, "removed from", 60)]:
    events.append(sec(eid, DC, ts(t), {**actor(3507, "adm.harbi", "0x7C3301"),
        "MemberName": "CN=F. Otaibi,OU=Users,DC=phantom,DC=lab",
        "MemberSid": SID + "-3508", "TargetUserName": "Server Operators",
        "TargetDomainName": DOM, "TargetSid": SID + "-549", "PrivilegeList": "-"},
        "A member was %s a security-enabled global group.\n\nSubject:\n" % verb +
        subj("adm.harbi", 3507, "0x7C3301") + "\n"
        "Member:\n\tSecurity ID:\t\t" + SID + "-3508\n"
        "\tAccount Name:\t\tCN=F. Otaibi,OU=Users,DC=phantom,DC=lab\n\n"
        "Group:\n\tSecurity ID:\t\t" + SID + "-549\n\tGroup Name:\t\tServer Operators\n"
        "\tGroup Domain:\t\t" + DOM + "\n\nAdditional Information:\n\tPrivileges:\t\t-",
        "Security Group Management"))

# ---- E. AS-REP: 8x 4768 PreAuthType 0 (10 min) -------------------------------------
for i in range(8):
    u = "asrep.victim%d" % i
    events.append(sec(4768, DC, ts(540 - i * 30), {
        "TargetUserName": u, "TargetDomainName": "PHANTOM.LAB",
        "TargetSid": SID + "-37%02d" % i, "ServiceName": "krbtgt",
        "ServiceSid": SID + "-502", "TicketOptions": "0x40810010", "Status": "0x0",
        "TicketEncryptionType": "0x17", "PreAuthType": "0",
        "IpAddress": "::ffff:10.20.63.40", "IpPort": str(58000 + i)},
        "A Kerberos authentication ticket (TGT) was requested.\n\nAccount Information:\n"
        "\tAccount Name:\t\t%s\n\tSupplied Realm Name:\t\tPHANTOM.LAB\n\tUser ID:\t\t\t"
        % u + SID + "-37%02d\n\n" % i +
        "Service Information:\n\tService Name:\t\tkrbtgt\n\tService ID:\t\t" + SID + "-502\n\n"
        "Network Information:\n\tClient Address:\t\t::ffff:10.20.63.40\n\tClient Port:\t\t%d\n\n"
        % (58000 + i) +
        "Additional Information:\n\tTicket Options:\t\t0x40810010\n\tResult Code:\t\t0x0\n"
        "\tTicket Encryption Type:\t0x17\n\tPre-Authentication Type:\t0\n\n"
        "Certificate Information:\n\tCertificate Issuer Name:\t\t-\n"
        "\tCertificate Serial Number:\t-\n\tCertificate Thumbprint:\t\t-",
        "Kerberos Authentication Service"))

# ---- F. multiple service tickets, AES (10 min) -------------------------------------
SPNS = ["HTTP/intranet.phantom.lab", "HTTP/portal.phantom.lab", "CIFS/PHSRV-FS01.phantom.lab",
        "CIFS/PHSRV-FS02.phantom.lab", "LDAP/PHDC01.phantom.lab", "LDAP/PHDC02.phantom.lab",
        "MSSQLSvc/PHSRV-SQL01.phantom.lab:1433", "MSSQLSvc/PHSRV-SQL03.phantom.lab:1433",
        "HOST/PHSRV-APP01.phantom.lab", "HOST/PHSRV-APP02.phantom.lab",
        "HTTP/hr.phantom.lab", "HTTP/finance.phantom.lab", "CIFS/PHSRV-FS03.phantom.lab",
        "WSMAN/PHSRV-APP01.phantom.lab", "TERMSRV/PHSRV-APP02.phantom.lab"]
for i, spn in enumerate(SPNS):
    events.append(sec(4769, DC, ts(520 - i * 20), {
        "TargetUserName": "ticket.harvester@PHANTOM.LAB", "TargetDomainName": "PHANTOM.LAB",
        "ServiceName": spn, "ServiceSid": SID + "-1105", "TicketOptions": "0x40810000",
        "TicketEncryptionType": "0x12", "IpAddress": "::ffff:10.20.63.41",
        "IpPort": str(59000 + i), "Status": "0x0",
        "LogonGuid": "{a17%05d-b22c-4e5f-8a00-%012x}" % (i, i), "TransmittedServices": "-"},
        "A Kerberos service ticket was requested.\n\nAccount Information:\n"
        "\tAccount Name:\t\tticket.harvester@PHANTOM.LAB\n\tAccount Domain:\t\tPHANTOM.LAB\n\n"
        "Service Information:\n\tService Name:\t\t" + spn + "\n\tService ID:\t\t" + SID + "-1105\n\n"
        "Network Information:\n\tClient Address:\t\t::ffff:10.20.63.41\n\tClient Port:\t\t%d\n\n"
        % (59000 + i) +
        "Additional Information:\n\tTicket Options:\t\t0x40810000\n\tTicket Encryption Type:\t0x12\n"
        "\tFailure Code:\t\t0x0\n\tTransited Services:\t-",
        "Kerberos Service Ticket Operations"))

# ---- G. dNSHostName changed to the DC's name (Medium, single) ----------------------
events.append(sec(4742, DC, ts(480), {**actor(3509, "adm.zahrani", "0x7A1109"),
    "TargetUserName": "PHWS-220$", "TargetDomainName": DOM, "TargetSid": SID + "-3510",
    "SamAccountName": "PHWS-220$", "DnsHostName": "PHDC02.phantom.lab", "PrivilegeList": "-"},
    "A computer account was changed.\n\nSubject:\n" + subj("adm.zahrani", 3509, "0x7A1109") + "\n"
    "Computer That Was Changed:\n\tSecurity ID:\t\t" + SID + "-3510\n"
    "\tAccount Name:\t\tPHWS-220$\n\tAccount Domain:\t\t" + DOM + "\n\n"
    "Changed Attributes:\n\tSAM Account Name:\tPHWS-220$\n"
    "\tDNS Host Name:\n\t\tPrevious Value: PHWS-220.phantom.lab\n"
    "\t\tNew Value: PHDC02.phantom.lab\n",
    "User Account Management"))

# ---- H. AdminSDHolder ACL (WRITE_DAC) ----------------------------------------------
ADSDH = "CN=AdminSDHolder,CN=System,DC=phantom,DC=lab"
events.append(sec(4662, DC, ts(460), {
    **actor(3511, "priv.escalator", "0x7D4401"), "ObjectServer": "DS",
    "ObjectType": "container", "ObjectName": ADSDH, "HandleId": "0x0",
    "OperationType": "Object Access", "AccessMask": "0x40000",
    "Properties": "WRITE_DAC", "Parameter1": "-", "Parameter2": "-"},
    "An operation was performed on an object.\n\nSubject :\n" +
    subj("priv.escalator", 3511, "0x7D4401") + "\n"
    "Object:\n\tObject Server:\t\tDS\n\tObject Type:\t\tcontainer\n"
    "\tObject Name:\t\t" + ADSDH + "\n\tHandle ID:\t\t0x0\n\n"
    "Operation:\n\tOperation Type:\t\tObject Access\n\tAccess Mask:\t\t0x40000\n"
    "\tProperties:\t\tWRITE_DAC\n\t\t\t" + ADSDH + "\n\n"
    "Additional Information:\n\tParameter 1:\t\t-\n\tParameter 2:\t\t-",
    "Directory Service Access"))

# ---- I. SID History added (4765) ----------------------------------------------------
events.append(sec(4765, DC, ts(440), {
    **actor(3512, "migrate.admin", "0x7E5501"),
    "TargetUserName": "legacy.migrated", "TargetDomainName": DOM, "TargetSid": SID + "-3513",
    "SidHistory": "S-1-5-21-1111111111-2222222222-3333333333-500", "PrivilegeList": "-"},
    "SID History was added to an account.\n\nSubject:\n" + subj("migrate.admin", 3512, "0x7E5501") + "\n"
    "Target Account:\n\tSecurity ID:\t\t" + SID + "-3513\n"
    "\tAccount Name:\t\tlegacy.migrated\n\tAccount Domain:\t\t" + DOM + "\n\n"
    "New SID:\n\tSID History:\t\tS-1-5-21-1111111111-2222222222-3333333333-500",
    "User Account Management"))

# ---- J. computer promoted to DC (UAC 0x82000) ---------------------------------------
events.append(sec(4742, DC, ts(420), {**actor(3514, "adm.zahrani", "0x7A1114"),
    "TargetUserName": "PHSRV-ROGUE$", "TargetDomainName": DOM, "TargetSid": SID + "-3515",
    "SamAccountName": "PHSRV-ROGUE$", "UserAccountControl": "0x82000", "PrivilegeList": "-"},
    "A computer account was changed.\n\nSubject:\n" + subj("adm.zahrani", 3514, "0x7A1114") + "\n"
    "Computer That Was Changed:\n\tSecurity ID:\t\t" + SID + "-3515\n"
    "\tAccount Name:\t\tPHSRV-ROGUE$\n\tAccount Domain:\t\t" + DOM + "\n\n"
    "Changed Attributes:\n\tSAM Account Name:\tPHSRV-ROGUE$\n"
    "\tUser Account Control:\n\t\tPrevious Value: 0x1000\n\t\tNew Value: 0x82000\n",
    "User Account Management"))

# ---- K. rare machine account creation -------------------------------------------------
events.append(sec(4741, DC, ts(400), {**actor(3516, "intern.first", "0x7F6601"),
    "TargetUserName": "PHWS-INT01$", "TargetDomainName": DOM, "TargetSid": SID + "-3517",
    "SamAccountName": "PHWS-INT01$", "DisplayName": "-", "UserPrincipalName": "-",
    "PrivilegeList": "-"},
    "A computer account was created.\n\nSubject:\n" + subj("intern.first", 3516, "0x7F6601") + "\n"
    "New Computer Account:\n\tSecurity ID:\t\t" + SID + "-3517\n"
    "\tAccount Name:\t\tPHWS-INT01$\n\tAccount Domain:\t\t" + DOM,
    "Computer Account Management"))

# ---- L. unusual account unlock (4767) -------------------------------------------------
events.append(sec(4767, DC, ts(380), {**actor(3518, "night.shift", "0x7A7701"),
    "TargetUserName": "cfo.assistant", "TargetDomainName": DOM, "TargetSid": SID + "-3519"},
    "A user account was unlocked.\n\nSubject:\n" + subj("night.shift", 3518, "0x7A7701") + "\n"
    "Target Account:\n\tSecurity ID:\t\t" + SID + "-3519\n"
    "\tAccount Name:\t\tcfo.assistant\n\tAccount Domain:\t\t" + DOM,
    "User Account Management"))

# ---- M. local group enumeration burst on fresh host (5 min) ---------------------------
GROUPS = ["Administrators", "Remote Desktop Users", "Backup Operators", "Power Users",
          "Server Operators", "Account Operators", "Print Operators", "Distributed COM Users",
          "Event Log Readers", "Remote Management Users"]
for i, g in enumerate(GROUPS):
    events.append(sec(4799, "PHWS-330", ts(360 - i * 20), {
        **actor(3520, "recon.local", "0x7A8801"), "TargetUserName": g,
        "TargetDomainName": "PHWS-330", "CallerProcessId": "0x21a4",
        "CallerProcessName": "C:\\Windows\\System32\\net1.exe"},
        "A security-enabled local group membership was enumerated.\n\nSubject:\n" +
        subj("recon.local", 3520, "0x7A8801") + "\nGroup:\n\tGroup Name:\t\t" + g + "\n\n"
        "Process Information:\n\tProcess ID:\t\t0x21a4\n"
        "\tProcess Name:\t\tC:\\Windows\\System32\\net1.exe",
        "Security Group Management"))

r = call_tool("wec-sender.send_events", {"events": events}, timeout=240)
res = r["result"]
print(json.dumps({k: res.get(k) for k in ("ok", "events", "sent", "envelopes")}))
