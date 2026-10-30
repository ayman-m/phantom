"""Create recurring experiment jobs on stc-engine — continuous threat pressure for the
baselined detectors. Timestamps self-date via {{now:strftime}} (rendered at emit time).
Minutes chosen to avoid the existing baseline jobs (3,5,7,10,11,13,15,17,20,27,30-35,41,43,45,47,50,51,53).
"""
import json, random
from stc_api import call_tool

random.seed(7)
fgt = {f["name"]: f for f in json.load(open("fgt_schema_fields.json"))}
win = {f["name"]: f for f in json.load(open("win_schema_fields.json"))}
DEST = "logdest:217fa292-3beb-49fd-ba8b-5cbd9e84341f"
TZ = "Asia/Riyadh"
DOMSID = "S-1-5-21-1004336348-1177238915-682003330"

def fgt_fields(names):
    return [{"name": n, "type": fgt[n]["type"]} for n in names]

def win_fields(names):
    return [{"name": n, "type": win[n]["type"]} for n in names]

def create(name, cron, args):
    r = call_tool("jobs_create", {"name": name, "cron": cron, "timezone": TZ,
                                  "action": {"type": "tool_call",
                                             "name": "xlog.create_data_worker",
                                             "args": args},
                                  "enabled": True}, timeout=60)
    ok = r.get("ok")
    print(name, "->", "OK" if ok else json.dumps(r)[:300])

# ---------- 1. exp-dns-tunnel: FortiGate utm:dns, 80 events, every 2h ----------
B32 = "abcdefghijklmnopqrstuvwxyz234567"
def b32(n): return "".join(random.choice(B32) for _ in range(n))
DOMAINS = ["t3.exfil-tunnel.net", "t4.exfil-tunnel.net", "t5.exfil-tunnel.net"]
qnames = [f"{b32(random.randint(32,48))}.{b32(random.randint(16,24))}.{random.choice(DOMAINS)}"
          for _ in range(80)]
create("exp-dns-tunnel", "9 */2 * * *", {
    "type": "CEF", "vendor": "Fortinet", "product": "Fortigate",
    "destination": DEST, "name": "exp-dns-tunnel", "tags": ["experiment"],
    "count": 80, "interval": 1, "duration_seconds": 120, "max_events": 80,
    "schema_override": fgt_fields(["FTNTFGTeventtime", "FTNTFGTduration", "FTNTFGTsubtype",
        "FTNTFGTeventtype", "FTNTFGTlogid", "FTNTFGTlevel", "FTNTFGTvd", "FTNTFGTqname",
        "FTNTFGTqtype", "FTNTFGTqclass", "FTNTFGTipaddr", "src", "spt", "dst", "dpt", "proto",
        "act", "app", "shost", "dhost", "dvchost", "deviceExternalId", "cefSeverity", "msg",
        "externalId", "out", "in"]),
    "observables_dict": {
        "FTNTFGTeventtime": ["{{now:%s}}000000000"],
        "FTNTFGTduration": ["0"],
        "FTNTFGTsubtype": ["dns-response"], "FTNTFGTeventtype": ["dns-response"],
        "FTNTFGTlogid": ["1501054600"], "FTNTFGTlevel": ["warning"], "FTNTFGTvd": ["root"],
        "FTNTFGTqname": qnames,
        "FTNTFGTqtype": ["TXT"]*6 + ["A"]*3 + ["CNAME"],
        "FTNTFGTqclass": ["IN"],
        "FTNTFGTipaddr": ["203.0.113.53", "203.0.113.54", "203.0.113.55"],
        "src": ["10.20.63.15", "10.20.63.16", "10.20.63.17"],
        "shost": ["WS-STCE-15", "WS-STCE-16", "WS-STCE-17"],
        "dst": ["203.0.113.53"], "dhost": ["dns.exfil-tunnel.net"],
        "dpt": ["53"], "proto": ["17"], "app": ["DNS"], "act": ["pass"],
        "spt": [str(random.randint(49152, 65535)) for _ in range(25)],
        "dvchost": ["FGT-EDGE-01.corp.stc.local"], "deviceExternalId": ["FGT60FT19015830"],
        "cefSeverity": ["3"],
        "msg": ["DNS query for encoded label under exfil-tunnel.net"],
        "externalId": [str(random.randint(2000000, 2999999)) for _ in range(4)],
        "out": [str(random.randint(180, 512)) for _ in range(10)],
        "in": [str(random.randint(200, 4000)) for _ in range(10)],
    }})

