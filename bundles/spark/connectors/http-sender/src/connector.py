"""http-sender connector: sends JSON events for any data source to a Cortex XSIAM HTTP Log Collector.

Tools (the runtime strips the `phantom_` prefix, so the agent sees `http-sender/<tool>`):

  phantom_list_destinations  the collectors this instance can send to
  phantom_send_test_event    one identifiable event: proves URL, key and landing for a destination
  phantom_generate_events    synthetic scenarios from a built-in profile (`okta`, `proofpoint_tap`, `google_workspace`,
                             and for the Cribl destinations `aws_cloudtrail`, `gcp_audit`, `azure_ad_audit`, `windows`):
                             benign baselines with stable identities and one detector's recipe with fresh ones
  phantom_send_events        caller-supplied JSON objects, sent exactly as given (for `cribl_windows_events`: structured
                             Windows events, rendered to Windows Event XML here, see windows_events.py)

Each tool takes an optional `destination` (default: the primary one); see destinations.py. A destination is either an
XSIAM HTTP collector or, when criblUrl and the criblToken secret are set, a `cribl_<source>` destination that posts to
the Cortex Cribl integration endpoint under that source's dedicated UUID (see cribl.py). The collector keys and the Cribl
token are read from the instance's secret slots at call time and used only as the Authorization header. No tool returns
one or accepts one as an argument, so the agent never handles a credential.

Identities (the people, their emails, Okta ids and home addresses, the AWS account, GCP project, regions, partner domain and
public egress addresses) are the ACTIVE ORGANIZATION's, read from the shared data volume at call time (see
phantom-connector-runtime/runtime/organization_view.py). An instance can pin one organization with its `organization` setting.
There is no built-in roster: with no organization the tools return {"ok": false, "error": ...} saying what to fix.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from runtime.organization_reader import OrganizationUnavailable
from runtime.organization_view import OrganizationView, get_view

from . import collector, cribl, destinations, profiles, windows_events
from .profiles import _org

logger = logging.getLogger(__name__)

MAX_EVENTS_PER_CALL = 5000


def _settings() -> dict[str, Any]:
    """Merge the instance config over the defaults. Split out so tests can stub it."""
    from config.config import get_config

    cfg = get_config()

    def get(name: str, default: Any = None) -> Any:
        return getattr(cfg, name, default)

    verify = get("verifyTls", True)
    if isinstance(verify, str):
        verify = verify.strip().lower() not in ("false", "0", "no", "off")
    return {
        "url": (get("collectorUrl", "") or "").strip(),
        "key": (get("collectorKey", "") or "").strip(),
        "vendor": (get("vendor", "") or "").strip(),
        "product": (get("product", "") or "").strip(),
        "extra": get("additionalDestinations", "") or "",
        "extra_keys": get("additionalKeys", "") or "",
        # Empty follows the active organization; an id pins one (see _organization).
        "organization": (get("organization", "") or "").strip(),
        "verify_tls": bool(verify),
        "timeout": float(get("timeoutSeconds", 15) or 15),
        "cribl_url": (get("criblUrl", "") or "").strip(),
        "cribl_token": (get("criblToken", "") or "").strip(),
        "cribl_integration": (get("criblIntegration", cribl.DEFAULT_INTEGRATION) or cribl.DEFAULT_INTEGRATION).strip(),
    }


def _field(event: dict[str, Any], path: str) -> Any:
    """`event[path]`, where `path` may be dotted (`id.time`) for a field inside a JSON object."""
    value: Any = event
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _err(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, **extra}


def _organization(settings: dict[str, Any]) -> OrganizationView:
    """The organization the identities come from, read NOW (a save in the UI is seen by the next call): the one the
    `organization` setting pins, else the active one. Raises OrganizationUnavailable when there is none."""
    return get_view(settings.get("organization") or None)


def _resolve(settings: dict[str, Any], wanted: str | None, *, need_ready: bool = True):
    """(destination, None) or (None, error result). `need_ready` also requires a usable URL and key."""
    dests, problems = destinations.load(settings)
    dest, error = destinations.resolve(dests, problems, wanted)
    if error is None and need_ready:
        error = destinations.check(dest)
    return (None, _err(error)) if error else (dest, None)


def _deliver(events: list[Any], dest: destinations.Destination, settings: dict[str, Any],
             **extra: Any) -> dict[str, Any]:
    if dest.source:
        result = cribl.post(
            dest.url, dest.key, cribl.SOURCES[dest.source], events,
            integration=settings.get("cribl_integration") or cribl.DEFAULT_INTEGRATION,
            verify_tls=settings["verify_tls"], timeout=settings["timeout"],
        )
    else:
        result = collector.post_events(
            dest.url, dest.key, events, vendor=dest.vendor, product=dest.product,
            verify_tls=settings["verify_tls"], timeout=settings["timeout"],
        )
    result["destination"] = dest.name
    result["dataset"] = dest.dataset
    result.update(extra)
    if not result["ok"]:
        logger.warning("http-sender: delivery to %s failed: status=%s sent=%s",
                       dest.name, result.get("http_status"), result.get("sent"))
    return result


def _is_windows(dest: destinations.Destination) -> bool:
    return dest.source == cribl.WINDOWS


def _dns(settings: dict[str, Any]) -> str:
    """The DNS suffix that qualifies a short computer name in a Windows event: the organization's."""
    return _organization(settings).dns


