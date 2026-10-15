"""The `proofpoint_tap` event profile: synthetic Proofpoint TAP SIEM API events.

Each event has the shape of one record from the TAP SIEM API, which is also the shape the
Cortex ProofpointTAP pack's `proofpoint_tap_raw` modeling rule (the `_1_3` rule) reads. There
are four kinds, told apart by `_log_type`:

  message-delivered / message-blocked   an email: `GUID`, `messageID`, `messageTime`,
      `fromAddress` (array), `sender`, `senderIP`, `recipient` (array), `ccAddresses` (array),
      `subject`, `messageParts` (array of objects), `threatsInfoMap` (array of objects).
  click-blocked / click-permitted       a user click on a rewritten URL: `clickTime`, `clickIP`,
      `userAgent`, `url`, and `recipient` as a plain STRING (the rule accepts both forms).

The rule reads `_vendor` (set by the collector) and `_log_type` (set here) to build
`xdm.event.type`. Every event carries `messageTime`, which the pack's parsing rule prefers
over `clickTime` for `_time`. A real click record has no `messageTime`, so `_time` would be
`clickTime`; a click here sets `messageTime` to its `clickTime` to get the same `_time` and
a TIME_FIELD that is always present. Without the pack installed the dataset is raw-only and
`_time` is the ingestion time.

Addresses are real, geo-resolvable public IPs from `ippools` (Cortex derives country and ASN from the
IP itself). Benign mail comes from a stable address per sender, drawn from the Saudi home pool and the
first six out-of-country ranges. A click comes from the recipient's own stable home address, the one
the same person has in the `okta` and `google_workspace` profiles. Every attack scenario sends from the
other twelve out-of-country ranges, so no attacker address is ever a benign sender's. Everything else
here is synthetic: names and ids are fictitious, and mail and URL hosts are on `.example` / `.invalid`.

The recipients are the active organization's people who may log on (leavers excluded), by their email; `target_user` names
one of them (login, email or the part before the @). The outside senders are not the organization's and stay here.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from runtime.organization_view import OrganizationView

from . import _org, ippools
from .okta import _times, iso  # one windowing and timestamp convention across profiles

# The profile interface (see profiles/__init__.py).
NAME = "proofpoint_tap"
DESCRIPTION = ("Proofpoint TAP SIEM API events: benign mail, phishing URL, malware attachment, "
               "credential phishing, BEC impostor, click chains.")
# The collector these events are meant for (vendor Proofpoint, product Tap).
EXPECTED_DATASET = "proofpoint_tap"
EXPECTED_DATASETS = ("proofpoint_tap",)
# The Cribl destination for the same source; the events are NOT yet measured through it (only the Okta, AWS, GCP and
# Azure AD audit sources were), and the HTTP collector stays the default.
CRIBL_DESTINATIONS = ("cribl_proofpoint_tap",)
# Messages and their clicks share a GUID, as in the real feed.
TEST_ID_FIELD = "GUID"
# Present on every event, and the field the pack's parsing rule prefers for `_time`.
TIME_FIELD = "messageTime"
SCENARIOS = ("benign_mail", "phishing_url", "malware_attachment", "credential_phishing",
             "bec_impostor", "click_chain")

_BENIGN_SENDERS = [
    ("Acme Notifications", "notifications@acme-saas.example"),
    ("Contoso Billing", "billing@contoso-billing.example"),
    ("Northwind HR", "hr-updates@northwind-hr.example"),
    ("Fabrikam Support", "support@fabrikam-support.example"),
    ("Tailspin Digest", "news@tailspin-digest.example"),
]
_THREAT_SENDERS = [
    ("Account Security", "security@account-verify-portal.example"),
    ("Document Share", "no-reply@secure-doc-share.example"),
    ("Payroll Team", "payroll@payroll-update-notice.example"),
    ("IT Helpdesk", "helpdesk@it-helpdesk-support.example"),
    ("Voicemail Service", "service@voicemail-delivery.example"),
]
_MALICIOUS_HOSTS = ["credential-harvest.example", "doc-view-portal.invalid", "login-verify.invalid",
                    "invoice-download.example", "secure-file-share.invalid"]
_BENIGN_SUBJECTS = ["Team meeting agenda", "Your invoice is ready", "Reminder: annual performance review",
                    "Project update: week 14", "Security awareness training reminder",
                    "IT maintenance window notification", "Quarterly business review - save the date"]
_PHISH_SUBJECTS = ["Your account requires verification", "URGENT: your account will be suspended",
                   "Important security notice for your account", "Your shared document is waiting",
                   "Unusual sign-in activity detected", "Password expiration notice"]
_BEC_SUBJECTS = ["Urgent wire transfer request", "Quick question", "Change of bank details",
                 "Confidential: executive action required", "Please process payment - time sensitive"]
# (filename template, content type): `{n}` is filled with a random number.
_MALWARE_FILES = [
    ("Invoice_{n}.doc", "application/msword"),
    ("Shipment_{n}.xlsm", "application/vnd.ms-excel.sheet.macroEnabled.12"),
    ("Report_{n}.exe", "application/octet-stream"),
    ("Setup_{n}.zip", "application/zip"),
    ("Statement_{n}.docm", "application/vnd.ms-word.document.macroEnabled.12"),
]
_BENIGN_FILES = [("Quarterly_Report.pdf", "application/pdf"), ("Meeting_Agenda.docx",
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                 ("photo.jpg", "image/jpeg")]
_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Microsoft Office/16.0 (Windows NT 10.0; Microsoft Outlook 16.0; Pro)",
]
_ROUTES = ["executives", "finance", "hr", "it_staff", "privileged_users"]
# Where mail comes from: benign senders use the home pool and the first six out-of-country ranges, attackers
# the remaining twelve. The two pools are disjoint, so a sender address alone tells a baseline from an attack.
_BENIGN_POOL = ippools.HOME + ippools.ABROAD[:6]
_ATTACK_POOL = ippools.ABROAD[6:]
_CLUSTER = "phantom_lab_hosted"
_ID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"


class _Factory:
    """Deterministic when seeded, so the tests can assert on exact output."""

    def __init__(self, view: OrganizationView, seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.view = view
        self.domain = view.email_domain
        self._seen: set[str] = set()
        self.pool = _org.logon_people(view)
        self._by_email = {p["email"].lower(): p for p in view.people}

    # -- ids and addresses ----------------------------------------------
    def _unique(self, make: Any) -> str:
        """The first value `make()` yields that this factory has not handed out yet."""
        while (value := make()) in self._seen:
            pass
        self._seen.add(value)
        return value

    def guid(self) -> str:
        return self._unique(lambda: "".join(self.rng.choice(_ID_ALPHABET) for _ in range(32)))

    def message_id(self, sender: str) -> str:
        local, host = sender.split("@", 1)
        return self._unique(lambda: f"<{self.rng.randint(10**8, 10**9 - 1)}.JavaMail.{local}@mail.{host}>")

    def hexdigest(self, bits: int) -> str:
        return f"{self.rng.getrandbits(bits):0{bits // 4}x}"

    def user(self, index: int) -> str:
        """The email of person number `index` of the pool (it wraps around the organization)."""
        return _org.email(self.pool[index % len(self.pool)])

    @staticmethod
    def benign_ip(sender_index: int) -> str:
        """The stable address of benign sender number `sender_index`."""
        pool_range = _BENIGN_POOL[sender_index * 7 % len(_BENIGN_POOL)]
        return ippools.host_in(pool_range, 11 + (sender_index * 13) % 200)

    def attacker_ip(self) -> str:
        return ippools.host_in(self.rng.choice(_ATTACK_POOL), self.rng.randint(2, 253))

    def home_ip(self, login: str) -> str:
        """The recipient's home address: where their clicks come from."""
        return _org.home(self._by_email.get(login.lower()) or {"login": login})[0]

    def url(self) -> str:
        token = self.hexdigest(64)
        path = self.rng.choice([f"/secure/verify?token={token}", f"/login?redirect={token[:8]}",
                                f"/view/invoice/{self.rng.randint(10000, 99999)}"])
        return f"https://{self.rng.choice(_MALICIOUS_HOSTS)}{path}"

    def insight_url(self, guid: str) -> str:
        return f"https://tap-threatinsight.example/#/threat/email/{guid}"

    # -- event pieces ---------------------------------------------------
    def part(self, filename: str, content_type: str, sandbox: str | None, disposition: str = "attachment") -> dict[str, Any]:
        return {"contentType": content_type, "disposition": disposition, "filename": filename,
                "md5": self.hexdigest(128), "oContentType": content_type,
                "sandboxStatus": sandbox, "sha256": self.hexdigest(256)}

    def body(self) -> dict[str, Any]:
        return self.part("text.txt", "text/plain", None, "inline")

    def message(
        self, *, when: datetime, log_type: str, sender: tuple[str, str], recipients: list[str],
        subject: str, ip: str, phish: int = 0, malware: int = 0, spam: int = 0, impostor: int = 0,
        modules: tuple[str, ...] = ("spam", "urldefense"), parts: list[dict[str, Any]] | None = None,
        cc: list[str] | None = None, reply_to: str | None = None, quarantine: tuple[str, str] | None = None,
        rewritten: bool = False,
    ) -> dict[str, Any]:
        """A threat-free message event; `threat` adds the threat fields on top."""
        display, address = sender
        return {
            "_log_type": log_type,
            "GUID": self.guid(),
            "QID": f"r{self.hexdigest(40)}",
            "messageID": self.message_id(address),
            "messageTime": iso(when),
            "recipient": recipients,
            "toAddresses": recipients,
            "headerTo": "; ".join(f'"{r.split("@")[0]}" <{r}>' for r in recipients),
            "ccAddresses": cc or [],
            "fromAddress": [address],
            "sender": address,
            "senderIP": ip,
            "headerFrom": f'"{display}" <{address}>',
            "replyToAddress": [reply_to] if reply_to else [],
            "headerReplyTo": f'"{display}" <{reply_to}>' if reply_to else None,
            "subject": subject,
            "messageSize": self.rng.randint(5000, 500000),
            "policyRoutes": ["default_inbound"] + ([self.rng.choice(_ROUTES)] if quarantine else []),
            "phishScore": phish, "malwareScore": malware, "spamScore": spam, "impostorScore": impostor,
            "quarantineFolder": quarantine[0] if quarantine else None,
            "quarantineRule": quarantine[1] if quarantine else None,
            "completelyRewritten": rewritten,
            "clusterId": _CLUSTER, "cluster": _CLUSTER,
            "modulesRun": list(modules),
            "messageParts": [self.body()] + (parts or []),
            "threatsInfoMap": [],
            "xmailer": "Microsoft Outlook 16.0",
        }

    def threat(
        self, ev: dict[str, Any], *, classification: str, threat_type: str, threat: str, threat_id: str,
        campaign: str, url: str | None = None,
    ) -> dict[str, Any]:
        """Mark a message as a threat: the `threatsInfoMap` entry plus the top-level hunt fields."""
        ev["threatsInfoMap"] = [{
            "campaignID": campaign, "classification": classification, "threat": threat,
            "threatID": threat_id, "threatStatus": "active", "threatTime": ev["messageTime"],
            "threatType": threat_type, "threatUrl": self.insight_url(ev["GUID"]),
        }]
        ev.update(classification=classification, threatID=threat_id,
                  threatURL=self.insight_url(ev["GUID"]), threatStatus="active")
        if url:
            ev["url"] = url
        return ev

    def click(self, msg: dict[str, Any], *, when: datetime, blocked: bool, click_ip: str) -> dict[str, Any]:
        """A click on the URL of `msg` (a message-delivered threat event), same GUID and recipient."""
        entry = msg["threatsInfoMap"][0]
        return {
            "_log_type": "click-blocked" if blocked else "click-permitted",
            "GUID": msg["GUID"],
            "id": self._unique(lambda: f"{self.hexdigest(32)}-{self.hexdigest(16)}-{self.hexdigest(16)}-{self.hexdigest(64)}"),
            "messageID": msg["messageID"],
            "messageTime": iso(when),  # see the module docstring: keeps `_time` at the click
            "clickTime": iso(when),
            "clickIP": click_ip,
            "userAgent": self.rng.choice(_AGENTS),
            "url": msg["url"],
            "recipient": msg["recipient"][0],  # a string on click events, not an array
            "sender": msg["sender"], "senderIP": msg["senderIP"], "fromAddress": msg["fromAddress"],
            "subject": msg["subject"],
            "classification": entry["classification"], "campaignId": entry["campaignID"],
            "threatID": entry["threatID"], "threatTime": iso(when), "threatURL": msg["threatURL"],
            "threatStatus": "active",
            "phishScore": msg["phishScore"], "malwareScore": msg["malwareScore"],
            "spamScore": msg["spamScore"], "impostorScore": msg["impostorScore"],
            "policyRoutes": msg["policyRoutes"], "modulesRun": ["urldefense"],
            "clusterId": _CLUSTER, "cluster": _CLUSTER,
        }

    def campaign(self) -> str:
        return f"CMP-{self.rng.randint(1000, 9999)}"


