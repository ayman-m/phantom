# http-sender

Sends JSON events for **any data source** to a Cortex XSIAM **HTTP Log Collector**, or (**Cribl mode**) to the Cortex
Cribl integration endpoint under a source's dedicated UUID. Okta, Proofpoint TAP, Google Workspace, AWS CloudTrail,
GCP Cloud Audit, Azure AD audit and Windows Security events are built in as event profiles (benign baselines with stable
identities, and one scenario per proven detector with fresh ones); every other source is sent with `send_events` (you or
the agent supply the events).

It is a bundle connector: the release manifest pins its image by digest, it is installed from the marketplace and it runs as its own container.

## One collector, one destination

An XSIAM HTTP collector has a fixed **vendor** and **product** (its dataset is `<vendor>_<product>_raw`), its
own **URL** and its own **key**. Phantom allows one active instance per connector, so an instance holds a
primary destination in plain fields and any others in two optional fields. A destination's name is its dataset
without `_raw` (`okta_sso`, `proofpoint_email_security`).

1. In XSIAM: Settings > Data Sources & Integrations > Custom Collectors > HTTP Log Collector. Log Format **JSON**,
   set Vendor and Product, **Save & Generate Token**, copy the URL and the key (shown once).
2. In Phantom: Connectors > http-sender > Create instance. The form starts with a **Destination** switch (`destinationMode`: `http`,
   `cribl` or `both`) that shows only the fields of the kind you choose; the connector itself ignores the value. The fields
   below are the HTTP collector kind (required for `http` and `both`).
   - `collectorUrl`, `vendor`, `product` and the `collectorKey` secret: the primary destination.
   - `additionalDestinations` (optional), more collectors as JSON:
     `[{"url": "https://api-<tenant>/logs/v1/event", "vendor": "Proofpoint", "product": "Email Security"}]`
   - `additionalKeys` (optional secret), their keys, by destination name:
     `{"proofpoint_email_security": "<key>"}`
3. Ask the agent to `list_destinations`, then `send_test_event` for each one.

The agent only ever sees destination names, vendors, products, datasets and the URL's host. Keys and the Cribl token are
read from the secret store at call time and never returned, logged or accepted as an argument.

## Event times

In `send_events`, an event's `time` may be written relative to the connector's own clock: `now`, `now-120s`, `now-5m` or `now-1h` (an absolute `YYYY-MM-DDTHH:MM:SSZ` still works). A model has no clock of its own, and an event stamped in the past does not trigger Analytics, so the skills use this form instead of asking the model to work out a timestamp.

## Tools

