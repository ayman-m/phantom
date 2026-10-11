# wec-sender

Delivers **synthetic Windows events** to a Cortex XSIAM Broker VM's **Windows Event Collector (WEC)** applet over
WS-Management (source-initiated forwarding, mutual TLS to TCP 5986), so they ingest with `_collector_type = "WEC"`.

It is a bundle connector: the release manifest pins its image by digest, it is installed from the marketplace and it runs as
its own container.

## Why this exists, and the doctrine exception

Phantom delivers synthetic telemetry over syslog/CEF only (root `CLAUDE.md`). WEC is a deliberate, scoped exception,
like `http-sender`, because some feeds cannot be produced any other way:

- an event forwarded over WEC lands in `microsoft_windows_raw` with `_collector_type = "WEC"`, with `event_data` as a JSON
  object, the Windows schema's columns filled from the event's rendered text, and **48** `xdm.*` fields from one 4624;
- every forwarded event also creates `xdr_data` rows keyed by the event's Computer (`EVENT_LOG`, and a `LOGIN_EVENT`
  for a 4624): the endpoint and identity feed a CEF source cannot create;
- an `AD FS Auditing` event 1200 reaches `microsoft_adfs_raw` through the pack's own parsing rule, whose `WEC` gate
  is unreachable over syslog/CEF.

It never replaces syslog/CEF for validating or promoting a data source's mapping. All output is synthetic and is sent
only to the operator's own broker.

## Event times

In `send_events`, an event's `time` may be written relative to the connector's own clock: `now`, `now-120s`, `now-5m` or `now-1h` (an absolute `YYYY-MM-DDTHH:MM:SSZ` still works). A model has no clock of its own, and an event stamped in the past does not trigger Analytics, so the skills use this form instead of asking the model to work out a timestamp.

## Prerequisites

1. In the Cortex console, create a **Windows Event Collector** configuration on the Broker VM. It gives you:
   - the **Subscription Manager** value, `Server=HTTPS://<broker fqdn>:5986/wsman/SubscriptionManager/WEC,Refresh=600,IssuerCA=<sha1>`;
   - a client certificate bundle (**PFX**) and its password. The PFX also contains the CA.
2. The connector's container must reach the broker on TCP 5986.

## Create the instance (operator)

The PFX and its password are secret slots (credential side of the catalog/credential boundary): the instance is created
by the operator, from the WEC Sender card on `/connectors` or over the REST surface, so they never pass through the agent.

| Field | Kind | Meaning |
|---|---|---|
| `subscriptionManagerUrl` | config, required | The console value as issued (a bare `https://` URL also works). `IssuerCA`, when present, is checked against the CA inside the PFX. |
| `clientPfx` | secret, required | The PFX as base64 text (about 4.7 KB; `base64 < client.pfx \| tr -d '\n'`). Whitespace and newlines are ignored. |
| `clientPfxPassword` | secret, required | The PFX password. |
| `senderComputerName` | config | Name the sender announces when it enumerates (default `phantom-wec-sender.phantom.lab`). |
| `timeoutSeconds` | config | Per-request timeout (default 30). |
| `domainNetbios` / `domainDns` | config | The synthetic domain (defaults `PHANTOM` / `phantom.lab`). |
| `hostCount` | config | Hosts in the synthetic domain, 8 to 100 (default 32). The 2 DCs and 4 servers always exist; the rest are workstations. |

There is no `verifyTls` option: verification is not optional.

Then ask the agent to run `list_subscriptions` (the connection test) and `send_test_event`.

## Tools