def _named_user(f: _Factory, login: str | None) -> str | None:
    """`target_user` as the email of the organization's person it names (one spelling per identity)."""
    if not login:
        return None
    return _org.email(_org.resolve(f.view, login))


def _recipients(f: _Factory, index: int, victim: str | None) -> list[str]:
    return [victim or f.user(index)]


def _benign(f: _Factory, times: list[datetime]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, when in enumerate(times):
        parts, extra = [], []
        if f.rng.random() < 0.5:
            name, ctype = f.rng.choice(_BENIGN_FILES)
            parts = [f.part(name, ctype, None if ctype.startswith("image/") else "CLEAN")]
        if f.rng.random() < 0.3:
            extra = [f.user(i + 1)]
        out.append(f.message(
            when=when, log_type="message-delivered", sender=_BENIGN_SENDERS[i % len(_BENIGN_SENDERS)],
            recipients=[f.user(i)], subject=f.rng.choice(_BENIGN_SUBJECTS), ip=f.benign_ip(i % len(_BENIGN_SENDERS)),
            phish=f.rng.randint(0, 15), spam=f.rng.randint(0, 25), parts=parts, cc=extra))
    return out


def _url_threat(f: _Factory, times: list[datetime], victim: str | None, ip: str | None,
                *, scores: tuple[int, int], credential: bool) -> list[dict[str, Any]]:
    """Blocked mail carrying a malicious URL (plain phishing, or credential harvesting)."""
    out: list[dict[str, Any]] = []
    for i, when in enumerate(times):
        url, threat_id = f.url(), f.hexdigest(256)
        ev = f.message(
            when=when, log_type="message-blocked", sender=f.rng.choice(_THREAT_SENDERS),
            recipients=_recipients(f, i, victim), subject=f.rng.choice(_PHISH_SUBJECTS),
            ip=ip or f.attacker_ip(), phish=f.rng.randint(*scores), spam=f.rng.randint(40, 85),
            malware=0 if credential else f.rng.randint(0, 30), modules=("spam", "urldefense", "pdr"),
            quarantine=("Phish", "module.urldefense.phish"), rewritten=True,
            reply_to=None if credential else f"reply-{f.rng.randint(1000, 9999)}@mail-relay.example")
        out.append(f.threat(ev, classification="PHISHING", threat_type="URL", threat=url,
                            threat_id=threat_id, campaign=f.campaign(), url=url))
    return out


def _malware(f: _Factory, times: list[datetime], victim: str | None, ip: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, when in enumerate(times):
        name, ctype = f.rng.choice(_MALWARE_FILES)
        attachment = f.part(name.replace("{n}", str(f.rng.randint(10000, 99999))), ctype, "MALICIOUS")
        ev = f.message(
            when=when, log_type="message-blocked", sender=f.rng.choice(_THREAT_SENDERS),
            recipients=_recipients(f, i, victim), subject=f.rng.choice(_PHISH_SUBJECTS),
            ip=ip or f.attacker_ip(), malware=f.rng.randint(90, 100), phish=f.rng.randint(20, 60),
            spam=f.rng.randint(30, 70), modules=("spam", "urldefense", "pdr", "sandbox"),
            parts=[attachment], quarantine=("Malware", "module.sandbox.threat"), rewritten=True)
        out.append(f.threat(ev, classification="MALWARE", threat_type="ATTACHMENT",
                            threat=attachment["sha256"], threat_id=attachment["sha256"],
                            campaign=f.campaign()))
    return out


def _bec(f: _Factory, times: list[datetime], victim: str | None, ip: str | None) -> list[dict[str, Any]]:
    """Impostor mail from a lookalike of the internal domain; delivered, because it has no payload."""
    lookalike = f"{f.domain.split('.')[0]}-secure.example"
    out: list[dict[str, Any]] = []
    for i, when in enumerate(times):
        exec_name = f.rng.choice(["ceo", "cfo", "vp.finance", "board.secretary"])
        ev = f.message(
            when=when, log_type="message-delivered",
            sender=(exec_name.replace(".", " ").title(), f"{exec_name}@{lookalike}"),
            recipients=_recipients(f, i, victim), subject=f.rng.choice(_BEC_SUBJECTS),
            ip=ip or f.attacker_ip(), impostor=f.rng.randint(75, 100), phish=f.rng.randint(20, 55),
            spam=f.rng.randint(5, 30), modules=("spam", "urldefense", "impostor"),
            reply_to=f"{exec_name}.private@mail-relay.example")
        ev.update(classification="IMPOSTOR", threatStatus="active")
        out.append(ev)
    return out


def _click_chain(f: _Factory, times: list[datetime], victim: str | None, ip: str | None) -> list[dict[str, Any]]:
    """Delivered phishing mail, then the recipients click: some blocked, some let through.

    The first third of the window (at least one event) is messages, the rest are clicks. Click
    `j` belongs to message `j % messages`, so every click follows its message and repeats its
    GUID, recipient and threat, and comes from that recipient's home address. A single event is
    just the message.
    """
    n_msg = max(1, len(times) // 3)
    messages: list[dict[str, Any]] = []
    for i, when in enumerate(times[:n_msg]):
        url = f.url()
        ev = f.message(
            when=when, log_type="message-delivered", sender=f.rng.choice(_THREAT_SENDERS),
            recipients=_recipients(f, i, victim), subject=f.rng.choice(_PHISH_SUBJECTS),
            ip=ip or f.attacker_ip(), phish=f.rng.randint(70, 95), spam=f.rng.randint(0, 30),
            modules=("spam", "urldefense", "pdr"), rewritten=True)
        messages.append(f.threat(ev, classification="PHISHING", threat_type="URL", threat=url,
                                 threat_id=f.hexdigest(256), campaign=f.campaign(), url=url))
    clicks = [f.click(messages[j % n_msg], when=when, blocked=j % 2 == 0,
                      click_ip=f.home_ip(messages[j % n_msg]["recipient"][0]))
              for j, when in enumerate(times[n_msg:])]
    return messages + clicks


def build_events(
    scenario: str, count: int, *, view: OrganizationView, now: datetime,
    spread_seconds: int = 120, start_offset_minutes: int = 0,
    target_user: str | None = None, source_ip: str | None = None, seed: int | None = None,
) -> list[dict[str, Any]]:
    """Build `count` events for `scenario`, oldest first.

    The window ends `start_offset_minutes` before `now` and is `spread_seconds` wide; nothing
    is ever dated after `now`. `target_user` is the recipient of the attack scenarios (default:
    a rotating pool) and `source_ip` the sending mail server (default: a random out-of-country
    address). Both are ignored by `benign_mail`. The recipients are the organization's people (`view`).
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose one of {', '.join(SCENARIOS)}")
    if count < 1:
        raise ValueError("count must be at least 1")
    f = _Factory(view, seed)
    end = now - timedelta(minutes=max(start_offset_minutes, 0))
    times = _times(end, count, spread_seconds)

    if scenario == "benign_mail":
        return _benign(f, times)
    victim = _named_user(f, target_user)
    if scenario == "phishing_url":
        return _url_threat(f, times, victim, source_ip, scores=(80, 100), credential=False)
    if scenario == "credential_phishing":
        return _url_threat(f, times, victim, source_ip, scores=(90, 100), credential=True)
    if scenario == "malware_attachment":
        return _malware(f, times, victim, source_ip)
    if scenario == "bec_impostor":
        return _bec(f, times, victim, source_ip)
    return _click_chain(f, times, victim, source_ip)


def sample_event(*, view: OrganizationView, now: datetime) -> dict[str, Any]:
    """One benign, unmistakably-synthetic delivered message for proving the collector path."""
    f = _Factory(view)
    return f.message(
        when=now, log_type="message-delivered", sender=("Phantom Sender", "phantom-sender@sample-vendor.example"),
        recipients=[f"phantom.test@{view.email_domain}"], subject="Phantom collector test message", ip=f.benign_ip(0))