def _deliver_windows(items: list[Any], dest: destinations.Destination, settings: dict[str, Any],
                     **extra: Any) -> dict[str, Any]:
    """Render and validate Windows events (structured dicts and/or XML strings), then post the XML as plain strings.
    A bad item returns an error naming it and nothing is sent."""
    try:
        prepared = windows_events.prepare(items, _dns(settings))
    except (ValueError, OrganizationUnavailable) as exc:
        return _err(str(exc))
    result = _deliver([p.xml for p in prepared], dest, settings, **extra)
    result.update(windows_events.summary(prepared))  # not via **extra: its `events` is `_deliver`'s own parameter name
    return result


def _warning(prof, scenario: str, name: str, configured: Any) -> str | None:
    """A caution when the destination is not what the profile (or the scenario) is meant for, else None.

    A scenario that defaults to a Cribl destination warns when sent elsewhere if it can only work through Cribl or if
    that destination is configured (an instance without Cribl behaves as it always did)."""
    expected = tuple(prof.EXPECTED_DATASETS)
    if name not in expected + tuple(getattr(prof, "CRIBL_DESTINATIONS", ())):
        return (f"profile {prof.NAME!r} produces events for "
                f"{' or '.join(repr(d) for d in expected)} "
                f"but the destination is {name!r}")
    wanted = getattr(prof, "SCENARIO_DESTINATION", {}).get(scenario)
    needs_cribl = scenario in getattr(prof, "CRIBL_ONLY_SCENARIOS", ()) or (wanted and wanted in configured)
    if wanted and name != wanted and needs_cribl:
        return (f"scenario {scenario!r} of profile {prof.NAME!r} is meant for the destination {wanted!r}: "
                f"sent to {name!r} it will probably raise no native detection")
    return None


def phantom_list_destinations() -> dict[str, Any]:
    """List the destinations this instance can send to: HTTP collectors and, when configured, Cribl sources.

    Use this first when the operator asks "what can you send to?", or before targeting a
    destination you have not used. An HTTP destination is one XSIAM HTTP collector: its vendor and
    product fix the dataset (`<vendor>_<product>_raw`). When the instance has a Cribl URL and token it also
    has one `cribl_<source>` destination per Cribl source (`cribl_okta_sso`, `cribl_aws_audit`,
    `cribl_gcp_cloud_logging`, `cribl_azure_ad_audit`, `cribl_windows_events`, ...): events sent there are treated by
    Cortex as that vendor's native feed, which is what makes the native Analytics detectors fire (`cribl_windows_events`
    takes the structured Windows events of `wec-sender.send_events`, see `send_events`). The first destination is the
    default for every tool; pass a `destination` name to another tool to send somewhere else. Keys and the
    Cribl token are never shown.

    Returns:
      {"ok": true, "destinations": [{"destination": "okta_sso", "mode": "http", "vendor": "Okta", "product": "SSO",
       "dataset": "okta_sso_raw", "host": "api-tenant.xdr.example", "default": true, "ready": true, "problem": null},
       {"destination": "cribl_aws_audit", "mode": "cribl", "source": "aws_audit", "vendor": "Cribl",
       "product": "AWS CloudTrail", "dataset": "amazon_aws_raw", "host": "api-tenant.xdr.example", "default": false,
       "ready": true, "problem": null}, ...], "problems": [...], "profiles": {...}}
      `ready` is false (with `problem` saying why) when a URL or key is missing. `problems` also says when only one of
      criblUrl and the criblToken secret is set (no Cribl destinations are registered then).
    """
    settings = _settings()
    dests, problems = destinations.load(settings)
    rows = []
    for index, dest in enumerate(dests.values()):
        problem = destinations.check(dest)
        row = {
            "destination": dest.name, "mode": "cribl" if dest.source else "http", "vendor": dest.vendor,
            "product": dest.product, "dataset": dest.dataset, "host": dest.host, "default": index == 0,
            "ready": problem is None, "problem": problem,
        }
        if dest.source:
            row["source"] = dest.source
        rows.append(row)
    return {"ok": bool(rows), "destinations": rows, "problems": problems,
            "profiles": {name: p.DESCRIPTION for name, p in profiles.PROFILES.items()}}


