"""Exp 6: machine-account + delegation abuse + TGT burst via Windows CEF.

4741 computer account created (rogue machine account) x1
4742 computer account changed - TrustedForDelegation enabled (delegation_change) x2
4729 member REMOVED from Domain Admins (priv_group_add_remove tail) x1
4768 TGT burst - 20 TGT requests in 60s from one user (irregular_tgt_burst)
"""
import json, datetime, time as _time
from stc_api import call_tool

fields = json.load(open("win_schema_fields.json"))
byname = {f["name"]: f for f in fields}
DEST = "logdest:217fa292-3beb-49fd-ba8b-5cbd9e84341f"
SID_A = "S-1-5-21-1004336348-1177238915-682003330-1100"
USER = "ahmed.alharbi"
DOMSID = "S-1-5-21-1004336348-1177238915-682003330"

BASE = ["time_created", "provider_name", "channel", "event_id", "event_result",
        "activity_id", "computer_name", "host_name", "log_level", "opcode",
        "os_subtype", "provider_guid", "record_id",
        "event_data.Domain", "event_data.FQDN",
        "event_data.SID", "event_data.SubjectDomainName", "event_data.SubjectUserName",
        "event_data.SubjectUserSid", "event_data.TargetDomainName", "event_data.TargetUserName",
        "event_data.TargetUserSid",
        "user.domain", "user.identifier", "user.name", "user.type", "message"]

def base_obs(tc, eid, rid0, n, act):
    return {
        "time_created": [tc], "provider_name": ["Microsoft-Windows-Security-Auditing"],
        "channel": ["Security"], "event_id": [eid], "event_result": ["success"],
        "activity_id": [act], "computer_name": ["DC01.stc.local"], "host_name": ["DC01"],
        "log_level": ["Information"], "opcode": ["Info"],
        "os_subtype": ["Windows Server 2022"],
        "provider_guid": ["{54849625-5478-4994-A5BA-3E3B0328C30D}"],
        "record_id": [str(rid0 + i) for i in range(n)],
        "event_data.Domain": ["STC"], "event_data.FQDN": ["DC01.stc.local"],
        "event_data.SID": [SID_A], "event_data.SubjectDomainName": ["STC"],
        "event_data.SubjectUserName": [USER], "event_data.SubjectUserSid": [SID_A],
        "user.domain": ["STC"], "user.identifier": [SID_A],
        "user.name": [USER], "user.type": ["User"],
    }

def fire(tag, obs, n, extra=None):
    names = BASE + [f for f in (extra or []) if f not in BASE]
    missing = [f for f in names if f not in byname]
    if missing:
        raise SystemExit(f"{tag}: missing schema fields {missing}")
    args = {"type": "CEF", "vendor": "microsoft", "product": "windows",
            "destination": DEST, "count": n, "interval": 1,
            "duration_seconds": 60, "max_events": n,
            "schema_override": [byname[f] for f in names],
            "observables_dict": obs}
    r = call_tool("xlog.create_data_worker", args, timeout=90)
    w = (r.get("result") or [{}])[0]
    print(tag, "->", w.get("worker"), w.get("status"))
    _time.sleep(3)

t0 = datetime.datetime.now(datetime.timezone.utc)

# --- 4741: rogue machine account EVIL-WS01$ created ---
tc = t0.strftime("%Y-%m-%dT%H:%M:%SZ")
m = ("A computer account was created.\n\n"
     "Subject:\n\tSecurity ID:\t\t" + SID_A + "\n\tAccount Name:\t\t" + USER +
     "\n\tAccount Domain:\t\tSTC\n\tLogon ID:\t\t0x1A2B3C\n\n"
     "New Computer Account:\n\tSecurity ID:\t\t" + DOMSID + "-1701\n"
     "\tAccount Name:\t\tEVIL-WS01$\n\tAccount Domain:\t\tSTC\n\n"
     "Attributes:\n\tSAM Account Name:\tEVIL-WS01$\n\tDisplay Name:\t\t-\n"
     "\tDns Host Name:\t\tEVIL-WS01.stc.local\n\tOperating System:\tWindows 11 Pro\n"
     "\tOperating System Version:\t10.0 (22631)\n\n"
     "Additional Information:\n\tPrivileges:\t\t-")
obs = base_obs(tc, "4741", 3900600, 1, "{7d3a91f2-4c8b-4e21-a6d5-b0c447410001}")
obs.update({"event_data.TargetDomainName": ["STC"],
            "event_data.TargetUserName": ["EVIL-WS01$"],
            "event_data.TargetUserSid": [DOMSID + "-1701"],
            "message": [m]})
