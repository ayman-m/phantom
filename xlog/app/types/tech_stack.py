"""Strawberry GraphQL types for the technology stack.

The "technology stack" is the org's catalog of vendor/product combos
(Fortinet/FortiGate, CrowdStrike/Falcon, …) that the agent biases
log-generation toward. It lives behind two GraphQL fields on the Query
root:

  - `technologyStack` ............... read the current stack
  - `updateTechnologyStack(stack:)` . replace the current stack

Update is exposed as a `@strawberry.field` (not `@strawberry.mutation`)
to match the rest of this schema's convention — every "mutating" op in
xlog is registered on Query today. When this schema gains a Mutation
root, this should move with the rest.

# Why three nested types

`LogDestination` and `VendorEntry` are nested rather than flat strings
because the agent reads them programmatically: it picks `log_destination
.full_address` as the default sink for `phantom_create_data_worker`, and
matches `vendor` × `product` × `formats` when generating realistic logs
for a specific device class. A flat string would force the agent to
re-parse on every read.

# Backwards compat

`TECHNOLOGY_STACK` env var stays valid as a boot-time fallback. When
the sqlite singleton is empty AND the env var is set, reads return the
env-var value with `source = "env"`. After a successful mutation, the
sqlite copy wins on subsequent reads (`source = "manual"`).
"""

from __future__ import annotations

from typing import List, Optional

import strawberry


@strawberry.type(description="Default log destination for generated logs.")
class LogDestination:
    type: str
    protocol: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    full_address: Optional[str] = None


@strawberry.type(description="A single vendor/product entry in the org's stack.")
class VendorEntry:
    vendor: str
    product: str
    category: str
    formats: List[str]
    description: Optional[str] = None


@strawberry.type(description="The org's technology stack — vendor catalog plus default sink.")
class TechnologyStack:
    stack_name: Optional[str]
    log_destination: Optional[LogDestination]
    vendors: List[VendorEntry]
    total_vendors: int
    configured: bool
    updated_at: Optional[str]
    source: str  # "manual" | "env" | "default"


@strawberry.input(description="Default log destination input.")
class LogDestinationInput:
    type: str
    protocol: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    full_address: Optional[str] = None


@strawberry.input(description="Vendor/product entry input.")
class VendorEntryInput:
    vendor: str
    product: str
    category: str
    formats: List[str]
    description: Optional[str] = None


@strawberry.input(description="Replacement payload for the technology stack — full overwrite.")
class TechnologyStackInput:
    stack_name: str
    vendors: List[VendorEntryInput]
    log_destination: Optional[LogDestinationInput] = None


# ─── Conversion helpers ──────────────────────────────────────────────


def stack_dict_to_type(stack: dict) -> TechnologyStack:
    """Convert the dict shape returned by `store.get_technology_stack()`
    into the Strawberry output type. The dict already has all the
    expected keys (the store normalizes), so this is mostly a typed
    rehydration."""
    log_dest_dict = stack.get("log_destination")
    log_destination: Optional[LogDestination] = None
    if isinstance(log_dest_dict, dict):
        log_destination = LogDestination(
            type=str(log_dest_dict.get("type") or ""),
            protocol=log_dest_dict.get("protocol"),
            host=log_dest_dict.get("host"),
            port=(
                int(log_dest_dict["port"])
                if log_dest_dict.get("port") is not None
                else None
            ),
            full_address=log_dest_dict.get("full_address"),
        )

    vendors_list = stack.get("vendors") or []
    vendors: List[VendorEntry] = []
    for entry in vendors_list:
        if not isinstance(entry, dict):
            continue
        formats = entry.get("formats") or []
        if not isinstance(formats, list):
            formats = []
        vendors.append(
            VendorEntry(
                vendor=str(entry.get("vendor") or ""),
                product=str(entry.get("product") or ""),
                category=str(entry.get("category") or ""),
                formats=[str(f) for f in formats],
                description=entry.get("description"),
            )
        )

    return TechnologyStack(
        stack_name=stack.get("stack_name"),
        log_destination=log_destination,
        vendors=vendors,
        total_vendors=int(stack.get("total_vendors", len(vendors))),
        configured=bool(stack.get("configured", False)),
        updated_at=stack.get("updated_at"),
        source=str(stack.get("source") or "default"),
    )


def input_to_dict(stack: TechnologyStackInput) -> dict:
    """Convert the Strawberry input into the dict shape `store
    .update_technology_stack()` expects. Strawberry has already validated
    that required fields are present, so we just flatten."""
    log_dest = None
    if stack.log_destination is not None:
        ld = stack.log_destination
        # Auto-derive `full_address` if the operator didn't provide one
        # (matches the env-var convention so reads are predictable).
        full_address = ld.full_address
        if not full_address and ld.protocol and ld.host and ld.port is not None:
            full_address = f"{ld.protocol}:{ld.host}:{ld.port}"
        log_dest = {
            "type": ld.type,
            "protocol": ld.protocol,
            "host": ld.host,
            "port": ld.port,
            "full_address": full_address,
        }
    return {
        "stack_name": stack.stack_name,
        "log_destination": log_dest,
        "vendors": [
            {
                "vendor": v.vendor,
                "product": v.product,
                "category": v.category,
                "formats": list(v.formats or []),
                "description": v.description,
            }
            for v in (stack.vendors or [])
        ],
    }