def phantom_send_test_event(destination: str | None = None, profile: str | None = None) -> dict[str, Any]:
    """Send ONE identifiable test event to a destination and report whether it was accepted.

    Use it first after creating or changing an instance, or whenever the operator asks "is the
    collector working?" / "did it land?". Without `profile` the event is a generic JSON object
    (`phantom_test_id`, `phantom_test_time`, `message`) that fits any HTTP collector. With a profile it is
    that source's own benign sample event (e.g. `okta` sends one Okta login), which also proves
    the collector's parsing and modeling see a realistic shape. For a `cribl_<source>` destination with no
    `profile`, the profile built for that source is used (`cribl_aws_audit` sends one CloudTrail record); a Cribl
    source with no profile gets the generic object. `cribl_windows_events` sends one benign Windows 4624 logon,
    rendered to Windows Event XML for you, by a fresh synthetic actor (it takes no `profile`).

    Args:
      destination: which destination, by name (see list_destinations). Default: the primary one.
      profile: optional built-in profile for a realistic sample event (`okta`, `aws_cloudtrail`, `gcp_audit`,
        `azure_ad_audit`, ...).

    Returns:
      {"ok": bool, "sent": 1, "http_status": 200, "response": '{"error":"false"}',
       "destination": "okta_sso", "dataset": "okta_sso_raw", "test_id": "<id>", "sent_at": "<iso>",
       "verify_with_xql": 'dataset = okta_sso_raw | filter phantom_test_id = "<id>"'}
      A Cribl destination also returns "num_records" (what the endpoint counted) and "batch_status".
      `cribl_windows_events` also returns "actor", "logon_id", "event_id" (4624), "test_id_field" ("LogonGuid"),
      "events" (1), "computers", "first_time", "last_time" and "sample_record_ids"; its verify query filters
      `computer_name` (the test id is the event's LogonGuid).
      On failure: {"ok": false, "error": "<what to fix>", "http_status": ...}.

    HTTP 200 only means the endpoint accepted the request. Landing is proven by the returned
    XQL query finding the row (allow about 1-3 minutes).

    Example payload:
      {"destination": "cribl_aws_audit"}
    """
    settings = _settings()
    dest, failure = _resolve(settings, destination)
    if failure:
        return failure
    now = datetime.now(timezone.utc)
    if _is_windows(dest):
        if profile:
            return _err("cribl_windows_events takes no profile: its test event is one rendered Windows 4624 logon")
        test_id = str(uuid.uuid4())
        try:
            event, facts = windows_events.build_test_event(_organization(settings), test_id, now)
        except OrganizationUnavailable as exc:
            return _err(str(exc))
        return _deliver_windows(
            [event], dest, settings, test_id=test_id, test_id_field="LogonGuid", event_id=4624,
            actor=facts["actor"], logon_id=facts["logon_id"], sent_at=windows_events.iso(now),
            verify_with_xql=f'dataset = {dest.dataset} | filter computer_name = "{facts["computer"]}" | sort desc _time | limit 5')
    if not profile and dest.source:
        matched = profiles.for_destination(dest.name)
        profile = matched.NAME if matched else None
    if profile:
        try:
            prof = profiles.get(profile)
        except ValueError as exc:
            return _err(str(exc))
        if getattr(prof, "WINDOWS_EVENTS", False):
            return _err("the windows profile builds structured Windows events for cribl_windows_events: send_test_event to that "
                        "destination (with no profile) sends one 4624, and generate_events sends the scenarios")
        try:
            event, id_field = prof.sample_event(view=_organization(settings), now=now), prof.TEST_ID_FIELD
        except OrganizationUnavailable as exc:
            return _err(str(exc))
        test_id = _field(event, id_field)
    else:
        test_id, id_field = str(uuid.uuid4()), "phantom_test_id"
        event = {id_field: test_id, "phantom_test_time": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                 "message": "Phantom http-sender test event"}
    return _deliver(
        [event], dest, settings, test_id=test_id,
        sent_at=now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        verify_with_xql=f'dataset = {dest.dataset} | filter {id_field} = "{test_id}"',
    )