| Tool | What it does |
|---|---|
| `list_subscriptions` | Enumerates the collector's subscriptions (name, version, delivery path, max envelope, heartbeat, channels, query preview). Doubles as the connection test. |
| `send_test_event` | One identifiable 4624 (or 4625, 4672; for 4634 the 4624 is sent first, then the paired 4634 with the same logon id, and both are reported) from `PHANTOM-WECTEST01.<domainDns>`; returns a test id (the event's `LogonGuid`) and the XQL query that finds it: `dataset = microsoft_windows_raw \| filter _collector_type = "WEC" and computer_name = "<name>"`. |
| `generate_events` | Profile `windows`, scenario `baseline_logons`: `count` (1-5000), `spread_seconds` (1-604800), `start_offset_minutes` (back-dating, 0-1051200), `dry_run` (returns the first 3 events with their XML). |
| `send_events` | Caller-supplied **structured** events (`event_id`, `computer`, `channel`, `provider`, `time`, `event_data` as an object or a list, `outcome`, `rendering` overrides, System overrides), rendered to Windows Event XML by the connector. 1 to 5000 per call. |

No tool returns or accepts a secret. Results never carry the PFX, its password or key material.

**What `sent` means.** `sent` is the number of events the applet **accepted with HTTP 200**. It does not prove they landed: landing is proven only by running the XQL query a tool returns (`verify_with_xql`) and finding the row.

## The `windows` profile

A small synthetic domain whose **identities are pure functions of names**, so a baseline accumulates history on the
tenant: the same login always has the same SID and home workstation; the same host the same address.

- 2 domain controllers (`PHDC01`, `PHDC02`), 4 servers (`PHSRV-FS01`, `-APP01`, `-SQL01`, `-WEB01`), 26 workstations
  (`PHWS-001` to `PHWS-026`); `Computer` is the FQDN `<name>.<domainDns>`. The probe hosts `PHTM-WEC-*` are never used.
- About 30 accounts: 22 staff, 4 administrators (`adm.*`), 4 service accounts (`svc-*`), domain SID
  `S-1-5-21-3623811015-3361044348-30300820`, RIDs from 1105.
- `baseline_logons`: interactive (type 2), unlock (7) and cached (11) logons on a user's home workstation in business hours
  (Saudi local time, Sunday to Thursday), network (3) logons on servers and DCs, service accounts around the clock, a little
  administrator RDP (10) with 4672 special privileges, and a **4634 logoff for each 4624 later in the window** with the same
  `TargetLogonId`. Source IP and `WorkstationName` are the user's home workstation. The result has exactly `count` events made of
  whole sessions; when `count` leaves one event over, it is a last 4624 (at most one session is left open). A logoff that would
  fall after the window ends is placed at a random moment before the end, so a short window does not pile them on one timestamp.

More scenarios (failed logons, Kerberos, LDAP enumeration, AD FS) plug into `profiles/windows.SCENARIOS`; new event ids are
one `EventDef` in `src/winevent.py` (the module header lists the next ones and the shape each needs).

## What the applet does with an event (drives the renderer)

`_time` is `System/TimeCreated@SystemTime` (so back-dating works); `event_action` is `RenderingInfo/Task`, `message` is
`RenderingInfo/Message`, `log_level` is `RenderingInfo/Level`; `event_result` is `failure` when `RenderingInfo/Keywords` holds
`Audit Failure`; `event_data` is the JSON of `EventData/Data` (named Data by `Name`, **unnamed Data as `param1..paramN`**).
So the renderer always writes real `RenderingInfo` text for the event id, never placeholders; an id outside the catalogue
must be given `provider`, `rendering.message` and `rendering.task`.

## Protocol and provenance

The WS-Management client in `src/wsman.py` is written from the public specifications: DMTF DSP0226 (WS-Management), W3C
WS-Eventing (2004/08), WS-Enumeration (2004/09), WS-Addressing (2004/08), SOAP 1.2, Microsoft MS-WSMV, and the Windows Event
XML schema, plus the applet's own `EnumerateResponse`, kept as `tests/fixtures/enumerate_response.xml` (sanitized).

1. **Enumerate** `POST /wsman/SubscriptionManager/WEC`, `Content-Type: application/soap+xml;charset=UTF-16`, UTF-16LE body with a
   BOM. Done at the start of every tool call (and again after the `Refresh` interval or a failed delivery). Each subscription
   carries a delivery address, an `e:Identifier` that is **new on every Enumerate** (never cached), and `MaxEnvelopeSize`.
2. **Deliver** `POST` to the subscription's delivery path: an `Events` envelope, one `wsman:Event` per event with the Event XML in
   CDATA, `MachineID` = the events' Computer, the Identifier from the same Enumerate. HTTP 200 with an empty body is success;
   anything else is a failure. Uncompressed delivery is accepted (no SLDC).
3. **Batching and routing**: encoded size is measured in real UTF-16LE bytes (4 for characters above U+FFFF) and kept under 80% of the
   subscription's `MaxEnvelopeSize`; an envelope never mixes computers. Every batch is planned before the first delivery, so an event
   that cannot be sent fails the whole call with nothing delivered. Security-channel events go to `Authentication Event Logs`, everything else to
   `ForwardedEvents`, falling back to the first subscription. The applet does not filter by the subscription's query today.
4. **Failure**: on a non-200 the subscriptions are enumerated again and that one envelope is retried once; envelopes already
   delivered are never resent.

## Security

- Mutual TLS, TLS 1.2 minimum. The server is verified against **only** the CA that issued the client certificate (name and
  signature checked, a look-alike with the same name is refused); other certificates in the PFX and the system trust store are
  never trusted. The applet's certificate has a CN and no subjectAltName, so the name is checked by hand right after the
  handshake and before any request is sent; a mismatch raises. Verification is never disabled.
- The private key is never written in the clear: it is exported as an encrypted PEM with a one-time passphrase to tmpfs
  (`/dev/shm` when present), loaded, and deleted in a `finally`.
- Errors name the problem (wrong password, wrong IssuerCA, bad base64, certificate mismatch) without echoing a secret.

## Not verified offline

Everything above is tested against an in-process fake applet and the saved reply. Not covered offline: the real applet's
acceptance of these exact envelopes, heartbeat and re-enumeration (`Version` change) behavior, bookmarks, SLDC, the maximum rate,
and whether the Windows-gated Analytics detectors fire from a baselined host set. The Pull half of WS-Enumeration is not
implemented (the applet answers an optimized Enumerate in one reply).

## Build and install

The release build produces the image and the release manifest pins it as
`DIGEST_PHANTOM_CONNECTOR_WEC_SENDER`; the YAML has no `image:` field on purpose. Install it from the marketplace, then
create the instance. To build it locally (the build context is the repo root):

```bash
docker build -f bundles/spark/connectors/wec-sender/Dockerfile \
  --build-arg PHANTOM_RUNTIME_VERSION=dev -t phantom-connector-wec-sender:local .
```

Tests (no network; loopback only): `cd bundles/spark/connectors/wec-sender && python3 -m pytest -x -q`.
