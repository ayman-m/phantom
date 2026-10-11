"""Destinations: the HTTP collectors one http-sender instance can send to.

An XSIAM HTTP collector has a fixed vendor and product (its dataset is
`<vendor>_<product>_raw`), its own URL and its own key. So "any data source over HTTP"
means one collector per source. Phantom allows a single active instance per connector, so
the instance carries a primary destination in plain fields and any number of additional
ones in two optional fields:

  collectorUrl / vendor / product + the `collectorKey` secret     the primary destination
  additionalDestinations   JSON array: [{"url": ..., "vendor": ..., "product": ...}, ...]
  additionalKeys           secret, JSON object: {"<destination>": "<key>", ...}
  criblUrl + the `criblToken` secret   the Cortex Cribl integration endpoint; when both are set one
                           destination `cribl_<source>` is registered per Cribl source (see cribl.py)

A destination is addressed by its name, the dataset without `_raw` (`okta_sso`). The agent
only ever sees names, vendors, products, datasets and the URL's host. Keys live in the
secret store, are read here at call time, and are never returned or logged.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from . import collector, cribl


@dataclass(frozen=True)
class Destination:
    name: str
    url: str
    key: str = field(repr=False)  # never in a repr, a log line or a traceback
    vendor: str
    product: str
    # The primary's key is the `collectorKey` secret; every other destination's comes
    # from the `additionalKeys` secret. Only used to word an error.
    primary: bool = False
    # The Cribl source alias (a key of cribl.SOURCES) for a `cribl_<source>` destination, else None. Such a
    # destination's key is the criblToken secret and its dataset is fixed by the source's UUID.
    source: str | None = None

    @property
    def dataset(self) -> str:
        if self.source:
            return cribl.SOURCES[self.source].dataset
        return collector.dataset_name(self.vendor, self.product)

    @property
    def host(self) -> str:
        return urlparse(self.url).netloc


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def normalize(name: str) -> str:
    """The key a destination is addressed by: slug, with a trailing `_raw` (the dataset form) dropped."""
    s = slug(name)
    return s[: -len("_raw")] if s.endswith("_raw") else s


def _name(vendor: str, product: str) -> str:
    return collector.dataset_name(vendor, product).removesuffix("_raw")


def _json(text: str, expected: type, label: str, problems: list[str]) -> Any:
    if not (text or "").strip():
        return expected()
    try:
        value = json.loads(text)
    except ValueError as exc:
        # `exc` carries the position of the error, never the text, so a key cannot leak through it.
        problems.append(f"{label} is not valid JSON ({exc.__class__.__name__}: line {getattr(exc, 'lineno', '?')} column {getattr(exc, 'colno', '?')})")
        return expected()
    if not isinstance(value, expected):
        problems.append(f"{label} must be a JSON {'array' if expected is list else 'object'}")
        return expected()
    return value


def load(settings: dict[str, Any]) -> tuple[dict[str, Destination], list[str]]:
    """The destinations of this instance (primary first) and any problems found in its config.

    Problems never stop the primary destination from working; they are reported by
    `list_destinations` and in the error for a destination that could not be resolved.
    """
    problems: list[str] = []
    destinations: dict[str, Destination] = {}

    vendor, product = (settings.get("vendor") or "").strip(), (settings.get("product") or "").strip()
    if vendor and product:
        name = _name(vendor, product)
        destinations[name] = Destination(name, (settings.get("url") or "").strip(),
                                         (settings.get("key") or "").strip(), vendor, product, primary=True)
    else:
        problems.append("vendor and product are required: they name the primary destination")

    keys = {normalize(k): v for k, v in _json(settings.get("extra_keys", ""), dict, "additionalKeys", problems).items()
            if isinstance(k, str)}
    for index, entry in enumerate(_json(settings.get("extra", ""), list, "additionalDestinations", problems), start=1):
        if not isinstance(entry, dict) or not all(isinstance(entry.get(f), str) and entry.get(f, "").strip()
                                                  for f in ("url", "vendor", "product")):
            problems.append(f"additionalDestinations[{index}] needs string fields url, vendor and product")
            continue
        name = _name(entry["vendor"], entry["product"])
        if name in destinations:
            problems.append(f"additionalDestinations[{index}] repeats destination {name!r}")
            continue
        key = keys.get(name)
        destinations[name] = Destination(name, entry["url"].strip(), key.strip() if isinstance(key, str) else "",
                                         entry["vendor"].strip(), entry["product"].strip())
    for name in keys:
        if name not in destinations:
            problems.append(f"additionalKeys has a key for {name!r}, which is not a configured destination")

    cribl_url, cribl_token = (settings.get("cribl_url") or "").strip(), (settings.get("cribl_token") or "").strip()
    if cribl_url and cribl_token:
        integration_problem = cribl.check_integration(settings.get("cribl_integration") or cribl.DEFAULT_INTEGRATION)
        if integration_problem:
            problems.append(integration_problem + ": sends to the cribl_<source> destinations will fail")
        for alias, src in cribl.SOURCES.items():
            name = cribl.destination_name(alias)
            if name in destinations:
                problems.append(f"destination {name!r} is reserved for the Cribl source {alias!r} but is already configured")
                continue
            destinations[name] = Destination(name, cribl_url, cribl_token, "Cribl", src.label, source=alias)
    elif cribl_url:
        problems.append("criblUrl is set but the criblToken secret is empty: the cribl_<source> destinations are not registered")
    elif cribl_token:
        problems.append("the criblToken secret is set but criblUrl is empty: the cribl_<source> destinations are not registered")
    return destinations, problems


def resolve(destinations: dict[str, Destination], problems: list[str], wanted: str | None) -> tuple[Destination | None, str | None]:
    """The destination called `wanted` (default: the primary), or an error to return to the caller."""
    if not destinations:
        return None, "no destination is configured: " + "; ".join(problems or ["set collectorUrl, vendor and product"])
    if not wanted or not wanted.strip():
        return next(iter(destinations.values())), None
    dest = destinations.get(normalize(wanted))
    if dest is None:
        hint = f" ({'; '.join(problems)})" if problems else ""
        return None, f"unknown destination {wanted!r}; configured: {', '.join(destinations)}{hint}"
    return dest, None


def check(dest: Destination) -> str | None:
    """A problem that stops `dest` from being used, or None. Never mentions the key's value."""
    if dest.source:
        url_problem = cribl.check_url(dest.url)
        if url_problem:
            return f"destination {dest.name!r}: {url_problem}"
        if not dest.key:
            return f"destination {dest.name!r} has no token: set the criblToken secret"
        if not collector.valid_secret(dest.key):
            return f"destination {dest.name!r}: " + collector.SECRET_REFUSED.format(what="the criblToken secret")
        return None
    if not dest.url:
        return f"destination {dest.name!r} has no collector URL (https://api-<tenant>/logs/v1/event)"
    parsed = urlparse(dest.url)
    # The key travels in a header, so never send it in clear text.
    if parsed.scheme != "https" or not parsed.netloc:
        return f"destination {dest.name!r}: the collector URL must be an https:// URL"
    if not dest.key:
        slot = "the collectorKey secret" if dest.primary else "its entry in the additionalKeys secret"
        return f"destination {dest.name!r} has no key: set {slot}"
    if not collector.valid_secret(dest.key):
        slot = "the collectorKey secret" if dest.primary else "its entry in the additionalKeys secret"
        return f"destination {dest.name!r}: " + collector.SECRET_REFUSED.format(what=slot)
    return None