fire("4741 machine-create", obs, 1)

# --- 4742: delegation enabled on the rogue machine account ---
tc = (t0 + datetime.timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
def m4742(host, sid):
    return ("A computer account was changed.\n\n"
            "Subject:\n\tSecurity ID:\t\t" + SID_A + "\n\tAccount Name:\t\t" + USER +
            "\n\tAccount Domain:\t\tSTC\n\tLogon ID:\t\t0x1A2B3C\n\n"
            "Computer Account That Was Changed:\n\tSecurity ID:\t\t" + sid +
            "\n\tAccount Name:\t\t" + host + "\n\tAccount Domain:\t\tSTC\n\n"
            "Changed Attributes:\n\tSAM Account Name:\t" + host + "\n"
            "\tUser Account Control:\n\t\t'Trusted For Delegation' Enabled\n"
            "\tService Principal Names:\n\t\tHOST/" + host.rstrip("$") + ".stc.local\n\n"
            "Additional Information:\n\tPrivileges:\t\t-")
targets = [("EVIL-WS01$", DOMSID + "-1701"), ("WS-2200$", DOMSID + "-1702")]
obs = base_obs(tc, "4742", 3900610, 2, "{7d3a91f2-4c8b-4e21-a6d5-b0c447420001}")
obs.update({"event_data.TargetDomainName": ["STC"],
            "event_data.TargetUserName": [h for h, _ in targets],
            "event_data.TargetUserSid": [s for _, s in targets],
            "message": [m4742(h, s) for h, s in targets]})
fire("4742 delegation", obs, 2)

# --- 4729: member removed from Domain Admins (add/remove tail) ---
tc = (t0 + datetime.timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
m = ("A member was removed from a security-enabled global group.\n\n"
     "Subject:\n\tSecurity ID:\t\t" + SID_A + "\n\tAccount Name:\t\t" + USER +
     "\n\tAccount Domain:\t\tSTC\n\tLogon ID:\t\t0x1A2B3C\n\n"
     "Member:\n\tSecurity ID:\t\t" + DOMSID + "-1601\n\tAccount Name:\t\tsvc-sql01\n\n"
     "Group:\n\tSecurity ID:\t\t" + DOMSID + "-512\n\tGroup Name:\t\tDomain Admins\n"
     "\tGroup Domain:\t\tSTC\n\n"
     "Additional Information:\n\tPrivileges:\t\t-")
obs = base_obs(tc, "4729", 3900620, 1, "{7d3a91f2-4c8b-4e21-a6d5-b0c447290001}")
obs.update({"event_data.TargetDomainName": ["STC"],
            "event_data.TargetUserName": ["svc-sql01"],
            "event_data.TargetUserSid": [DOMSID + "-1601"],
            "message": [m]})
fire("4729 group-remove", obs, 1)

# --- 4768: irregular TGT burst, 20 in one minute ---
tc = (t0 + datetime.timedelta(seconds=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
m4768 = ("A Kerberos authentication ticket (TGT) was requested.\n\n"
         "Account Information:\n\tAccount Name:\t\t" + USER + "\n"
         "\tSupplied Realm Name:\tSTC\n\tUser ID:\t\t\t" + SID_A + "\n\n"
         "Service Information:\n\tService Name:\t\tkrbtgt\n"
         "\tService ID:\t\t" + DOMSID + "-502\n\n"
         "Network Information:\n\tClient Address:\t\t::ffff:10.20.14.11\n"
         "\tClient Port:\t\t52431\n\n"
         "Additional Information:\n\tTicket Options:\t\t0x40810010\n"
         "\tResult Code:\t\t0x0\n\tFailure Code:\t\t0x0\n"
         "\tTicket Encryption Type:\t0x12\n\tPre-Authentication Type:\t2")
obs = base_obs(tc, "4768", 3900630, 20, "{7d3a91f2-4c8b-4e21-a6d5-b0c447680001}")
obs.update({"event_data.TargetDomainName": ["STC"],
            "event_data.TargetUserName": [USER],
            "event_data.TargetUserSid": [SID_A],
            "event_data.TicketEncryptionType": ["0x12"],
            "event_data.IpAddress": ["10.20.14.11"],
            "event_data.WorkstationName": ["WS-1001"],
            "message": [m4768]})
fire("4768 tgt-burst", obs, 20,
     extra=["event_data.TicketEncryptionType", "event_data.IpAddress", "event_data.WorkstationName"])