# ---------- shared Windows helpers ----------
GUIDS = ("{1131f6aa-9c07-11d1-f79f-00c04fc2dcd2}\n    {1131f6ad-9c07-11d1-f79f-00c04fc2dcd2}\n    "
         "{1131f6ae-9c07-11d1-f79f-00c04fc2dcd2}\n    {89e95b76-444d-4c62-991a-0facbeda640c}")
IDENTS = [("ahmed.alharbi", f"{DOMSID}-1100", "WS-1001", "10.20.14.11", "0x1A2B3C"),
          ("abdullah.alzahrani", f"{DOMSID}-1101", "WS-1002", "10.20.14.12", "0x2B3C4D")]

def win_base(eid, fields_extra):
    names = ["time_created", "provider_name", "channel", "event_id", "event_result",
             "activity_id", "computer_name", "host_name", "log_level", "opcode", "os_subtype",
             "process_pid", "process_thread_id", "provider_guid", "record_id",
             "event_data.Domain", "event_data.FQDN", "event_data.IpAddress", "event_data.SID",
             "event_data.SubjectDomainName", "event_data.SubjectUserName",
             "event_data.SubjectUserSid", "event_data.TargetDomainName",
             "event_data.TargetUserName", "event_data.TargetUserSid",
             "user.domain", "user.identifier", "user.name", "user.type", "message"] + fields_extra
    obs = {
        "time_created": ["{{now:%Y-%m-%dT%H:%M:%SZ}}"],
        "provider_name": ["Microsoft-Windows-Security-Auditing"],
        "channel": ["Security"], "event_id": [eid], "event_result": ["success"],
        "activity_id": ["{7d3a91f2-4c8b-4e21-a6d5-b0c4job00001}".replace("job", "aa")],
        "computer_name": [h + ".stc.local" for _, _, h, _, _ in IDENTS],
        "host_name": [h for _, _, h, _, _ in IDENTS],
        "log_level": ["Information"], "opcode": ["Info"],
        "os_subtype": ["Windows 10 Enterprise"], "process_pid": ["488"],
        "process_thread_id": ["6104"],
        "provider_guid": ["{54849625-5478-4994-A5BA-3E3B0328C30D}"],
        "record_id": [str(3901000 + i) for i in range(20)],
        "event_data.Domain": ["STC"],
        "event_data.FQDN": [h + ".stc.local" for _, _, h, _, _ in IDENTS],
        "event_data.IpAddress": [ip for _, _, _, ip, _ in IDENTS],
        "event_data.SID": [s for _, s, _, _, _ in IDENTS],
        "event_data.SubjectDomainName": ["STC"],
        "event_data.SubjectUserName": [u for u, _, _, _, _ in IDENTS],
        "event_data.SubjectUserSid": [s for _, s, _, _, _ in IDENTS],
        "event_data.TargetDomainName": ["STC"],
        "event_data.TargetUserName": [u for u, _, _, _, _ in IDENTS],
        "event_data.TargetUserSid": [s for _, s, _, _, _ in IDENTS],
        "user.domain": ["STC"], "user.identifier": [s for _, s, _, _, _ in IDENTS],
        "user.name": [u for u, _, _, _, _ in IDENTS], "user.type": ["User"],
    }
    return names, obs

# ---------- 2. exp-dcsync: 4662 x4 every 3h ----------
def msg4662(u, sid, logon):
    obj = "CN=krbtgt,CN=Users,DC=stc,DC=local"
    return ("An operation was performed on an object.\n\nSubject :\n"
            f"\tSecurity ID:\t\t{sid}\n\tAccount Name:\t\t{u}\n\tAccount Domain:\t\tSTC\n"
            f"\tLogon ID:\t\t{logon}\n\nObject:\n\tObject Server:\t\tDS\n"
            "\tObject Type:\t\t%{bf967aba-0de6-11d0-a285-00aa003049e2}\n"
            f"\tObject Name:\t\t{obj}\n\tHandle ID:\t\t0x0\n\nOperation:\n"
            "\tOperation Type:\t\tObject Access\n\tAccess Mask:\t\t0x100\n"
            f"\tProperties:\t\t{GUIDS}\n\t\t\t{obj}\n\nAdditional Information:\n"
            "\tParameter 1:\t\t-\n\tParameter 2:\t\t-")
