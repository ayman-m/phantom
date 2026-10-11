"""Asset generation — synthesize a host fleet and create it in Cortex XSIAM.

WHY THIS IS A SEPARATE TOOL FROM LOG GENERATION. Cortex models assets in a
subsystem that log ingestion cannot reach: a CEF event carrying the same
flat `xdm_asset_*` columns the first-party `panw_ad_hygiene_*_raw` datasets
use lands as a dataset row and creates no asset, and `xdm.asset.*` is not in
the event XDM schema at all, so no parsing or modeling rule can emit one.
The only door open to an external system is the Vulnerability Ingest /
"Bring Your Own Scanner" API, which the `xsiam_assets` destination type
implements.

WHAT MAKES THIS USEFUL RATHER THAN DECORATIVE — CORRELATION. Assets that
share no identifiers with the log stream produce two disconnected views: an
inventory nobody references and alerts about hosts that do not exist. This
tool therefore RETURNS the fleet it created. The caller pins those same
addresses into log generation via `phantom_create_data_worker`'s
`observables_dict`, so an IP in a Cisco ASA event resolves to a real asset
carrying real findings. That linkage is the point of generating assets at
all; generating a fleet and never referencing it is the failure mode this
docstring exists to prevent.

DELIBERATE LIMITS, none of which this tool can lift:

  * The platform types BYOS assets, not the caller. A record submitted with
    `provider: AWS` / `asset_type: EC2_INSTANCE` materialises as
    `xdm.asset.provider = OTHER` and `xdm.asset.type.id = GENERIC_DEVICE_IP`
    (verified on a live tenant). There is no payload shaping that produces
    cloud-typed assets, so this tool does not pretend to offer a provider
    knob. Properly-typed AWS/AZURE/GCP assets come only from first-party
    cloud discovery, which runs from Palo Alto's own SaaS.
  * The endpoint allows 10 requests per hour. One call here is ONE request
    regardless of `count`, so prefer a single large fleet over repeated
    small calls.

The destination is passed as a `logdest:<id>` reference, never a raw key.
Resolution happens here, MCP-side, which is the only place that can read
both `log_destinations.db` and the SecretStore — so the destination's API
key never crosses the agent's tool surface. Same property the
`log_destination_resolver` gives `phantom_create_data_worker`.
"""

from __future__ import annotations

import ipaddress
import logging
import random
import time
from typing import Any

logger = logging.getLogger("Phantom MCP")

# A small, real, well-known set. Real CVE ids matter: they resolve in the
# Cortex UI to actual advisories, so a demo inventory reads as plausible
# rather than as obvious filler.
_DEFAULT_CVES: list[tuple[str, str, str]] = [
    ("CVE-2021-44228", "Apache Log4j2 JNDI RCE (Log4Shell)", "critical"),
    ("CVE-2021-4034", "polkit pkexec local privilege escalation (PwnKit)", "high"),
    ("CVE-2022-22965", "Spring Framework RCE (Spring4Shell)", "critical"),
    ("CVE-2023-4863", "libwebp heap buffer overflow", "high"),
    ("CVE-2024-3094", "xz-utils backdoor in liblzma", "critical"),
    ("CVE-2020-1472", "Netlogon elevation of privilege (Zerologon)", "critical"),
    ("CVE-2019-0708", "Remote Desktop Services RCE (BlueKeep)", "critical"),
    ("CVE-2022-30190", "MSDT remote code execution (Follina)", "high"),
    ("CVE-2023-23397", "Microsoft Outlook elevation of privilege", "high"),
    ("CVE-2021-34527", "Windows Print Spooler RCE (PrintNightmare)", "critical"),
]

_OS_FLEET: list[tuple[str, str]] = [
    ("Windows Server 2022", "win"),
    ("Windows Server 2019", "win"),
    ("Windows 11 Pro", "win"),
    ("Ubuntu 22.04.4 LTS", "nix"),
    ("Red Hat Enterprise Linux 9.3", "nix"),
    ("Amazon Linux 2023", "nix"),
]