def phantom_generate_events(
    profile: str,
    scenario: str,
    count: int | None = None,
    spread_seconds: int = 120,
    start_offset_minutes: int = 0,
    target_user: str | None = None,
    source_ip: str | None = None,
    destination: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generate synthetic events from a built-in profile and send them to a destination.

    A profile knows one data source's event shape and scenarios. HTTP-collector profiles: `okta` (Okta
    System Log objects, for the `okta_okta` destination, or `okta_sso`), `proofpoint_tap` (Proofpoint TAP SIEM
    events, for `proofpoint_tap`) and `google_workspace` (Admin SDK Drive/Login activity, for
    `google_workspace_drive`). Cribl profiles (events in the vendor's own API shape, for the `cribl_<source>`
    destinations, which make Cortex treat them as that vendor's native feed so the native Analytics detectors
    fire): `aws_cloudtrail` (`cribl_aws_audit`), `gcp_audit` (`cribl_gcp_cloud_logging`), `azure_ad_audit`
    (`cribl_azure_ad_audit`), `windows` (`cribl_windows_events`: structured Windows events, rendered to Windows Event XML
    for you) and two extra `okta` scenarios for `cribl_okta_sso`. A Cribl profile with no `destination` goes to its own
    Cribl destination and refuses to send if Cribl is not configured (`dry_run` still works); the `windows` profile refuses
    any other destination. For a source without a profile, build the events yourself and use `send_events`.

    Profile `okta`, scenarios:
      benign_logins        alternating user.session.start / user.authentication.sso for the organization's
                           people (those who may log on: no leavers), each from the stable home address the
                           organization gives them (a real Saudi ISP address; Cortex derives country and ASN
                           from it). Baseline traffic.
      failed_then_success  count-1 failed logins (INVALID_CREDENTIALS) for ONE user from ONE
                           out-of-country address, then one success. The identity brute-force shape.
      password_spray       ONE out-of-country address, one failed login per distinct user.
      mfa_fatigue          alternating Okta Verify push sent / push denied for ONE user, then an
                           approval. The MFA-fatigue shape ("Multiple Okta MFA requests").
      Most Okta detectors stay silent over the HTTP collectors; through Cribl "Multiple Okta MFA requests" fires from
      mfa_fatigue and failed_then_success. So when `cribl_okta_sso` is configured, mfa_fatigue, failed_then_success,
      tor_signin and fastpass_phishing all default to it; without Cribl every okta scenario keeps the primary
      destination (tor_signin and fastpass_phishing then return a warning).
      tor_signin           successful SSO by the organization's people (or `target_user`) from a Tor exit, a different
                           exit and a never-seen app per event ("A successful SSO sign-in from TOR"). Defaults to
                           `cribl_okta_sso`; the Tor list is a dated snapshot, pass a current exit as `source_ip`.
      fastpass_phishing    FastPass declined a phishing attempt: a brand-new user and a new Tor exit per event
                           ("Okta FastPass reported phishing attack suspected"). Defaults to `cribl_okta_sso`.

    Profile `proofpoint_tap`, scenarios (target_user = the recipient, source_ip = the sending mail
    server):
      benign_mail          message-delivered mail, some with attachments or CC. Baseline.
      phishing_url         message-blocked mail carrying a malicious URL.
      malware_attachment   message-blocked mail with a malicious attachment (sandbox verdict).
      credential_phishing  message-blocked credential-harvesting mail.
      bec_impostor         message-delivered mail from a lookalike domain, classification IMPOSTOR.
      click_chain          a delivered phishing message, then click-blocked / click-permitted events
                           for the same message GUID and recipient. The user-clicked-a-bad-link shape.

    Profile `google_workspace`, scenarios (target_user = the actor):
      benign_drive         Drive view/download/delete by a pool of users. Baseline.
      public_share         Drive visibility changed to public / shared with an external party.
      sensitive_download   a burst of downloads of sensitive-looking files by ONE actor.
      impossible_travel_login  two logins for ONE actor hours apart from different addresses (needs
                           count >= 2; the gap is in the event time, not the wall clock).
      These events model only on a collector whose dataset is `google_workspace_drive_raw`
      (destination `google_workspace_drive`). Sent to `google_workspace` (dataset
      `google_workspace_raw`) they land raw: no Cortex rule binds to that dataset.

    Cloud profiles (`aws_cloudtrail`, `gcp_audit`, `azure_ad_audit`): each ATTACK scenario is ONE detector's measured
    shape, a short recipe of 1-5 steps by one actor (the minimum `count` is the step count; a larger count repeats the
    recipe with fresh resource ids). Every call invents its own user, role, key and resource ids, so it looks like a
    first-time actor, in the organization's own AWS account / GCP project. target_user = the acting principal, one of the
    organization's people (login, email or the part before the @; the calls then come from that person's home address);
    source_ip = the external address where a scenario has one (below). The one BENIGN scenario of each, `benign_activity`,
    is the opposite and is the baseline the attacks contrast with: STABLE identities (the organization's people who have
    that cloud in `cloud_access`, each with the home address the organization gives them, plus fixed roles / service
    accounts / the IT staff as admins, in the organization's AWS account, GCP project or Azure directory), ordinary
    read-heavy work, and nothing that any detector fires on. `count` events (default 20) spread over `spread_seconds` ending now;
    target_user and source_ip are ignored. Run it on a schedule so the actors an attack recipe contrasts with have a history
    (the benign scenarios are listed after the attack ones below).
      aws_cloudtrail:
        guardduty_detector_deleted, bedrock_logging_deleted, route53_logging_deleted (non-admin role),
        ebs_encryption_disabled        one logging / encryption control switched off
        s3_public_exposure             bucket policy to *, ACL to AllUsers, public-access block removed (3 steps)
        security_group_open            SSH from one external /32 (source_ip) and RDP from 0.0.0.0/0 (2 steps)
        backup_vault_policy_modified   foreign-account principal allowed on a backup vault (IAM user)
        pentest_tool                   6 IAM ListRoles calls with pen-test tool user agents from source_ip (6 steps)
        snapshot_public_share          an EBS and an RDS snapshot shared with `all` (2 steps)
        tor_api_call                   ListUsers + ListBuckets from a Tor exit (source_ip) (2 steps)
        iam_new_admin_identity         role + user created, full-admin policies attached, by an IAM user (5 steps)
        iam_admin_user_credentials     user created, AdministratorAccess attached, access key minted, by a role (3 steps)
      gcp_audit:
        data_asset_public (bucket to allUsers), sensitive_role_to_group (roles/owner to a group),
        k8s_anonymous (anonymous Kubernetes call from source_ip), k8s_vuln_scanner (4 scanner user agents),
        tor_api_call (object read from a Tor exit), new_admin_service_account (create SA, then roles/owner to it)
      azure_ad_audit (one directory-audit operation by a fresh admin):
        ca_policy_deleted, pim_alert_disabled, pim_role_setting_changed, federation_modified, unverified_domain_added
      benign_activity (aws_cloudtrail)  IAM users and their usual roles: ConsoleLogin, ListBuckets, GetObject, ListObjects,
                           DescribeInstances/SecurityGroups/Volumes/DBInstances, ListUsers, ListFunctions, GetCallerIdentity,
                           AssumeRole into a usual role
      benign_activity (gcp_audit)       users and service accounts of one project: storage.objects.get/list, buckets
                           get/list, compute.instances.list, GetServiceAccount, log reads, GetIamPolicy (Data Access logs)
      benign_activity (azure_ad_audit)  four IT admins and twelve users: Update user, Add/Remove member of an ordinary group,
                           Reset password (by admin, the helpdesk admin), Change password (self-service), Add app role
                           assignment grant to user, Add user

    Profile `windows` (destination `cribl_windows_events`; events are structured Windows Security events, see `send_events`;
    the domain is the synthetic PHANTOM / phantom.lab one):
      baseline_logons      benign logons (4624, 4672 for administrators, 4634) of a stable directory: 22 staff, 4 administrators
                           and 4 service accounts on 2 domain controllers, 4 servers and 26 workstations, shaped by the time
                           of day (the same events as `wec-sender.generate_events`). `count` events (default 30) over
                           `spread_seconds` ending now. target_user and source_ip are ignored.
      admin_activity       benign administration by the four IT administrators: helpdesk password resets (4724) and unlocks
                           (4767) of ordinary users, 4738 changes of display name / script path / home directory / password
                           age, ordinary new users created (4720), ordinary users added to and removed from department groups
                           (4728 / 4729, never a privileged group). Same stable directory. Default count 10.
      Attack scenarios, one per Windows trigger skill; each sends exactly the events of that skill's JSON block (the skill
      `trigger_<scenario>_alert` documents the detector), timed as the skill says (now minus N seconds, so `spread_seconds` does
      not apply) with EVERY identity new per call (actor `adm.run<hex>`, RIDs, logon id, hosts, addresses), so each call looks like
      a first-time actor and fires its detector like a manual replay. `count` is the event count of the recipe (a multiple of it
      runs it several times, each with its own identities); target_user = the name of the NEW acting account instead of a generated one (not an organization account; unused by excessive_lockouts and privileged_certificate_request); source_ip = the
      IPv4 address of the attacking host (dcsync, weak_service_tickets, spoofed_samaccountname_tickets). The result names the
      accounts that acted (`actors`) so the alert can be found.
        machine_account_domain_admins (1 event)   a computer account added to Domain Admins (4728)
        privileged_group_add (1)                  a user added to Domain Admins (4728)
        dcsync (5)                                one logon and four replication-right 4662 events by a new user
        guest_account_enabled (1)                 the Guest account enabled (4722)
        sms_admins (1)                            a member added to the local SMS Admins group (4732)
        weak_service_tickets (19)                 RC4 service tickets for 19 SPNs by one account (4769, Kerberoasting)
        excessive_lockouts (16)                   11 accounts locked out from one host (4740)
        samaccountname_change (1)                 a computer account renamed without its trailing $ (4781)
        multiple_account_deletions (6)            six accounts deleted by a new actor (4726)
        hidden_user_created (1)                   a user created with a name ending in $ (4720)
        default_account_masquerade (2)            local DefaultAccount and Guest created on a member server (4720 x 2)
        spoofed_samaccountname_tickets (4)        the noPac shape: rename, TGT, service ticket, rename back (4781, 4768, 4769, 4781)
        shadow_credentials (1)                    msDS-KeyCredentialLink written on a computer object (5136)
        delegation_to_krbtgt (1)                  constrained delegation to krbtgt/PHANTOM.LAB set on a user (4738)
        privileged_certificate_request (1)        a DomainController-template certificate issued to a machine (4887)

    Args:
      profile: the built-in profile: "okta", "proofpoint_tap", "google_workspace", "aws_cloudtrail", "gcp_audit",
        "azure_ad_audit" or "windows".
      scenario: one of the profile's scenarios (above).
      count: total events, 1-5000 (default 20; for a cloud or Windows attack scenario the default is its step count, for
        benign_activity 20, baseline_logons 30, admin_activity 10). Failed-then-success and MFA fatigue need >= 2; a cloud
        scenario needs at least its step count and repeats its recipe beyond that; a Windows attack scenario needs a whole
        number of recipes (its event count, 2x, 3x, ...).
      spread_seconds: width of the time window the events are spread across (default 120).
      start_offset_minutes: end the window this many minutes in the past (default 0 = now).
        Set when the operator says "back-date" / "make these older". The event's own timestamp
        field carries the time (Okta: `published`, TAP: `messageTime`/`clickTime`, Google: `id.time`, AWS: `eventTime`,
        GCP: `timestamp`, Azure: `activityDateTime`); the dataset's `_time` follows it ONLY when the
        source's content pack (its parsing rule) is installed on the tenant, otherwise `_time` is
        the ingestion time.
      target_user: victim login for okta failed_then_success / mfa_fatigue / tor_signin, the recipient (TAP), the
        actor (Google, or the acting principal of a cloud attack scenario). It must be one of the ACTIVE
        ORGANIZATION's people, by login, email or the part of the email before the @ (an unknown value returns an error
        that lists the valid emails); the default is the organization's first person (cloud scenarios invent
        a fresh actor instead). The WINDOWS attack scenarios are the exception: every one except excessive_lockouts and
        privileged_certificate_request (which have no acting account and ignore it) acts as a NEW account, because the
        detectors fire on first-time activity, so there target_user names that new account (a bare name of letters,
        digits, dots, dashes and underscores, at most 20, e.g. `adm.run1`) and must NOT be an organization account
        (that returns an error). Never use `DOMAIN\\user`. Ignored by every benign_activity / baseline_logons /
        admin_activity scenario.
      source_ip: attacker address for the attack scenarios (default a random real out-of-country
        address; for Proofpoint TAP the sending mail server, for Google Workspace the actor's
        address in public_share / sensitive_download and the far login of impossible_travel_login; for the cloud
        scenarios and okta tor_signin / fastpass_phishing the external or Tor address, where a current Tor exit
        is worth passing because the built-in list is a dated snapshot).
      destination: which destination, by name (see list_destinations). Default: the primary one, except that a
        Cribl profile (and okta tor_signin / fastpass_phishing / mfa_fatigue / failed_then_success) uses its
        `cribl_<source>` destination when it is configured. A warning is returned when it is not one the profile is meant for;
        the `windows` profile accepts only `cribl_windows_events`.
      dry_run: true = build and return the first 3 events without sending anything (needs no credentials).

    Returns:
      {"ok": bool, "sent": int, "batches": int, "http_status": int, "destination": "okta_sso",
       "dataset": "okta_sso_raw", "profile": "okta", "scenario": ..., "first_time": iso,
       "last_time": iso, "sample_ids": [...]}
      A Cribl destination also returns "num_records" (what the endpoint counted) and "batch_status".
      The `windows` profile also returns "actors" (the accounts that acted: look the alert up by them), "events", "computers",
      "first_time", "last_time" and "sample_record_ids" (sample_ids are "<event id>@<computer>").
      dry_run adds "events": [...] and sends nothing.

    Identities (users, emails, Okta ids, home addresses, the AWS account, GCP project, regions and the partner domain)
    come from the active organization, so the same person is the same entity in every profile and connector. With no
    organization the call returns {"ok": false, "error": ...}.

    Example payload (use a person of the active organization as target_user):
      {"profile": "okta", "scenario": "failed_then_success", "count": 12,
       "target_user": "<login or email of a person of the organization>", "spread_seconds": 90}
      {"profile": "aws_cloudtrail", "scenario": "s3_public_exposure", "count": 3}
      {"profile": "aws_cloudtrail", "scenario": "benign_activity"}
      {"profile": "windows", "scenario": "baseline_logons", "count": 40, "spread_seconds": 1500}
      {"profile": "windows", "scenario": "dcsync"}
      {"profile": "okta", "scenario": "tor_signin", "count": 4, "destination": "cribl_okta_sso"}
    """
    settings = _settings()
    try:
        prof = profiles.get(profile)
    except ValueError as exc:
        return _err(str(exc), profiles=sorted(profiles.PROFILES))
    wanted = destination
    unconfigured = None
    known = destinations.load(settings)[0]
    if count is None:
        # An omitted count is the scenario's own default (a baseline scenario), else one full recipe for a Cribl-only
        # profile (not 20 GuardDuty deletes), else 20.
        count = getattr(prof, "DEFAULT_COUNT", {}).get(scenario) or (
            getattr(prof, "MIN_COUNT", {}).get(scenario, 1) if getattr(prof, "CRIBL_ONLY", False) else 20)
    if not (wanted or "").strip():
        default = profiles.default_destination(prof, scenario)
        if default and destinations.normalize(default) in known:
            wanted = default
        elif default and getattr(prof, "CRIBL_ONLY", False):
            # Never fall back to the primary HTTP collector: a CloudTrail record must not land in an Okta dataset.
            unconfigured = default
    if unconfigured and not dry_run:
        return _err(f"profile {prof.NAME!r} sends to the Cribl destination {unconfigured!r}, which is not configured: "
                    "set criblUrl and the criblToken secret (see list_destinations), or name another destination")
    if unconfigured:
        dest, failure = None, None
        name = unconfigured
        dataset = cribl.SOURCES[unconfigured.removeprefix(cribl.PREFIX)].dataset
    else:
        dest, failure = _resolve(settings, wanted, need_ready=not dry_run)
        if failure:
            return failure
        name, dataset = dest.name, dest.dataset
        if getattr(prof, "WINDOWS_EVENTS", False) and not _is_windows(dest):
            return _err(f"profile {prof.NAME!r} sends structured Windows events, which only the destination "
                        f"{cribl.destination_name(cribl.WINDOWS)!r} takes (it renders them to Windows Event XML); "
                        f"{name!r} is not that destination")
    if count > MAX_EVENTS_PER_CALL:
        return _err(f"count must not exceed {MAX_EVENTS_PER_CALL} per call")
    # A pattern needs a minimum number of events (a lockout storm, a two-step MFA fatigue). A caller that asks for fewer
    # still wants the pattern, so raise the count to the minimum and say so, instead of failing with an error to retry.
    asked = count
    if scenario in ("failed_then_success", "mfa_fatigue") and count < 2:
        count = 2
    needed = getattr(prof, "MIN_COUNT", {}).get(scenario)
    if needed and count < needed:
        count = needed
    try:
        events = prof.build_events(
            scenario, count, view=_organization(settings), now=datetime.now(timezone.utc),
            spread_seconds=spread_seconds, start_offset_minutes=start_offset_minutes,
            target_user=target_user, source_ip=source_ip,
        )
    except OrganizationUnavailable as exc:
        return _err(str(exc))
    except _org.UnknownUser as exc:
        return _err(str(exc))
    except ValueError as exc:
        return _err(str(exc), scenarios=list(prof.SCENARIOS))
    sample_id = getattr(prof, "sample_id", None) or (lambda e: _field(e, prof.TEST_ID_FIELD))
    summary: dict[str, Any] = {
        "profile": prof.NAME, "scenario": scenario,
        "sample_ids": [sample_id(e) for e in events[:5]],
        "first_time": _field(events[0], prof.TIME_FIELD), "last_time": _field(events[-1], prof.TIME_FIELD),
    }
    if hasattr(prof, "describe"):
        summary.update(prof.describe(events))
    if count != asked:
        summary["count_raised"] = {"asked": asked, "used": count, "why": f"{scenario} needs at least {count} event(s) to form its pattern"}
    warning = _warning(prof, scenario, name, known)
    if warning:
        summary["warning"] = warning
    if dry_run:
        return {"ok": True, "dry_run": True, "sent": 0, "destination": name,
                "dataset": dataset, "events": events[:3], **summary}
    if getattr(prof, "WINDOWS_EVENTS", False):
        return _deliver_windows(events, dest, settings, **summary)
    return _deliver(events, dest, settings, **summary)


def phantom_send_events(events: list[dict[str, Any]], destination: str | None = None) -> dict[str, Any]:
    """Send caller-supplied JSON objects to a destination, exactly as given.

    Use when the operator has a specific event shape to test, or for any source that has no
    profile. Each item must be one JSON object in the shape the destination's collector (and its
    parsing and modeling rules) expects. Nothing is added or rewritten; build them yourself or
    start from `generate_events(dry_run=true)`. Put the event time in the field the source's
    parsing rule reads (Okta: `published`, an ISO-8601 string like "2026-09-30T10:15:20.123Z").

    For a `cribl_<source>` destination send the vendor's own event object (an Okta System Log event, a CloudTrail
    record, a Cloud Logging LogEntry, a Graph directoryAudit object), one per list item and NOT wrapped: the
    connector wraps each in the `{"data": ...}` envelope the Cribl endpoint requires.

    For `cribl_windows_events` (Windows Event Logs) pass STRUCTURED Windows events, exactly as for
    `wec-sender.send_events`: the connector renders each to Windows Event XML for you, so do NOT build XML by hand and
    do not wrap anything. Catalogued ids (4624, 4625, 4634, 4672) need only `event_id`, `computer` and `event_data`;
    any other id also needs `provider`, `rendering.message` and `rendering.task`. Give `time` (ISO-8601 UTC, or epoch
    seconds) to back-date; the default is now. A short computer name gets the active organization's DNS suffix. A string item that is
    already Windows Event XML (starts with `<Event`) is passed through unchanged. Every item is validated first: a bad
    one returns an error naming it and nothing is sent. No Broker, certificate or WEC subscription is involved; the
    rows land in `microsoft_windows_raw` with `_transport = cribl` (and no `_collector_type`). AD FS events still need
    the real WEC path (`wec-sender`).

    Args:
      events: list of 1-5000 JSON objects (for `cribl_windows_events`: structured Windows events as described above,
        or XML strings).
        Windows event fields: event_id (int, required), computer (required), channel (default Security), provider,
        time, event_data (object = named Data, or list = positional Data), outcome ("success" | "failure"),
        rendering ({message, level, task, opcode, channel, provider, keywords}), and optional System overrides:
        version, level, task, opcode, record_id, process_id, thread_id, activity_id, message.
      destination: which destination, by name (see list_destinations). Default: the primary one.

    Returns:
      {"ok": bool, "sent": int, "batches": int, "http_status": int, "destination": "okta_sso",
       "dataset": "okta_sso_raw"}
      A Cribl destination also returns "num_records" (what the endpoint counted) and "batch_status".
      `cribl_windows_events` also returns "events", "computers" (count per computer), "first_time", "last_time" and
      "sample_record_ids".

    Example payload:
      {"destination": "okta_sso",
       "events": [{"eventType": "user.session.start", "published": "2026-09-30T10:15:20.123Z",
                   "outcome": {"result": "SUCCESS"}, "actor": {"alternateId": "<a person's email>"}}]}
      {"destination": "cribl_aws_audit",
       "events": [{"eventVersion": "1.11", "eventTime": "2026-10-04T17:23:37Z", "eventSource": "guardduty.amazonaws.com",
                   "eventName": "DeleteDetector", "awsRegion": "us-east-1", "sourceIPAddress": "188.55.20.23"}]}
      {"destination": "cribl_windows_events",
       "events": [{"event_id": 4728, "computer": "PHDC02", "time": "2026-10-05T10:15:00Z",
                   "provider": "Microsoft-Windows-Security-Auditing",
                   "rendering": {"message": "A member was added to a security-enabled global group.\\n\\nSubject:\\n\\tSecurity ID:\\t\\tS-1-5-21-3623811015-3361044348-30300820-3301\\n\\tAccount Name:\\t\\tadm.run3301\\n\\tAccount Domain:\\t\\tPHANTOM\\n\\tLogon ID:\\t\\t0x9A4C21\\n\\nMember:\\n\\tSecurity ID:\\t\\tS-1-5-21-3623811015-3361044348-30300820-3302\\n\\tAccount Name:\\t\\tCN=Run Member 3302,OU=Users,DC=phantom,DC=lab\\n\\nGroup:\\n\\tSecurity ID:\\t\\tS-1-5-21-3623811015-3361044348-30300820-512\\n\\tGroup Name:\\t\\tDomain Admins\\n\\tGroup Domain:\\t\\tPHANTOM\\n\\nAdditional Information:\\n\\tPrivileges:\\t\\t-",
                                 "task": "Security Group Management"},
                   "event_data": {"MemberName": "CN=Run Member 3302,OU=Users,DC=phantom,DC=lab",
                                  "MemberSid": "S-1-5-21-3623811015-3361044348-30300820-3302",
                                  "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-3301",
                                  "SubjectUserName": "adm.run3301", "SubjectDomainName": "PHANTOM",
                                  "SubjectLogonId": "0x9A4C21", "TargetUserName": "Domain Admins",
                                  "TargetDomainName": "PHANTOM",
                                  "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-512",
                                  "PrivilegeList": "-"}}]}
    """
    settings = _settings()
    dest, failure = _resolve(settings, destination)
    if failure:
        return failure
    if not isinstance(events, list) or not events:
        return _err("events must be a non-empty list of JSON objects")
    if len(events) > MAX_EVENTS_PER_CALL:
        return _err(f"at most {MAX_EVENTS_PER_CALL} events per call")
    if _is_windows(dest):
        return _deliver_windows(events, dest, settings)
    if not all(isinstance(e, dict) for e in events):
        return _err("every item in events must be a JSON object")
    return _deliver(events, dest, settings)


__all__ = ["phantom_list_destinations", "phantom_send_test_event", "phantom_generate_events", "phantom_send_events"]
