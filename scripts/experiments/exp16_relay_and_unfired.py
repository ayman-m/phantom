"""Exp 16: catalog-informed retry of the detectors that did NOT fire in Exp 8-15.

Research basis: docs/research/analytics-detector-catalog-2026-09-30.json
  - "NTLM Relay" / "Machine Account NTLM Relay" (PAN traffic, 10 min): NTProofStr seen
    from more than one source -> same user/machine from 2+ source IPs in the window.
  - "Possible Kerberos relay attack" (WEC, single event): investigative hint says
    "look for a NEW MACHINE that was added to the domain" -> prepend 4741 computer
    creation, then relay logon for that machine account.
  - "Suspicious sAMAccountName change" (WEC, single): machine account renamed to a
    sAMAccountName MISSING the trailing dollar sign (Exp 15 renamed WITH $ -> miss).
  - "SPNs cleared from a machine account" (WEC, single): retry 4742 + add 5136
    Directory Service Changes variant (attribute value deleted).
  - "Sensitive account password reset attempt" (WEC, single): target built-in
    sensitive accounts (Administrator -500, krbtgt -502) instead of a custom admin.
  - "Suspicious access of the System Management Container" (WEC, single): retry 4662
    with a NON-admin subject and read access mask.
  - "Kerberos User Enumeration" (PAN traffic, 1h): high volume of kerberos traffic
    from one host to the DC (principal-unknown errors not expressible in CEF traffic;
    best-effort shape).
  - "Possible Kerberoasting without SPNs" (PAN traffic, single): weak-encryption
    kerberos TGS shape; best-effort over CEF traffic.
  - "Multiple user accounts were deleted" (WEC, 1h): 6x 4726 (not yet tried).

Distinct users/hosts per variant for attribution.
LDAP admin enumeration is EXCLUDED: confirmed 1644 events land in
microsoft_windows_raw but never model into XDM (checked 2026-10-04), so the
detector's input fields never populate over WEC. Needs the Directory Service
channel parsing/modeling gap addressed in content, or an EAL/agent feed.
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

def subj(name="adm.malwadi", sid=SID + "-1128", logon="0x73B226"):
    return (f"\tSecurity ID:\t\t{sid}\n\tAccount Name:\t\t{name}\n"
            f"\tAccount Domain:\t\t{DOM}\n\tLogon ID:\t\t{logon}\n")

ADMIN = {"SubjectUserSid": SID + "-1128", "SubjectUserName": "adm.malwadi",
         "SubjectDomainName": DOM, "SubjectLogonId": "0x73B226"}

events = []

# ---- A. Kerberos relay WITH new-machine story -----------------------------------
# 4741: attacker creates machine account PHWS-RELAY$ (KrbRelay / relay+shadow creds kill chain)
M4741 = ("A computer account was created.\n\nSubject:\n" + subj("relay.operator", SID + "-3401", "0x8A1102") + "\n"
         "New Computer Account:\n\tSecurity ID:\t\t" + SID + "-3402\n"
         "\tAccount Name:\t\tPHWS-RELAY$\n\tAccount Domain:\t\t" + DOM + "\n\n"
         "Attributes:\n\tSAM Account Name:\tPHWS-RELAY$\n\tDisplay Name:\t\t-\n"
         "\tUser Principal Name:\t-\n\tHome Directory:\t\t-\n\n"
         "Additional Information:\n\tPrivileges:\t\t-")
events.append(sec(4741, DC, ts(300), {
    "SubjectUserSid": SID + "-3401", "SubjectUserName": "relay.operator",
    "SubjectDomainName": DOM, "SubjectLogonId": "0x8A1102",
    "TargetUserName": "PHWS-RELAY$", "TargetDomainName": DOM, "TargetSid": SID + "-3402",
    "SamAccountName": "PHWS-RELAY$", "DisplayName": "-", "UserPrincipalName": "-",
    "PrivilegeList": "-"}, M4741, "Computer Account Management"))

# 4624: the freshly-created machine account logs on to a server over the network,
# sourced from a loopback/self address (relay signature)
events.append({"event_id": 4624, "computer": "PHSRV-FS01", "time": ts(280), "event_data": {
    "SubjectUserSid": "S-1-5-18", "SubjectUserName": "PHSRV-FS01$",
    "SubjectDomainName": DOM, "SubjectLogonId": "0x3E7",
    "TargetUserSid": SID + "-3402", "TargetUserName": "PHWS-RELAY$",
    "TargetDomainName": DOM, "TargetLogonId": "0x8A2201",
    "LogonType": "3", "LogonProcessName": "Kerberos", "AuthenticationPackageName": "Kerberos",
    "WorkstationName": "PHWS-RELAY", "IpAddress": "127.0.0.1", "IpPort": "49152"}})

# ---- B. sAMAccountName change WITHOUT trailing $ --------------------------------
M4781 = ("The name of an account was changed:\n\nSubject:\n" + subj() + "\n"
         "Account Whose Name Was Changed:\n\tSecurity ID:\t\t" + SID + "-3403\n"
         "\tOld Account Name:\tPHWS-210$\n\tNew Account Name:\tPHWS-210")
events.append(sec(4781, DC, ts(260), {**ADMIN, "OldTargetUserName": "PHWS-210$",
    "NewTargetUserName": "PHWS-210", "TargetSid": SID + "-3403"}, M4781,
    "User Account Management"))

# ---- C. SPNs cleared: 4742 + 5136 variant ---------------------------------------
M4742_SPN = ("A computer account was changed.\n\nSubject:\n" + subj() + "\n"
    "Computer That Was Changed:\n\tSecurity ID:\t\t" + SID + "-3404\n"
    "\tAccount Name:\t\tPHSRV-SQL02$\n\tAccount Domain:\t\t" + DOM + "\n\n"
    "Changed Attributes:\n\tSAM Account Name:\tPHSRV-SQL02$\n"
    "\tService Principal Names:\n"
    "\t\tPrevious Value: MSSQLSvc/PHSRV-SQL02.phantom.lab:1433;MSSQLSvc/PHSRV-SQL02.phantom.lab\n"
    "\t\tNew Value: -\n")
events.append(sec(4742, DC, ts(240), {**ADMIN, "TargetUserName": "PHSRV-SQL02$",
    "TargetDomainName": DOM, "TargetSid": SID + "-3404", "SamAccountName": "PHSRV-SQL02$",
    "ServicePrincipalNames": "-", "PrivilegeList": "-"}, M4742_SPN, "User Account Management"))

M5136 = ("A directory service object was modified.\n\nSubject:\n" + subj() + "\n"
    "Object:\n\tObject DN:\tCN=PHSRV-SQL02,OU=Servers,DC=phantom,DC=lab\n"
    "\tObject GUID:\t{8f3a1b2c-4d5e-6f70-8192-a3b4c5d6e7f8}\n\tObject Class:\tcomputer\n\n"
    "Attribute:\n\tLDAP Display Name:\tservicePrincipalName\n"
    "\tSyntax (OID):\t2.5.5.4\n\tValue:\tMSSQLSvc/PHSRV-SQL02.phantom.lab:1433\n\n"
    "Operation:\n\tType:\t\tValue Deleted\n\tCorrelation ID:\t{2b4c6d8e-1f2a-3b4c-5d6e-7f8091a2b3c4}")
events.append(sec(5136, DC, ts(230), {**ADMIN,
    "ObjectDN": "CN=PHSRV-SQL02,OU=Servers,DC=phantom,DC=lab",
    "ObjectGUID": "{8f3a1b2c-4d5e-6f70-8192-a3b4c5d6e7f8}", "ObjectClass": "computer",
    "AttributeLDAPDisplayName": "servicePrincipalName",
    "AttributeValue": "MSSQLSvc/PHSRV-SQL02.phantom.lab:1433",
    "OperationType": "Value Deleted"}, M5136, "Directory Service Changes"))

# ---- D. Sensitive password resets: Administrator + krbtgt ------------------------
for tgt, tsid, t in [("Administrator", SID + "-500", 210), ("krbtgt", SID + "-502", 190)]:
    events.append(sec(4724, DC, ts(t), {
        "SubjectUserSid": SID + "-3405", "SubjectUserName": "helpdesk.temp",
        "SubjectDomainName": DOM, "SubjectLogonId": "0x9C55%02d" % t,
        "TargetUserName": tgt, "TargetDomainName": DOM, "TargetSid": tsid},
        "An attempt was made to reset an account's password.\n\nSubject:\n" +
        subj("helpdesk.temp", SID + "-3405", "0x9C55%02d" % t) + "\n"
        "Target Account:\n\tSecurity ID:\t\t" + tsid + "\n"
        "\tAccount Name:\t\t" + tgt + "\n\tAccount Domain:\t\t" + DOM,
        "User Account Management"))

# ---- E. System Management Container access, non-admin subject ---------------------
SMC = "CN=System Management,CN=System,DC=phantom,DC=lab"
M4662 = ("An operation was performed on an object.\n\nSubject :\n" +
    subj("sccm.recon", SID + "-3406", "0x7B3301") + "\n"
    "Object:\n\tObject Server:\t\tDS\n\tObject Type:\t\tcontainer\n"
    f"\tObject Name:\t\t{SMC}\n\tHandle ID:\t\t0x0\n\n"
    "Operation:\n\tOperation Type:\t\tObject Access\n\tAccess Mask:\t\t0x10\n"
    f"\tProperties:\t\t{{bf967950-0de6-11d0-a285-00aa003049e2}}\n\t\t\t{SMC}\n\n"
    "Additional Information:\n\tParameter 1:\t\t-\n\tParameter 2:\t\t-")
events.append(sec(4662, DC, ts(170), {
    "SubjectUserSid": SID + "-3406", "SubjectUserName": "sccm.recon",
    "SubjectDomainName": DOM, "SubjectLogonId": "0x7B3301", "ObjectServer": "DS",
    "ObjectType": "container", "ObjectName": SMC, "HandleId": "0x0",
    "OperationType": "Object Access", "AccessMask": "0x10",
    "Properties": "{bf967950-0de6-11d0-a285-00aa003049e2}"}, M4662,
    "Directory Service Access"))

# ---- F. Multiple user accounts deleted (Info, 1h) ---------------------------------
for i in range(6):
    name = "tmp.sweep%02d" % i
    events.append(sec(4726, DC, ts(150 - i * 15), {
        **ADMIN, "TargetUserName": name, "TargetDomainName": DOM,
        "TargetSid": SID + "-35%02d" % i, "PrivilegeList": "-"},
        "A user account was deleted.\n\nSubject:\n" + subj() + "\n"
        "Target Account:\n\tSecurity ID:\t\t" + SID + "-35%02d\n" % i +
        "\tAccount Name:\t\t" + name + "\n\tAccount Domain:\t\t" + DOM,
        "User Account Management"))

r = call_tool("wec-sender.send_events", {"events": events}, timeout=240)
res = r["result"]
print(json.dumps({k: res.get(k) for k in ("ok", "events", "sent", "envelopes")}))

# ---- G/H. PAN traffic workers: NTLM relay + kerberos shapes ----------------------
DEST = "logdest:217fa292-3beb-49fd-ba8b-5cbd9e84341f"
SCHEMA = [{"name": n, "type": t} for n, t in [
    ("action", "string"), ("app", "string"), ("dest_ip", "ipv4"), ("dest_port", "integer"),
    ("protocol", "string"), ("source_device_host", "string"), ("source_ip", "ipv4"),
    ("source_port", "integer"), ("source_user", "string"), ("bytes_sent", "integer"),
    ("bytes_received", "integer"), ("log_type", "string"), ("sub_type", "string"),
    ("rule_matched", "string"), ("from_zone", "string"), ("to_zone", "string"),
    ("packets_sent", "integer"), ("packets_received", "integer"),
    ("total_time_elapsed", "integer"), ("session_id", "integer")]]

def base_obs(**over):
    obs = {
        "log_type": ["TRAFFIC"], "sub_type": ["end"], "protocol": ["tcp"],
        "action": ["allow"], "rule_matched": ["allow-internal"],
        "from_zone": ["trust"], "to_zone": ["trust"],
        "bytes_sent": ["2400", "9600"], "bytes_received": ["48000", "180000"],
        "packets_sent": ["30", "120"], "packets_received": ["45", "200"],
        "total_time_elapsed": ["3", "12", "45"],
        "session_id": [str(810000 + i) for i in range(64)],
    }
    obs.update(over)
    return obs

WORKERS = [
    # NTLM Relay: same user seen from TWO source IPs inside 10 minutes
    ("exp16-ntlm-relay-user", 8, 45, base_obs(
        source_ip=["10.20.63.31", "10.20.63.32"],
        source_device_host=["WS-STCE-31", "WS-STCE-32"],
        source_user=["stc\\relay.victim"],
        dest_ip=["10.20.0.12"], dest_port=["445", "389"],
        app=["ntlm", "smb", "ldap"])),
    # Machine Account NTLM Relay: machine account from TWO source IPs
    ("exp16-ntlm-relay-machine", 8, 45, base_obs(
        source_ip=["10.20.63.33", "10.20.63.34"],
        source_device_host=["PHSRV-APP02", "WS-STCE-34"],
        source_user=["stc\\PHSRV-APP02$"],
        dest_ip=["10.20.0.12"], dest_port=["445", "636"],
        app=["ntlm", "smb", "ldap"])),
    # Kerberos User Enumeration (Medium, 1h): one host hammering the DC on 88
    ("exp16-kerberos-user-enum", 40, 12, base_obs(
        source_ip=["10.20.63.35"], source_device_host=["WS-STCE-35"],
        source_user=["stc\\enum.scanner"],
        dest_ip=["10.20.0.12"], dest_port=["88"], app=["kerberos"])),
    # Kerberoasting without SPNs (single event): weak-enc kerberos TGS shape
    ("exp16-kerberoast-nospn", 6, 30, base_obs(
        source_ip=["10.20.63.36"], source_device_host=["WS-STCE-36"],
        source_user=["stc\\roast.user"],
        dest_ip=["10.20.0.12"], dest_port=["88"], app=["kerberos"])),
]

for name, count, interval, obs in WORKERS:
    r = call_tool("xlog.create_data_worker", {
        "type": "CEF", "vendor": "panw", "product": "ngfw_traffic",
        "destination": DEST, "name": name, "tags": ["experiment", "exp16"],
        "count": count, "interval": interval,
        "schema_override": SCHEMA, "observables_dict": obs,
    }, timeout=120)
    res = r["result"][0] if isinstance(r.get("result"), list) else r.get("result")
    print(f'{name:26s} worker={res.get("worker")} status={res.get("status")} count={res.get("count")}')