_ROLE_BY_OS: dict[str, list[str]] = {
    "win": ["dc", "file", "app", "sql", "wks"],
    "nix": ["web", "api", "db", "build", "proxy"],
}


def _mac(rng: random.Random) -> str:
    # Locally-administered unicast prefix (02:) — never collides with a real
    # vendor OUI, so synthetic hosts stay identifiable as synthetic.
    return "02:" + ":".join(f"{rng.randint(0, 255):02x}" for _ in range(5))


def _build_fleet(
    count: int,
    subnet: str,
    hostname_prefix: str,
    with_vulnerabilities: bool,
    cve_ids: list[str] | None,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Synthesize `count` hosts inside `subnet`.

    Addresses are taken in order from the subnet's host range rather than at
    random so a fleet is contiguous and reproducible for a given subnet —
    which makes the IPs easy to reference later in log generation.
    """
    net = ipaddress.ip_network(subnet, strict=False)
    hosts = net.hosts()
    now_ms = int(time.time() * 1000)

    pool: list[tuple[str, str, str]] = []
    if cve_ids:
        known = {c[0]: c for c in _DEFAULT_CVES}
        for cid in cve_ids:
            pool.append(known.get(cid, (cid, cid, "medium")))
    else:
        pool = list(_DEFAULT_CVES)

    fleet: list[dict[str, Any]] = []
    for i in range(count):
        try:
            ip = str(next(hosts))
        except StopIteration:
            logger.warning(
                "asset fleet truncated at %d: subnet %s has no more addresses",
                i, subnet,
            )
            break

        os_name, family = _OS_FLEET[i % len(_OS_FLEET)]
        role = _ROLE_BY_OS[family][i % len(_ROLE_BY_OS[family])]
        hostname = f"{hostname_prefix}-{role}-{i + 1:03d}"

        asset: dict[str, Any] = {
            # The hostname already carries the prefix, and the platform
            # stores asset_id verbatim as `byos:<asset_id>` — prefixing again
            # here produced `byos:phantom-phantom-web-001` in the inventory.
            "asset_id": hostname,
            "last_seen": now_ms,
            "first_seen": now_ms - rng.randint(1, 60) * 86_400_000,
            "hostname": hostname,
            "name": hostname,
            "ip_address": ip,
            "mac_address": _mac(rng),
            "os": os_name,
            "source": "phantom",
        }

        if with_vulnerabilities and pool:
            picks = rng.sample(pool, k=min(rng.randint(1, 3), len(pool)))
            asset["vulnerabilities"] = [
                {
                    "vulnerability_id": f"{hostname}-{cid}",
                    "cve_id": [cid],
                    "name": title,
                    "severity": sev,
                    "description": f"{title} detected on {hostname} ({os_name}).",
                    "last_seen": now_ms,
                }
                for cid, title, sev in picks
            ]

        fleet.append(asset)
    return fleet


async def phantom_generate_assets(
    *,
    destination: str,
    count: int = 25,
    subnet: str = "10.20.0.0/24",
    hostname_prefix: str = "phantom",
    with_vulnerabilities: bool = True,
    cve_ids: list[str] | None = None,
    seed: int | None = None,
    dry_run: bool = False,
    ctx: Any = None,
) -> dict[str, Any]:
    """Generate a fleet of host assets and create them in Cortex XSIAM.

    Assets are a SEPARATE subsystem from logs — generating logs never creates
    an asset, so an inventory has to be populated deliberately with this
    tool. Use it when the operator wants the Asset Inventory, Exposure
    Management or risk views to have something in them.

    CORRELATE THE FLEET WITH LOG GENERATION. This returns every hostname and
    IP it created. Feed those same values into
    `phantom_create_data_worker`'s `observables_dict` so the events reference
    hosts that actually exist in the inventory. An asset fleet nobody
    references is the main way this feature gets used wrong.

    Args:
        destination: A `logdest:<id>` reference to a destination of type
            `xsiam_assets`. Resolved MCP-side; the API key is never exposed.
            Use `log_destinations_list` to find one.
        count: How many hosts to create. ONE request is sent regardless of
            count, and the endpoint allows only 10 requests/hour, so prefer
            one large fleet over repeated small calls.
        subnet: CIDR the fleet's addresses come from, taken in order.
            Pick a range that matches the environment the logs describe.
        hostname_prefix: Leading token of each hostname
            (`<prefix>-<role>-<n>`, e.g. `phantom-web-001`).
        with_vulnerabilities: Attach 1-3 real CVEs per host. Set False for a
            clean inventory with no findings.
        cve_ids: Restrict findings to these CVE ids, e.g. to build a scenario
            around one vulnerability. Defaults to a curated well-known set.
        seed: Fix the RNG so a fleet is reproducible across calls.
        dry_run: Build and return the fleet WITHOUT sending it. Use this to
            show the operator what would be created, or to get the
            hostname/IP list for log generation before committing.

    Returns:
        sent / failed / errors, the upstream `job_id`, and `assets`: the
        `{hostname, ip, os}` list to correlate against.
    """
    if count < 1:
        return {"sent": 0, "failed": 0, "errors": ["count must be >= 1"], "assets": []}

    try:
        ipaddress.ip_network(subnet, strict=False)
    except ValueError as e:
        return {"sent": 0, "failed": 0, "errors": [f"invalid subnet: {e}"], "assets": []}

    rng = random.Random(seed)
    fleet = _build_fleet(
        count, subnet, hostname_prefix, with_vulnerabilities, cve_ids, rng,
    )
    if not fleet:
        return {"sent": 0, "failed": 0, "errors": ["subnet has no usable hosts"], "assets": []}

    summary = [
        {"hostname": a["hostname"], "ip": a["ip_address"], "os": a["os"]}
        for a in fleet
    ]
    correlation = (
        "Pin these IPs/hostnames into phantom_create_data_worker's "
        "observables_dict so the generated logs reference hosts that exist "
        "in the inventory."
    )

    if dry_run:
        return {
            "sent": 0,
            "failed": 0,
            "errors": [],
            "dry_run": True,
            "assets": summary,
            "correlation_hint": correlation,
        }

    # Resolve the destination here, MCP-side — the only place that can read
    # both the destination store and the SecretStore.
    from usecase.destination_handler_registry import dispatch_send
    from usecase.log_destinations_store import get_log_destination_store

    if not isinstance(destination, str) or not destination.startswith("logdest:"):
        return {
            "sent": 0,
            "failed": len(fleet),
            "errors": [
                "destination must be a 'logdest:<id>' reference to an "
                "xsiam_assets destination; call log_destinations_list to find one"
            ],
            "assets": summary,
        }

    dest_id = destination[len("logdest:"):].strip()
    store = get_log_destination_store()
    row = store.get(dest_id)
    if row is None:
        return {
            "sent": 0, "failed": len(fleet),
            "errors": [f"log destination {dest_id!r} not found"], "assets": summary,
        }
    if row.type_id != "xsiam_assets":
        return {
            "sent": 0, "failed": len(fleet),
            "errors": [
                f"destination {dest_id!r} is type {row.type_id!r}; assets need an "
                "'xsiam_assets' destination. Log destinations (syslog/xsiam_http) "
                "cannot create assets — Cortex ignores asset shape on the log path."
            ],
            "assets": summary,
        }

    merged = store.merged_config(dest_id) or {}
    try:
        result = await dispatch_send(row.type_id, merged, fleet)
    except Exception as e:  # noqa: BLE001
        logger.exception("asset dispatch failed")
        return {
            "sent": 0, "failed": len(fleet),
            "errors": [f"{type(e).__name__}: {e}"], "assets": summary,
        }

    out = dict(result)
    out["assets"] = summary
    out["correlation_hint"] = correlation
    return out