names, obs = win_base("4662", ["AccessMask", "ObjectName", "ObjectType"])
obs.update({"AccessMask": ["0x100"],
            "ObjectName": ["CN=krbtgt,CN=Users,DC=stc,DC=local"],
            "ObjectType": ["%{bf967aba-0de6-11d0-a285-00aa003049e2}"],
            "message": [msg4662(u, s, l) for u, s, _, _, l in IDENTS]})
create("exp-dcsync", "23 */3 * * *", {
    "type": "CEF", "vendor": "microsoft", "product": "windows",
    "destination": DEST, "name": "exp-dcsync", "tags": ["experiment"],
    "count": 4, "interval": 1, "duration_seconds": 30, "max_events": 4,
    "schema_override": win_fields(names), "observables_dict": obs})

# ---------- 3. exp-kerberoast: 4769 RC4 x15 every 3h ----------
SPNS = [("MSSQLSvc/FS-01.stc.local:1433", f"{DOMSID}-1601"),
        ("HTTP/intranet.stc.local", f"{DOMSID}-1602"),
        ("CIFS/FS-02.stc.local", f"{DOMSID}-1603"),
        ("ldap/DC01.stc.local", f"{DOMSID}-1604"),
        ("TERMSRV/TS-01.stc.local", f"{DOMSID}-1605")]
def msg4769(u, spn, ssid):
    return ("A Kerberos service ticket was requested.\n\nAccount Information:\n"
            f"\tAccount Name:\t\t{u}@STC.LOCAL\n\tAccount Domain:\t\tSTC.LOCAL\n"
            "\tLogon GUID:\t\t{00000000-0000-0000-0000-000000000000}\n\nService Information:\n"
            f"\tService Name:\t\t{spn}\n\tService ID:\t\t{ssid}\n\nNetwork Information:\n"
            "\tClient Address:\t\t::ffff:10.20.14.11\n\tClient Port:\t\t52431\n\n"
            "Additional Information:\n\tTicket Options:\t\t0x40810000\n"
            "\tTicket Encryption Type:\t0x17\n\tFailure Code:\t\t0x0\n\tTransited Services:\t-")
names, obs = win_base("4769", ["event_data.TicketEncryptionType", "event_data.User",
                               "event_data.UserSid", "event_data.WorkstationName"])
obs.update({"event_data.TicketEncryptionType": ["0x17"],
            "event_data.User": [u for u, _, _, _, _ in IDENTS],
            "event_data.UserSid": [s for _, s, _, _, _ in IDENTS],
            "event_data.WorkstationName": [h for _, _, h, _, _ in IDENTS],
            "message": [msg4769(u, spn, ssid) for u, _, _, _, _ in IDENTS for spn, ssid in SPNS]})
create("exp-kerberoast", "37 */3 * * *", {
    "type": "CEF", "vendor": "microsoft", "product": "windows",
    "destination": DEST, "name": "exp-kerberoast", "tags": ["experiment"],
    "count": 15, "interval": 1, "duration_seconds": 60, "max_events": 15,
    "schema_override": win_fields(names), "observables_dict": obs})

# ---------- 4. exp-ldap-enum: 1644 x5 every 4h ----------
FILTERS = [" (&(objectClass=group)(cn=Domain Admins))",
           " (&(objectClass=group)(cn=Enterprise Admins))",
           " (&(objectClass=group)(cn=Schema Admins))",
           " (&(objectClass=group)(cn=Administrators))",
           " (&(objectClass=user)(adminCount=1))"]
