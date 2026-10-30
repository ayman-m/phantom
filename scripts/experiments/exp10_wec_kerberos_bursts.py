"""Exp 10: P2 Kerberos bursts over native WEC (batch 3).

  #22 multiple service tickets (Info, 10 min)   - 18x 4769, one user, distinct SPNs
  #23 weakly encrypted service tickets (10 min) - same burst, TicketEncryptionType 0x17 (RC4)
  #25 TGT without pre-auth (Info, 10 min)       - 8x 4768 PreAuthType 0, distinct users
  #24 irregular TGT burst (Low, 10 min)         - 10x 4768, one user, rapid succession
"""
import json, os, sys, datetime
sys.path.insert(0, os.path.expanduser("~/Documents/Phantom"))
from stc_api import call_tool

NOW = datetime.datetime.now(datetime.timezone.utc)
def ts(d): return (NOW - datetime.timedelta(seconds=d)).strftime("%Y-%m-%dT%H:%M:%SZ")

DOM, DNS, DC = "PHANTOM", "phantom.lab", "PHDC02"
SEC = "Microsoft-Windows-Security-Auditing"
SID = "S-1-5-21-3623811015-3361044348-30300820"

SPNS = ["MSSQLSvc/PHSRV-SQL01.phantom.lab:1433", "HTTP/intranet.phantom.lab",
        "CIFS/PHSRV-FS01.phantom.lab", "HOST/PHSRV-APP01.phantom.lab",
        "LDAP/PHDC01.phantom.lab", "HTTP/portal.phantom.lab",
        "MSSQLSvc/PHSRV-SQL02.phantom.lab:1433", "CIFS/PHDC02.phantom.lab",
        "WSMAN/PHSRV-APP02.phantom.lab", "HTTP/api.phantom.lab",
        "MSSQLSvc/PHSRV-SQL03.phantom.lab:1433", "CIFS/PHSRV-FS02.phantom.lab",
        "HOST/PHWS-050.phantom.lab", "LDAP/PHDC02.phantom.lab",
        "HTTP/reports.phantom.lab", "TERMSRV/PHSRV-APP01.phantom.lab",
        "HOST/PHWS-051.phantom.lab", "CIFS/PHSRV-FS03.phantom.lab"]

MSG_4769 = (
    "A Kerberos service ticket was requested.\n\n"
    "Account Information:\n"
    "\tAccount Name:\t\t{user}@{DOM}.LAB\n"
    "\tAccount Domain:\t\t{DOM}.LAB\n"
    "\tLogon GUID:\t\t{{{guid}}}\n\n"
    "Service Information:\n"
    "\tService Name:\t\t{spn}\n"
    "\tService ID:\t\t{sid}-1105\n\n"
    "Network Information:\n"
    "\tClient Address:\t\t::ffff:{ip}\n"
    "\tClient Port:\t\t{port}\n\n"
    "Additional Information:\n"
    "\tTicket Options:\t\t0x40810000\n"
    "\tTicket Encryption Type:\t{enc}\n"
    "\tFailure Code:\t\t0x0\n"
    "\tTransited Services:\t-"
)

MSG_4768 = (
    "A Kerberos authentication ticket (TGT) was requested.\n\n"
    "Account Information:\n"
    "\tAccount Name:\t\t{user}\n"
    "\tSupplied Realm Name:\t\t{DOM}.LAB\n"
    "\tUser ID:\t\t\t{sid}-{rid}\n\n"
    "Service Information:\n"
    "\tService Name:\t\tkrbtgt\n"
    "\tService ID:\t\t{sid}-502\n\n"
    "Network Information:\n"
    "\tClient Address:\t\t::ffff:{ip}\n"
    "\tClient Port:\t\t{port}\n\n"
    "Additional Information:\n"
    "\tTicket Options:\t\t0x40810010\n"
    "\tResult Code:\t\t0x0\n"
    "\tTicket Encryption Type:\t{enc}\n"
    "\tPre-Authentication Type:\t{preauth}\n\n"
    "Certificate Information:\n"
    "\tCertificate Issuer Name:\t\t-\n"
    "\tCertificate Serial Number:\t-\n"
    "\tCertificate Thumbprint:\t\t-"
)

events = []

# #22+#23: 18x 4769, svc.web, distinct SPNs, RC4 (0x17)
for i, spn in enumerate(SPNS):
    events.append({
        "event_id": 4769, "computer": DC, "time": ts(540 - i * 8),
        "provider": SEC,
        "rendering": {"task": "Kerberos Service Ticket Operations",
                      "message": MSG_4769.format(user="svc.web", DOM=DOM,
                          guid="%08x-a11c-4e2a-9b00-%012x" % (0x47690000 + i, i),
                          spn=spn, sid=SID, ip="10.20.16.26", port=52000 + i, enc="0x17")},
        "event_data": {
            "TargetUserName": "svc.web@PHANTOM.LAB", "TargetDomainName": "PHANTOM.LAB",
            "ServiceName": spn, "ServiceSid": SID + "-1105",
            "TicketOptions": "0x40810000", "TicketEncryptionType": "0x17",
            "IpAddress": "::ffff:10.20.16.26", "IpPort": str(52000 + i),
            "Status": "0x0",
            "LogonGuid": "{%08x-a11c-4e2a-9b00-%012x}" % (0x47690000 + i, i),
            "TransmittedServices": "-"},
    })

# #25: 8x 4768 PreAuthType 0, distinct users
for i in range(8):
    u = "user.preauth%d" % i
    events.append({
        "event_id": 4768, "computer": DC, "time": ts(480 - i * 20),
        "provider": SEC,
        "rendering": {"task": "Kerberos Authentication Service",
                      "message": MSG_4768.format(user=u, DOM=DOM, sid=SID,
                          rid=3300 + i, ip="10.20.17.%d" % (40 + i),
                          port=53000 + i, enc="0x12", preauth="0")},
        "event_data": {
            "TargetUserName": u, "TargetDomainName": "PHANTOM.LAB",
            "TargetSid": "%s-%d" % (SID, 3300 + i),
            "ServiceName": "krbtgt", "ServiceSid": SID + "-502",
            "TicketOptions": "0x40810010", "Status": "0x0",
            "TicketEncryptionType": "0x12", "PreAuthType": "0",
            "IpAddress": "::ffff:10.20.17.%d" % (40 + i), "IpPort": str(53000 + i)},
    })

# #24: 10x 4768 burst, one user (irregular TGT)
for i in range(10):
    events.append({
        "event_id": 4768, "computer": DC, "time": ts(300 - i * 6),
        "provider": SEC,
        "rendering": {"task": "Kerberos Authentication Service",
                      "message": MSG_4768.format(user="svc.scheduler", DOM=DOM, sid=SID,
                          rid=3208, ip="10.20.16.77", port=54000 + i,
                          enc="0x12", preauth="2")},
        "event_data": {
            "TargetUserName": "svc.scheduler", "TargetDomainName": "PHANTOM.LAB",
            "TargetSid": SID + "-3208", "ServiceName": "krbtgt",
            "ServiceSid": SID + "-502", "TicketOptions": "0x40810010",
            "Status": "0x0", "TicketEncryptionType": "0x12", "PreAuthType": "2",
            "IpAddress": "::ffff:10.20.16.77", "IpPort": str(54000 + i)},
    })

r = call_tool("wec-sender.send_events", {"events": events}, timeout=240)
res = r["result"]
print(json.dumps({k: res.get(k) for k in ("ok", "events", "sent", "envelopes", "first_time", "last_time")}, indent=1))
