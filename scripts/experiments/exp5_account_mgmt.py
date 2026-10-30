"""Exp 5: Windows account-management attack batch via CEF.

4728 member added to Domain Admins (priv_group_addition) x2
4720 user account created (suspicious_account_creation) x2
4726 user account deleted (mass_account_deletion) x8
4740 account locked out (account_lockout) x6

Actor: ahmed.alharbi (Logon 0x1A2B3C) for the management events; DC01$ SYSTEM subject for 4740.
All events logged on DC01.stc.local.
"""
import json, datetime, time as _time
from stc_api import call_tool

fields = json.load(open("win_schema_fields.json"))
byname = {f["name"]: f for f in fields}
DEST = "logdest:217fa292-3beb-49fd-ba8b-5cbd9e84341f"
SID_A = "S-1-5-21-1004336348-1177238915-682003330-1100"
USER = "ahmed.alharbi"
DOMSID = "S-1-5-21-1004336348-1177238915-682003330"
TABS = "\t"

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

def fire(tag, obs, n):
    missing = [f for f in BASE if f not in byname]
    if missing:
        raise SystemExit(f"missing schema fields {missing}")
    args = {"type": "CEF", "vendor": "microsoft", "product": "windows",
            "destination": DEST, "count": n, "interval": 1,
            "duration_seconds": 30, "max_events": n,
            "schema_override": [byname[f] for f in BASE],
            "observables_dict": obs}
    r = call_tool("xlog.create_data_worker", args, timeout=90)
    w = (r.get("result") or [{}])[0]
    print(tag, "->", w.get("worker"), w.get("status"))
    _time.sleep(3)

t0 = datetime.datetime.now(datetime.timezone.utc)

# --- 4728: svc-sql01 + backup.svc02 added to Domain Admins ---
tc = t0.strftime("%Y-%m-%dT%H:%M:%SZ")
members = [("svc-sql01", f"{DOMSID}-1601"), ("backup.svc02", f"{DOMSID}-1611")]
def m4728(mname, msid):
    return ("A member was added to a security-enabled global group.\n\n"
            "Subject:\n\tSecurity ID:\t\t" + SID_A + "\n\tAccount Name:\t\t" + USER +
            "\n\tAccount Domain:\t\tSTC\n\tLogon ID:\t\t0x1A2B3C\n\n"
            "Member:\n\tSecurity ID:\t\t" + msid + "\n\tAccount Name:\t\t" + mname + "\n\n"
            "Group:\n\tSecurity ID:\t\t" + DOMSID + "-512\n\tGroup Name:\t\tDomain Admins\n"
            "\tGroup Domain:\t\tSTC\n\n"
            "Additional Information:\n\tPrivileges:\t\t-")
obs = base_obs(tc, "4728", 3900500, 2, "{7d3a91f2-4c8b-4e21-a6d5-b0c447280001}")
obs.update({"event_data.TargetDomainName": ["STC"],
            "event_data.TargetUserName": [m for m, _ in members],
            "event_data.TargetUserSid": [s for _, s in members],
            "message": [m4728(m, s) for m, s in members]})
fire("4728 group-add", obs, 2)

# --- 4720: two new accounts created ---
tc = (t0 + datetime.timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
def m4720(mname, msid):
    return ("A user account was created.\n\n"
            "Subject:\n\tSecurity ID:\t\t" + SID_A + "\n\tAccount Name:\t\t" + USER +
            "\n\tAccount Domain:\t\tSTC\n\tLogon ID:\t\t0x1A2B3C\n\n"
            "New Account:\n\tSecurity ID:\t\t" + msid + "\n\tAccount Name:\t\t" + mname +
            "\n\tAccount Domain:\t\tSTC\n\n"
            "Attributes:\n\tSAM Account Name:\t" + mname + "\n\tDisplay Name:\t\t-\n"
            "\tUser Principal Name:\t" + mname + "@stc.local\n\tHome Directory:\t\t-\n"
            "\tUser Account Control:\tEnabled\n\tPassword Last Set:\t<never>\n\n"
            "Additional Information:\n\tPrivileges:\t\t-")
obs = base_obs(tc, "4720", 3900510, 2, "{7d3a91f2-4c8b-4e21-a6d5-b0c447200001}")
obs.update({"event_data.TargetDomainName": ["STC"],
            "event_data.TargetUserName": [m for m, _ in members],
            "event_data.TargetUserSid": [s for _, s in members],
            "message": [m4720(m, s) for m, s in members]})
fire("4720 create", obs, 2)

# --- 4726: mass deletion, 8 accounts ---
tc = (t0 + datetime.timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
victims = [("m.alotaibi", 1501), ("f.aldossari", 1502), ("r.alqahtani", 1503),
           ("l.almutairi", 1504), ("h.alsubaie", 1505), ("n.alshammari", 1506),
           ("k.alghamdi", 1507), ("t.alanazi", 1508)]
def m4726(mname, msid):
    return ("A user account was deleted.\n\n"
            "Subject:\n\tSecurity ID:\t\t" + SID_A + "\n\tAccount Name:\t\t" + USER +
            "\n\tAccount Domain:\t\tSTC\n\tLogon ID:\t\t0x1A2B3C\n\n"
            "Target Account:\n\tSecurity ID:\t\t" + msid + "\n\tAccount Name:\t\t" + mname +
            "\n\tAccount Domain:\t\tSTC\n\n"
            "Additional Information:\n\tPrivileges:\t\t-")
obs = base_obs(tc, "4726", 3900520, 8, "{7d3a91f2-4c8b-4e21-a6d5-b0c447260001}")
obs.update({"event_data.TargetDomainName": ["STC"],
            "event_data.TargetUserName": [v for v, _ in victims],
            "event_data.TargetUserSid": [f"{DOMSID}-{s}" for _, s in victims],
            "message": [m4726(v, f"{DOMSID}-{s}") for v, s in victims]})
fire("4726 mass-delete", obs, 8)

# --- 4740: lockouts, 6 users, caller WS-1001 ---
tc = (t0 + datetime.timedelta(seconds=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
locked = victims[:6]
def m4740(mname, msid):
    return ("A user account was locked out.\n\n"
            "Subject:\n\tSecurity ID:\t\tS-1-5-18\n\tAccount Name:\t\tDC01$\n"
            "\tAccount Domain:\t\tSTC\n\tLogon ID:\t\t0x3E7\n\n"
            "Account That Was Locked Out:\n\tSecurity ID:\t\t" + msid +
            "\n\tAccount Name:\t\t" + mname + "\n\tAccount Domain:\t\tSTC\n\n"
            "Additional Information:\n\tCaller Computer Name:\tWS-1001")
obs = base_obs(tc, "4740", 3900530, 6, "{7d3a91f2-4c8b-4e21-a6d5-b0c447400001}")
obs.update({"event_data.SubjectUserName": ["DC01$"], "event_data.SubjectUserSid": ["S-1-5-18"],
            "event_data.TargetDomainName": ["STC"],
            "event_data.TargetUserName": [v for v, _ in locked],
            "event_data.TargetUserSid": [f"{DOMSID}-{s}" for _, s in locked],
            "message": [m4740(v, f"{DOMSID}-{s}") for v, s in locked]})
fire("4740 lockouts", obs, 6)