ATTRS = "member,sAMAccountName,objectSid,adminCount,memberOf,distinguishedName"
def msg1644(filt, u):
    return ("Internal event: A client issued a search operation with the following options. \n \n "
            "Client:\n10.20.14.11:59300 \nStarting node:\nDC=stc,DC=local \nFilter:\n" + filt +
            " \nSearch scope:\n subtree \nAttribute selection:\n" + ATTRS +
            " \nServer controls:\n \nVisibility of deleted objects:\n0 \nSearch flags:\n0 \n"
            "Attributes read:\n14 \nSearch time (ms):\n7 \nUser:\nSTC\\" + u + " \n")
names1644 = ["time_created", "provider_name", "event_id", "event_result", "activity_id",
             "computer_name", "host_name", "log_level", "opcode", "os_subtype", "provider_guid",
             "record_id", "event_data.param1", "event_data.param2", "event_data.param3",
             "event_data.param4", "event_data.param5", "event_data.param6", "event_data.param7",
             "event_data.param9", "event_data.param17", "message"]
obs1644 = {
    "time_created": ["{{now:%Y-%m-%dT%H:%M:%SZ}}"],
    "provider_name": ["Microsoft-Windows-ActiveDirectory_DomainService"],
    "event_id": ["1644"], "event_result": ["success"],
    "activity_id": ["{7d3a91f2-4c8b-4e21-a6d5-b0c416440002}"],
    "computer_name": ["DC01.stc.local"], "host_name": ["DC01"],
    "log_level": ["Information"], "opcode": ["Info"],
    "os_subtype": ["Windows Server 2022"],
    "provider_guid": ["{54849625-5478-4994-A5BA-3E3B0328C30D}"],
    "record_id": [str(3902000 + i) for i in range(5)],
    "event_data.param1": ["DC=stc,DC=local"], "event_data.param2": FILTERS,
    "event_data.param3": ["0"], "event_data.param4": ["0"],
    "event_data.param5": ["10.20.14.11:59300"], "event_data.param6": ["subtree"],
    "event_data.param7": [ATTRS], "event_data.param9": ["idx_object-class:0:N;"],
    "event_data.param17": ["STC\\ahmed.alharbi"],
    "message": [msg1644(f, "ahmed.alharbi") for f in FILTERS]}
create("exp-ldap-enum", "19 */4 * * *", {
    "type": "CEF", "vendor": "microsoft", "product": "windows",
    "destination": DEST, "name": "exp-ldap-enum", "tags": ["experiment"],
    "count": 5, "interval": 1, "duration_seconds": 30, "max_events": 5,
    "schema_override": win_fields(names1644), "observables_dict": obs1644})

# ---------- 5. exp-acct-mgmt: 4726 mass-delete x8 every 6h ----------
victims = [("m.alotaibi", 1501), ("f.aldossari", 1502), ("r.alqahtani", 1503),
           ("l.almutairi", 1504), ("h.alsubaie", 1505), ("n.alshammari", 1506),
           ("k.alghamdi", 1507), ("t.alanazi", 1508)]
def msg4726(vname, vsid, u, usid):
    return ("A user account was deleted.\n\nSubject:\n"
            f"\tSecurity ID:\t\t{usid}\n\tAccount Name:\t\t{u}\n\tAccount Domain:\t\tSTC\n"
            "\tLogon ID:\t\t0x1A2B3C\n\nTarget Account:\n"
            f"\tSecurity ID:\t\t{vsid}\n\tAccount Name:\t\t{vname}\n\tAccount Domain:\t\tSTC\n\n"
            "Additional Information:\n\tPrivileges:\t\t-")
names, obs = win_base("4726", [])
obs["computer_name"] = ["DC01.stc.local"]; obs["host_name"] = ["DC01"]
obs["os_subtype"] = ["Windows Server 2022"]
obs.update({"event_data.TargetUserName": [v for v, _ in victims],
            "event_data.TargetUserSid": [f"{DOMSID}-{s}" for _, s in victims],
            "message": [msg4726(v, f"{DOMSID}-{s}", u, usid)
                        for v, s in victims for u, usid, _, _, _ in IDENTS[:1]]})
create("exp-acct-mgmt", "47 */6 * * *", {
    "type": "CEF", "vendor": "microsoft", "product": "windows",
    "destination": DEST, "name": "exp-acct-mgmt", "tags": ["experiment"],
    "count": 8, "interval": 1, "duration_seconds": 30, "max_events": 8,
    "schema_override": win_fields(names), "observables_dict": obs})