| Tool | What it does |
|---|---|
| `list_destinations` | The destinations this instance can send to (HTTP collectors and `cribl_<source>`), whether each is ready, and the built-in profiles. |
| `send_test_event` | One identifiable event (generic, or a profile's own sample; `cribl_windows_events` sends one rendered Windows 4624) and an XQL query that proves it landed. |
| `generate_events` | Synthetic events from a profile: `okta` (benign_logins, failed_then_success, password_spray, mfa_fatigue, tor_signin, fastpass_phishing), `proofpoint_tap` (benign_mail, phishing_url, malware_attachment, credential_phishing, bec_impostor, click_chain), `google_workspace` (benign_drive, public_share, sensitive_download, impossible_travel_login), and the Cribl profiles `aws_cloudtrail`, `gcp_audit`, `azure_ad_audit` (each with a `benign_activity` baseline) and `windows` (benign `baseline_logons` and `admin_activity`, and 15 attack scenarios): see Cribl mode and "Scenarios for scheduled jobs". |
| `send_events` | Caller-supplied JSON objects, sent exactly as given. Works for any source. For `cribl_windows_events` the objects are **structured Windows events** (the `wec-sender` shape), rendered to Windows Event XML by the connector (see Cribl mode, Windows). |

Every tool except `list_destinations` takes an optional `destination` (default: the primary one).

## Cribl mode

The tenant has a Cribl integration endpoint (the one Cribl Stream's Cortex XSIAM destination posts to). A request that
carries a data source's **dedicated** `Source-Identifier` UUID is treated by Cortex as that vendor's **native feed**: the
rows get the source's own collector type, parsing, normalized audit rows (`cloud_audit_logs`, `authentication_story`)
and the out-of-the-box Analytics detectors, none of which the generic HTTP collector or syslog produces. In testing, this path
raised alerts for 25 distinct out-of-the-box detectors.

**Config.** Create a Cribl collector in the tenant (Settings > Data Sources & Integrations), then on the instance:

| Field | Kind | Meaning |
|---|---|---|
| `criblUrl` | config, optional | The endpoint, `https://api-<tenant>/logs/v1/integrated/cribl/data`. Must be https and end in that path: an HTTP collector's `/logs/v1/event` URL is refused (its dataset would be polluted). |
| `criblToken` | **secret slot**, optional | The collector's token. Sent as the raw `Authorization` header; never returned, logged or accepted as an argument. Printable ASCII only (no spaces or control characters): anything else is refused with a fixed message, without being sent or quoted. |
| `criblIntegration` | config, optional | The `Integration-Identifier` header; it becomes `_collector_name` on the rows. Default `phantom-http-sender`. |

When **both** `criblUrl` and `criblToken` are set, one destination per Cribl source is registered automatically:
`cribl_okta_sso`, `cribl_azure_ad_signins`, `cribl_azure_ad_audit`, `cribl_azure_event_hub`, `cribl_aws_audit`,
`cribl_gcp_cloud_logging`, `cribl_windows_events`, `cribl_proofpoint_tap` (the source's UUID and dataset are in `src/cribl.py`).
`list_destinations` shows them (`mode: cribl`, `source`, `dataset`, `host`) and reports a problem when only one of the two is set.
The existing HTTP destinations are unchanged; the primary stays the default destination. An instance can have only the Cribl
fields: with no collector URL, vendor or product it has no primary and `list_destinations` reports that as a problem, while the
`cribl_<source>` destinations work. In the form, choose `cribl` (or `both`) in the **Destination** switch to show these fields.

**Wire.** `POST` to `criblUrl` with `Authorization: <token>`, `Source-Identifier: <uuid>`, `Format: json`,
`Integration-Identifier: <name>`. The body is NDJSON, 300 events per request, and **each line is wrapped
`{"data": <the vendor's event object>}`** (an unwrapped line lands as `_raw_log` only). The answer is
`{"num_records": N, "success": "true"}`; a different count or `success` counts as a failure. `send_events` takes the vendor
object unwrapped. `num_records` may arrive as an int or a string of digits. The results add `num_records` and `batch_status`.
Cribl posts use a timeout of at least 60 seconds, never follow a redirect, and never resend a batch whose answer was lost (a read
timeout may mean it landed); only a failed connection, a 429 or a gateway error is retried. A transport failure is reported by
exception type only, and the collector key gets the same treatment on the HTTP path.

**Profiles.** `generate_events` with a Cribl profile and no `destination` goes to that profile's own Cribl destination and
**refuses to send** when Cribl is not configured (it never falls back to the primary HTTP collector). `dry_run` always works.
`okta` keeps the primary as its default, except that **when Cribl is configured** `tor_signin`, `fastpass_phishing`, `mfa_fatigue` and
`failed_then_success` default to `cribl_okta_sso` (the Okta detectors are silent over the HTTP collector; "Multiple Okta MFA requests"
fired from the last two through Cribl). Without Cribl the primary HTTP collector is the default destination. An omitted `count` is one full recipe for a
cloud scenario, and 20 for everything else.
`send_test_event` to a `cribl_<source>` destination sends that source's profile sample (a generic object when it has no profile).

Every cloud scenario is the shape of one detector's proven variant (variants that stayed silent are not
included). A scenario is a recipe of 1-5 steps by one actor, so the minimum `count` is its step count; a larger `count` repeats
the recipe with fresh resource ids. Account ids, IAM users/roles/sessions, access keys, projects, service accounts, admin
UPNs and domains are invented **per call**, so each call looks like a first-time actor. `eventTime` is now (or back-dated
with `start_offset_minutes`), and addresses are real: ordinary actors from the Saudi home pool, scanners from the abroad pool,
Tor scenarios from a Tor exit. `okta.tor_signin` is the one exception: it follows the proven recipe, which uses the
**baseline pool users** with a never-seen app and a new exit per event, so its actors are the pool's unless you pass `target_user`.

| Detector | Profile.scenario | Notes |
|---|---|---|
| A successful SSO sign-in from TOR | `okta.tor_signin` | Needs a live Tor exit (list below); baseline users, new app per event. Default `cribl_okta_sso`. |
| Okta FastPass reported phishing attack suspected | `okta.fastpass_phishing` | New user and new Tor exit per event (dedup is 1 day). Default `cribl_okta_sso`. |
| Multiple Okta MFA requests | `okta.mfa_fatigue`, `okta.failed_then_success` | Default to `cribl_okta_sso` when configured; `count` >= 2. |
| AWS Guard-Duty detector deletion | `aws_cloudtrail.guardduty_detector_deleted` | |
| AWS S3 bucket was exposed to public access | `aws_cloudtrail.s3_public_exposure` | 3 steps (policy `*`, ACL AllUsers, block removed). |
| AWS Bedrock model invocation logging deleted | `aws_cloudtrail.bedrock_logging_deleted` | |
| AWS Route53 DNS Resolver query logging deleted by a non-admin | `aws_cloudtrail.route53_logging_deleted` | Acts as a non-admin role (`ci-deploy-runner-*`). |
| AWS Security Group remote access from an unknown external IP | `aws_cloudtrail.security_group_open` | `source_ip` = the external /32 for SSH; RDP from 0.0.0.0/0. |
| Cloud snapshot configured for public access / publicly shared / shared public | `aws_cloudtrail.snapshot_public_share` | One scenario for the family: an EBS and an RDS snapshot shared with `all` raised all three. |
| Disable encryption operations | `aws_cloudtrail.ebs_encryption_disabled` | |
| Cloud penetration testing tool activity | `aws_cloudtrail.pentest_tool` | 6 steps, one tool user agent each, from an abroad address (`source_ip`). |
| A Backup vault policy was modified | `aws_cloudtrail.backup_vault_policy_modified` | Must be an IAM user with a foreign-account principal Allow; the same policy via an assumed role stayed silent. |
| Suspicious API call from a Tor exit node | `aws_cloudtrail.tor_api_call`, `gcp_audit.tor_api_call` | Needs a Tor exit (`source_ip` to override). |
| Cloud activity from an unusual high-risk IP | `aws_cloudtrail.tor_api_call`, `gcp_audit.tor_api_call` | Raised by the same Tor events as the row above; needs a high-risk (Tor) IP. |
| New cloud identity created with administrative policy | `aws_cloudtrail.iam_new_admin_identity`, `gcp_audit.new_admin_service_account` | AWS: an IAM user, 5 steps (an assumed role stayed silent). GCP: create the SA, then `roles/owner` to it. |
| Administrative IAM User Created with Credentials | `aws_cloudtrail.iam_admin_user_credentials` | An assumed role: CreateUser, AdministratorAccess, CreateAccessKey. |
| GCP data asset shared public | `gcp_audit.data_asset_public` | Bucket IAM to `allUsers`. |
| GCP sensitive role granted to group | `gcp_audit.sensitive_role_to_group` | `roles/owner` to a group. |
| A Kubernetes API operation was successfully invoked by an anonymous user outside the cluster | `gcp_audit.k8s_anonymous` | `system:anonymous` from a public address (`source_ip`). |
| External Kubernetes vulnerability scanning tool usage | `gcp_audit.k8s_vuln_scanner` | 4 steps, one scanner user agent each. |
| Conditional Access policy removed | `azure_ad_audit.ca_policy_deleted` | |
| Azure AD PIM alert disabled | `azure_ad_audit.pim_alert_disabled` | |
| A successful Azure domain federation settings modification | `azure_ad_audit.federation_modified` | A new domain name each call. |
| Azure AD PIM role settings change | `azure_ad_audit.pim_role_setting_changed` | |
| Rare unverified domain addition to Azure AD | `azure_ad_audit.unverified_domain_added` | The domain must be new: it is invented per call. |

Alerts typically arrive within seconds to a few minutes. Several detectors dedup (FastPass 1 day), so repeat with a fresh actor
(the cloud profiles do this by themselves; for `tor_signin` pass a new `target_user`).

**The Tor list is a dated snapshot.** `ippools.TOR_EXITS` holds 19 exits (flagged `TOR_PROXY` by Cortex) for the Okta
scenarios, and `ippools.CLOUD_TOR_EXITS` holds 7 exits observed in AWS/GCP testing for `aws_cloudtrail.tor_api_call` and
`gcp_audit.tor_api_call` (the provenance and snapshot dates are in `ippools.py`). Exits leave the network, and a departed exit silently stops firing
the Tor detectors, so when one stops, refresh the list from a host with internet (the check.torproject.org bulk exit list,
or `https://torstatus.rueckgr.at/ip_list_exit.php/Tor_ip_list_EXIT.csv`) and update the dates in `ippools.py`; until then
pass a current exit as `source_ip`. An address that is not in the snapshot is accepted and still gets the Tor flags in Okta events.

**XDM.** AWS, GCP and Azure rows land without XDM unless the packs that carry their modeling rules are installed on the
tenant; the detectors do not need it. The test-event verify query filters the vendor's own id column
(`eventID`, `insertId`, `id`); if it finds nothing, filter on `_collector_name = "<criblIntegration>"` instead.

### Windows

The `cribl_windows_events` destination (Windows Event Logs, UUID in `src/cribl.py`, dataset `microsoft_windows_raw`) carries the
Windows identity detectors with **no Broker VM, no client certificate and no WEC subscription**. The event XML that `wec-sender` delivers over WEC, posted through
this endpoint, fires the same nine detectors that fire over WEC (the nine `trigger_*_alert` Windows skills).

- **Same events as `wec-sender`.** `send_events(events, destination="cribl_windows_events")` takes exactly the structured events
  `wec-sender.send_events` takes (`event_id`, `computer`, `time`, `provider`, `channel`, `event_data` as an object or a list,
  `outcome`, `rendering`, System overrides, 1 to 5000 per call), with the same validation. The connector renders each to Windows
  Event XML itself with `src/winevent.py`, a copy of `wec-sender/src/winevent.py` (two container images cannot share code, so
  the two must stay in step: `tests/test_windows_events.py` loads both and compares their XML byte for byte for the nine skills'
  events). **Never hand-build the XML.** A string item that already is Windows Event XML (starts with `<Event`) is checked for
  well-formedness (no DOCTYPE or ENTITY) and then passed through unchanged. Every item is validated before anything is sent: a
  bad one returns an error naming it (`events[3].time must be ...`) and nothing is posted.
- **The plain-string rule.** Each posted line is `{"data": "<Event xmlns=...>...</Event>"}`: the XML is ONE PLAIN STRING. Wrapped
  in an object (`{"data": {"_raw": "<Event ...>"}}`) the endpoint answers 200 and lands **nothing**, so `cribl.post` refuses a
  non-string event for this source. Posting stays on `cribl.post` (300 lines per request, same headers and token handling as every
  other source).
- **Config.** None of its own: the DNS suffix that qualifies short computer names (`PHDC02` becomes `PHDC02.phantom.lab`; a name
  with a dot is left alone), the NetBIOS domain and the SID base are the ACTIVE ORGANIZATION's (or the one the instance's
  `organization` setting pins), read at call time. `<Computer>` is byte-for-byte what `wec-sender` renders for the same
  organization.
- **`send_test_event`** (`destination = cribl_windows_events`, no `profile`) sends one benign network 4624 for host
  `<NETBIOS>-CRIBLTEST01.<dns>` (the organization's) from an address in its `unmanaged` network, by a **fresh actor** (`phantom.test<6 hex>`), the test id in `LogonGuid`, and returns an XQL query
  on `computer_name` that proves the row landed.
- **`generate_events`** has a `windows` profile (see "Scenarios for scheduled jobs"): it builds the structured events
  and sends them here, and refuses any other destination. Another profile's object events sent to this destination keep the
  destination-mismatch warning, and `cribl.post` then refuses them (an object lands nothing).
- **How it differs from `wec-sender`.** No Broker, no WS-Management, no mutual-TLS certificate, no subscription: the only credential
  is the Cribl token. The rows carry `_transport = "cribl"` and **no `_collector_type`** (WEC rows carry `_collector_type = "WEC"`);
  the other columns and the `xdm.*` fields are the same. **AD FS still needs WEC**: its parsing rule requires
  `_collector_type = "WEC"` (not tested over Cribl), so `microsoft_adfs_raw` events go through `wec-sender`.

Example (one 4728, a user added to Domain Admins; the message is shortened here, and the `trigger_*_alert` skills carry the
full layout, which a non-catalogued id such as 4728 needs kept):

```json
{"destination": "cribl_windows_events",
 "events": [{"event_id": 4728, "computer": "PHDC02", "time": "now-300s",
             "provider": "Microsoft-Windows-Security-Auditing",
             "rendering": {"message": "A member was added to a security-enabled global group.", "task": "Security Group Management"},
             "event_data": {"MemberName": "CN=Run Member 3302,OU=Users,DC=phantom,DC=lab",
                            "MemberSid": "S-1-5-21-3623811015-3361044348-30300820-3302",
                            "SubjectUserSid": "S-1-5-21-3623811015-3361044348-30300820-3301",
                            "SubjectUserName": "adm.run3301", "SubjectDomainName": "PHANTOM", "SubjectLogonId": "0x9A4C21",
                            "TargetUserName": "Domain Admins", "TargetDomainName": "PHANTOM",
                            "TargetSid": "S-1-5-21-3623811015-3361044348-30300820-512", "PrivilegeList": "-"}}]}
```

## Scenarios for scheduled jobs

The scheduler can only call a tool with fixed arguments, so every scenario below works from `generate_events(profile, scenario, ...)`
alone: events are built at CALL time (current timestamps) and, for the attack scenarios, with fresh identities. Two rules, opposite
on purpose:

- **Benign scenarios have STABLE identities.** A baseline is only a baseline if the same actors come back. Their names, ids, keys
  and home addresses are pure functions of an index (`profiles/_fresh.py`: `person`, `stable`, `stable_guid`), so the same people
  appear on every call, run after run. The cloud personas are the organization's people (the same users as in Okta) (`noura.alharbi` ... `dana.alanazi`), each with
  the same home address in every profile (`ippools.home_for`); AWS, GCP and Azure each use one fixed account, project or tenant
  that no attack scenario ever uses. Timestamps are current: `count` events spread at random moments over `spread_seconds` ending now
  (the first at the start of the window, the last at its end; `start_offset_minutes` back-dates it).
- **Attack scenarios have FRESH identities.** The detectors count what an actor did for the first time in 30 days and deduplicate for a
  day, so every call invents its actor, RIDs, logon ids, hosts and addresses (below), never reuses one within the process, and
  shares none with the baseline. `count` is the recipe's event count; a whole multiple runs it several times, each run with its own
  identities.

| Profile.scenario | What it does | Detector, or benign |
|---|---|---|
| `aws_cloudtrail.benign_activity` | 12 IAM users and their usual roles (DataAnalyst, ReadOnlyAuditor, AppSupport, BillingViewer) in one fixed account: ConsoleLogin, ListBuckets, GetObject, ListObjects, DescribeInstances / SecurityGroups / Volumes / DBInstances, ListUsers, ListFunctions, GetCallerIdentity, AssumeRole into a usual role, from the home pool | benign |
| `gcp_audit.benign_activity` | the organization's people with GCP access and its service accounts, in one project: storage.objects.get / list, buckets get / list, compute.instances.list, GetServiceAccount, ListLogEntries, GetIamPolicy (Data Access logs) | benign |
| `azure_ad_audit.benign_activity` | the IT admins and the organization's people: Update user (job title, department, office, manager), Add / Remove member of an ordinary group, Reset password (by admin, done by the helpdesk admin), Change password (self-service), Add app role assignment grant to user, Add user | benign |
| `windows.baseline_logons` | 4624 / 4672 / 4634 of the 30-account, 32-host domain (22 staff, 4 administrators, 4 service accounts; 2 DCs, 4 servers, 26 workstations), shaped by the time of day; the same events as `wec-sender.generate_events` | benign |
| `windows.admin_activity` | the four IT administrators on the DCs: helpdesk password resets (4724) and unlocks (4767) of ordinary users, 4738 changes (display name, script path, home directory, password age), ordinary new users (4720), ordinary users added to / removed from department groups `SG-Finance`, `SG-HR`, `SG-Sales`, `SG-Engineering`, `SG-VPN-Users`, `SG-Project-Atlas` (4728 / 4729) | benign |
| `windows.machine_account_domain_admins` | 1 x 4728: a computer account added to Domain Admins | Machine account was added to a domain admins group (and User added to a Windows privileged group) |
| `windows.privileged_group_add` | 1 x 4728: a user added to Domain Admins | User added to a Windows privileged group |
| `windows.dcsync` | 4624 then 4 x 4662 with the DS-Replication rights, by a new ordinary user | Possible DCSync by an unusual user |
| `windows.guest_account_enabled` | 1 x 4722: the Guest account (RID 501) enabled | A user enabled the Windows default Guest account |
| `windows.sms_admins` | 1 x 4732: a member added to the local `SMS Admins` group | User added to the SMS Admins local group |
| `windows.weak_service_tickets` | 19 x 4769, RC4 (0x17), 19 distinct SPNs, one new account, about 7.5 minutes | Abnormal issuance of weakly encrypted service tickets to a user |
| `windows.excessive_lockouts` | 16 x 4740: 11 new accounts locked out from one new host over about 12 minutes | Excessive user account lockouts |
| `windows.samaccountname_change` | 1 x 4781: a computer account renamed without its trailing `$` | Suspicious sAMAccountName change |
| `windows.multiple_account_deletions` | 6 x 4726 by one new actor over 75 seconds | A user deleted multiple users for the first time |
| `windows.hidden_user_created` | 1 x 4720 on a DC: a user whose name ends in `$` | Suspicious hidden user created |
| `windows.default_account_masquerade` | 2 x 4720 on a member server: local `DefaultAccount` and `Guest` created | Masquerading as a default local account (one alert per account) |
| `windows.spoofed_samaccountname_tickets` | 4781, 4768, 4769, 4781: the noPac shape on a new DC name | TGT request / Service ticket request with a spoofed sAMAccountName (and Suspicious sAMAccountName change) |
| `windows.shadow_credentials` | 1 x 5136: `msDS-KeyCredentialLink` added to a computer object | Possible shadow credentials addition |
| `windows.delegation_to_krbtgt` | 1 x 4738: `AllowedToDelegateTo` set to `krbtgt/PHANTOM.LAB` on a new user | User account delegation to KRBTGT |
| `windows.privileged_certificate_request` | 1 x 4887 on `PHCA01`: a `DomainController`-template certificate for a new machine | Suspicious privileged certificate request via certificate template |

The cloud attack scenarios keep their own table (Cribl mode). All the `windows` scenarios go only to `cribl_windows_events`.

**The Windows attack scenarios are the skills' own events.** `src/profiles/windows_recipes.json` holds the first JSON block of each
`trigger_<scenario>_alert` skill verbatim, `<CHANGE: label>` placeholders included (two container images cannot read the skill files,
so they are embedded; `tests/test_windows_profile.py` fails if a skill's block changes and the file does not). Every call fills the
manual recipe's (the tests render both and compare them):

| Label | Value, new on every call |
|---|---|
| `now minus N s` | the window's end (now, or now minus `start_offset_minutes`) minus N seconds; `spread_seconds` does not apply |
| `actor` | `adm.run<6 hex>` (`svc.run<6 hex>` for `weak_service_tickets`), or `target_user` |
| `actor RID`, `machine RID`, `member RID`, `lockout RID n`, `repeat lockout RID`, `deleted RID n` | a random number from 100000 to 90 million, all different (the skills ask for 3300, 3500 or 4000 or more; the directory's RIDs are 1000 to 1134, the groups' 2101 to 2106, the test event's 5000 to 94999) |
| `actor logon id` | `0x` and six hex digits |
| `machine`, `attacker host`, `caller host` | `PHWS-<5 digits>` (the directory has `PHWS-001` to `PHWS-026`); `svcprint<5 digits>` for the hidden account (`hidden_user_created`); `PHSRV-WEB<4 digits>` for the member server of `default_account_masquerade` |
| `attacker IP`, `client IP` | `10.20.<100-199>.<20-250>`, outside the directory's ranges, or `source_ip` |
| `member display name` | `Run Member <5 digits>` |
| `lockout user n`, `repeat lockout user`, `deleted user n` | `l.u<6 hex>`, `l.rpt<6 hex>`, `tmp.sw<6 hex>` |
| `PHDC<actor RID>` (the DC of `spoofed_samaccountname_tickets`) | follows the actor RID, as the skill says |

A label has one value wherever it appears. Within a call no two values of one kind are equal, and (for an unseeded call) no value is ever drawn twice
by the same process; a restart of the container starts the record again, and the ranges are wide enough that a repeat is then
astronomically unlikely, not impossible. The result's `actors` lists the accounts that acted, so the alert is found by them.
`target_user` and `source_ip` are validated (an account of letters, digits, dots, dashes and underscores, at most 20, no `$`; an IPv4 address).

**Benign scenarios are not guaranteed silent.** The cloud and Windows benign scenarios are built from the proven attack shapes and the skills'
notes on what stays silent, and are checked by tests (no detector's event name, group, address or flag appears in them). Whether
Cortex Analytics raises nothing on them depends on the tenant: run each with `dry_run=false` once and check `dataset = alerts`
before scheduling it. The Windows benign layouts for ids the skills do not carry (4724, 4729, 4767) follow the Windows message
text and have not been validated against a tenant; 4720 and 4738 reuse the skills' layouts.

## Client IPs

Cortex derives country, city, ASN and ISP from the actual IP and ignores any label in the event, so the profiles use
real, geo-resolvable addresses from `src/profiles/ippools.py` instead of documentation ranges. Both pools were
verified with Cortex's `iploc` stage; the module header records the provenance.

- **Home** (24 Saudi /24s across four regional ISPs): each user has one stable address, the same
  on every run and in all three profiles. Benign events, and a click in `proofpoint_tap`, come from it.
- **Abroad** (18 non-Saudi /24s): attack scenarios default to a random address from it, so an attacker is never in
  a home range. `proofpoint_tap` keeps the first six for benign senders and sends every attack from the other twelve.
- **Tor exits** (`ippools.TOR_EXITS` and `CLOUD_TOR_EXITS`, dated snapshots, see Cribl mode): the Tor scenarios draw from it. They are not iploc-verified and sit in no home or abroad range.
- `source_ip` overrides the default; its geography is the pool range it sits in, or empty for any other address.

## Datasets

The `okta` profile suits both Okta collectors: `okta_okta` (vendor Okta, product Okta; the preferred one, which populates 58 distinct
`xdm.*` fields from one event) and `okta_sso` (vendor Okta, product SSO). `google_workspace` models on
`google_workspace_drive`. The Cribl profiles are meant for their `cribl_<source>` destination (`aws_cloudtrail` for `cribl_aws_audit`,
`gcp_audit` for `cribl_gcp_cloud_logging`, `azure_ad_audit` for `cribl_azure_ad_audit`, okta `tor_signin` and `fastpass_phishing` for `cribl_okta_sso`). A destination outside a profile's list still receives the events, with a warning.

## Adding a profile

A profile is a module under `src/profiles/` that follows the interface documented in `src/profiles/__init__.py`
(`NAME`, `SCENARIOS`, `build_events`, `sample_event`, ...), plus one line in `PROFILES`. A profile for a Cribl source also declares
`CRIBL_DESTINATIONS`, `DEFAULT_DESTINATION` / `SCENARIO_DESTINATION`, `CRIBL_ONLY`, `MIN_COUNT`, `BENIGN_SCENARIOS` and `DEFAULT_COUNT` (documented there);
the `windows` profile also sets `WINDOWS_EVENTS` and provides `sample_id` and `describe`. Keep everything
source-specific there; the transport and the tool layer stay generic.

## What landing proves

HTTP 200 means the collector accepted the request. The event is in the dataset a minute or two later. `_time`
follows the event's own timestamp field only when the source's content pack (its parsing rule) is installed on the
tenant; without the pack the dataset is raw-only and `_time` is the ingestion time.

## Build and install

The release build produces the image and the release manifest pins it as
`DIGEST_PHANTOM_CONNECTOR_HTTP_SENDER`; the YAML has no `image:` field on purpose. Install it from the marketplace, then
create an instance. To build it locally (the build context is the repo root):

```bash
docker build -f bundles/spark/connectors/http-sender/Dockerfile \
  --build-arg PHANTOM_RUNTIME_VERSION=dev -t phantom-connector-http-sender:local .
```

Tests: `cd bundles/spark/connectors/http-sender && python3 -m pytest -x` (no network).
