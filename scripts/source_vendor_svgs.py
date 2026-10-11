#!/usr/bin/env python3
"""Source theme-aware SVG variants for every vendor in vendor_map.yaml.

Pipeline per vendor (priority order):
  1. Online repos:
     - gilbarbara/logos        (https://raw.githubusercontent.com/gilbarbara/logos/main/logos/<slug>.svg)
     - SimpleIcons via jsDelivr (https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/<slug>.svg)
  2. demisto/content              (existing _dark.svg files we already have committed under Packs/<pack>/Integrations/<int>/<int>_dark.svg)
  3. Wordmark fallback            (rendered SVG: vendor name in primary color)

For each vendor we produce TWO files:
  bundles/spark/connectors/cortex-content/baked/vendor_svgs/<vendor>_light.svg   (brand color on light bg)
  bundles/spark/connectors/cortex-content/baked/vendor_svgs/<vendor>_dark.svg    (light/inverted on dark bg)

Maintainer-only — never invoked at runtime.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BAKED = ROOT / "bundles/spark/connectors/cortex-content/baked"
VENDOR_SVGS_DIR = BAKED / "vendor_svgs"
VENDOR_MAP_PATH = BAKED / "vendor_map.yaml"
LICENSES_PATH = BAKED / "LICENSES.md"

GILBARBARA_BASE = "https://raw.githubusercontent.com/gilbarbara/logos/main/logos"
SIMPLEICONS_BASE = "https://cdn.jsdelivr.net/npm/simple-icons@latest/icons"

# SHA-256 prefix of the generic-shield fallback. 26 packs ship this
# placeholder under <int>_dark.svg — we must not pick it as a "branded"
# demisto/content source. Vendors whose only existing _dark.svg matches this
# hash fall through to wordmark.
GENERIC_SHIELD_SHA256_PREFIX = "3d95768ef2e0"

# Vendor key → list of slugs to try for online lookup (first match wins per source)
EXPLICIT_SLUGS = {
    "microsoft": ["microsoft"],
    "cisco": ["cisco"],
    "aws": ["amazon-web-services", "aws"],
    "google": ["google"],
    "paloalto": ["palo-alto-networks", "paloalto"],
    "proofpoint": ["proofpoint"],
    "cyberark": ["cyberark"],
    "ibm": ["ibm"],
    "forcepoint": ["forcepoint"],
    "crowdstrike": ["crowdstrike"],
    "okta": ["okta"],
    "fortinet": ["fortinet", "fortigate"],
    "checkpoint": ["check-point", "checkpoint"],
    "symantec": ["symantec"],
    "mcafee": ["mcafee", "trellix"],
    "trendmicro": ["trend-micro", "trendmicro"],
    "splunk": ["splunk"],
    "cloudflare": ["cloudflare"],
    "sentinelone": ["sentinelone"],
    "darktrace": ["darktrace"],
    "tenable": ["tenable"],
    "qualys": ["qualys"],
    "rapid7": ["rapid7"],
    "zscaler": ["zscaler"],
    "barracuda": ["barracuda", "barracuda-networks"],
    "sophos": ["sophos"],
    "bitdefender": ["bitdefender"],
    "kaspersky": ["kaspersky"],
    "eset": ["eset"],
    "github": ["github"],
    "gitlab": ["gitlab"],
    "bitbucket": ["bitbucket"],
    "atlassian": ["atlassian"],
    "salesforce": ["salesforce"],
    "box": ["box"],
    "dropbox": ["dropbox"],
    "slack": ["slack"],
    "mongodb": ["mongodb"],
    "mysql": ["mysql"],
    "postgresql": ["postgresql"],
    "snowflake": ["snowflake"],
    "oracle": ["oracle"],
    "sap": ["sap"],
    "vmware": ["vmware"],
    "akamai": ["akamai"],
    "sumologic": ["sumologic", "sumo-logic"],
    "datadog": ["datadog"],
    "newrelic": ["new-relic", "newrelic"],
    "cylance": ["cylance"],
    "carbonblack": ["carbon-black", "vmware-carbon-black"],
    "extrahop": ["extrahop"],
    "duo": ["duo-security", "duo"],
    "pingidentity": ["ping-identity"],
    "jamf": ["jamf"],
    "sailpoint": ["sailpoint"],
    "wiz": ["wiz"],
    "orca": ["orca-security"],
    "lacework": ["lacework"],
    "illumio": ["illumio"],
    "arista": ["arista", "arista-networks"],
    "juniper": ["juniper", "juniper-networks"],
    "f5": ["f5"],
    "jumpcloud": ["jumpcloud"],
    "onelogin": ["onelogin"],
    "auth0": ["auth0"],
    "bitwarden": ["bitwarden"],
    "1password": ["1password"],
    "hashicorp": ["hashicorp"],
    "kubernetes": ["kubernetes"],
    "docker": ["docker"],
    "redis": ["redis"],
    "elastic": ["elastic"],
    "grafana": ["grafana"],
    "delinea": ["delinea"],
    "fireeye": ["fireeye"],
    "imperva": ["imperva"],
    "infoblox": ["infoblox"],
    "manageengine": ["manageengine"],
    "hpe": ["hpe", "hewlett-packard-enterprise"],
    "alibaba": ["alibaba", "alibaba-cloud"],
    "mimecast": ["mimecast"],
    "netskope": ["netskope"],
    "nvidia": ["nvidia"],
    "huawei": ["huawei"],
    "forescout": ["forescout"],
    "ubiquiti": ["ubiquiti"],
    "servicenow": ["servicenow"],
    "workday": ["workday"],
    "zoom": ["zoom"],
    "docusign": ["docusign"],
    "shodan": ["shodan"],
    "recordedfuture": ["recorded-future", "recordedfuture"],
    "vectra": ["vectra-ai", "vectra"],
    "exabeam": ["exabeam"],
    "abnormalsecurity": ["abnormal-security"],
    "teamviewer": ["teamviewer"],
    "linuxeventscollection": ["linux"],
}


def fetch_url(url: str, timeout: int = 10) -> bytes | None:
    """GET url, return body bytes or None on failure (404/timeout/etc.)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "phantom-svg-sourcer/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status == 200:
                return r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        pass
    return None


def is_valid_svg(content: bytes) -> bool:
    """Light validation that content is actually SVG."""
    if not content or len(content) < 50:
        return False
    head = content[:1024].decode("utf-8", errors="ignore").lower()
    return "<svg" in head and ("</svg>" in content[-1024:].decode("utf-8", errors="ignore").lower() or len(content) < 1024)


def try_gilbarbara(slug: str) -> bytes | None:
    return fetch_url(f"{GILBARBARA_BASE}/{slug}.svg")


def try_simpleicons(slug: str) -> bytes | None:
    return fetch_url(f"{SIMPLEICONS_BASE}/{slug}.svg")


def find_existing_dark_svg(vendor_packs: list[str]) -> bytes | None:
    """Reuse a demisto-published _dark.svg from one of the vendor's existing packs.

    Skips the generic-shield fallback (26 packs ship it as a placeholder).
    """
    import hashlib
    for pack_id in vendor_packs:
        pack_dir = BAKED / "Packs" / pack_id
        if not pack_dir.is_dir():
            continue
        int_dir = pack_dir / "Integrations"
        if not int_dir.is_dir():
            continue
        for child in int_dir.iterdir():
            if not child.is_dir():
                continue
            svg = child / f"{child.name}_dark.svg"
            if svg.is_file():
                content = svg.read_bytes()
                h = hashlib.sha256(content).hexdigest()[:12]
                if h == GENERIC_SHIELD_SHA256_PREFIX:
                    continue  # skip generic-shield placeholder
                return content
    return None


def find_existing_png_dimensions(vendor_packs: list[str]) -> tuple[int, int] | None:
    """Sample existing PNG dimensions to size wordmark fallback proportionately."""
    # Most demisto PNGs are 312x100 or similar; default 312x100 = 3.12:1 aspect ratio
    return (312, 100)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


def _luminance(hex_color: str) -> float:
    """Perceptual luminance approximation (0..255 scale)."""
    r, g, b = _hex_to_rgb(hex_color)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance (0..1 scale, sRGB-linearized).

    Used for WCAG 2.1 contrast ratio calculation.
    """
    def channel(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb(hex_color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.1 contrast ratio between two hex colors (1.0..21.0)."""
    l1 = _relative_luminance(fg)
    l2 = _relative_luminance(bg)
    lighter, darker = (l1, l2) if l1 > l2 else (l2, l1)
    return (lighter + 0.05) / (darker + 0.05)


def _darken(hex_color: str, amount: float = 0.4) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex(int(r * (1 - amount)), int(g * (1 - amount)), int(b * (1 - amount)))


def _lighten(hex_color: str, amount: float = 0.3) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex(
        int(r + (255 - r) * amount),
        int(g + (255 - g) * amount),
        int(b + (255 - b) * amount),
    )


# Wordmark fills MUST meet WCAG AA contrast (4.5:1) against the
# constant near-white panel (#F7F8FA). Brand colors that fail (Symantec
# yellow, Proofpoint light-blue, Nvidia mid-green, Portnox cyan) get
# iteratively darkened until they pass. Conservative cap at 10% luminance
# (very dark gray-ish) so we never collapse to pure black on edge cases.
NEAR_WHITE_PANEL = "#F7F8FA"
WCAG_AA_CONTRAST = 4.5
MIN_LUM_FRACTION = 0.10  # don't darken below 10% of original brightness


def ensure_wcag_contrast(brand_color: str, bg: str = NEAR_WHITE_PANEL, target: float = WCAG_AA_CONTRAST) -> str:
    """Iteratively darken `brand_color` until its WCAG contrast vs `bg` ≥ target.

    Returns the original color if it already passes. For colors that won't darken
    enough (extremely saturated yellows/cyans), the loop terminates at the MIN_LUM
    threshold and accepts whatever contrast that yields — typically still better
    than the original.
    """
    if _contrast_ratio(brand_color, bg) >= target:
        return brand_color

    r0, g0, b0 = _hex_to_rgb(brand_color)
    # Linearly scale the channels toward 0 until contrast meets target OR we hit min
    for step in range(1, 20):  # up to 19 darken steps in 5%-per-step increments
        factor = 1 - 0.05 * step
        if factor < MIN_LUM_FRACTION:
            factor = MIN_LUM_FRACTION
        candidate = _rgb_to_hex(int(r0 * factor), int(g0 * factor), int(b0 * factor))
        if _contrast_ratio(candidate, bg) >= target:
            return candidate
        if factor == MIN_LUM_FRACTION:
            return candidate  # hit floor, accept best-effort
    return brand_color  # unreachable


def render_wordmark_svg(display_name: str, primary_color: str, theme: str) -> bytes:
    """Render a theme-aware wordmark SVG.

    For the LIGHT variant (the only one the UI now serves against
    the constant #F7F8FA near-white panel), enforce WCAG AA contrast (4.5:1)
    by darkening the brand color iteratively until it passes. This keeps
    wordmarks for brands with bright/saturated
    colors (Symantec yellow, Proofpoint light-blue, Nvidia green, Portnox
    cyan, etc.) that fell below the AA threshold.

    For the DARK variant (kept for backwards compat but no longer used by
    the UI), unchanged behavior: white text for dark brands, lightened
    brand for bright brands.
    """
    if theme == "light":
        # Enforce WCAG AA contrast (4.5:1) against the near-white panel.
        # Darken iteratively until brand color passes the threshold.
        fill = ensure_wcag_contrast(primary_color, bg=NEAR_WHITE_PANEL, target=WCAG_AA_CONTRAST)
    else:
        # Dark theme variant — preserved for backwards compat with any
        # caller that still requests ?theme=dark. UI no longer fetches this.
        lum = _luminance(primary_color)
        if lum < 80:
            fill = "#FFFFFF"
        else:
            fill = _lighten(primary_color, 0.2)

    # Estimate text width: roughly 18px per character at 30px font
    text = display_name
    char_count = max(len(text), 6)
    estimated_width = max(160, char_count * 18)
    # ViewBox so the wordmark scales with the container
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {estimated_width} 60" '
        f'preserveAspectRatio="xMidYMid meet">'
        f'<text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" '
        f'font-family="Inter, -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif" '
        f'font-size="32" font-weight="600" fill="{fill}">{text}</text>'
        f'</svg>'
    ).encode("utf-8")


def main() -> int:
    if not VENDOR_MAP_PATH.is_file():
        print(f"ERROR: vendor_map.yaml not found at {VENDOR_MAP_PATH}", file=sys.stderr)
        return 1

    data = yaml.safe_load(VENDOR_MAP_PATH.read_text())
    vendors = data.get("vendors", {})
    if not vendors:
        print("ERROR: no vendors in vendor_map.yaml", file=sys.stderr)
        return 1

    VENDOR_SVGS_DIR.mkdir(parents=True, exist_ok=True)

    stats = {
        "gilbarbara": 0,
        "simpleicons": 0,
        "demisto_dark": 0,
        "wordmark_fallback": 0,
        "total_vendors": len(vendors),
    }
    license_entries: list[tuple[str, str, str, str]] = []  # (vendor, source, url, license)

    for vk in sorted(vendors.keys()):
        info = vendors[vk]
        display = info["display_name"]
        color = info.get("primary_color", "#5F6368")
        packs = info.get("packs", [])

        slugs = EXPLICIT_SLUGS.get(vk, [vk])
        light_content: bytes | None = None
        dark_content: bytes | None = None
        light_source = "none"
        dark_source = "none"
        light_license = ""
        dark_license = ""

        # 1. Try online sources for LIGHT variant
        for slug in slugs:
            content = try_gilbarbara(slug)
            if content and is_valid_svg(content):
                light_content = content
                light_source = "gilbarbara/logos"
                light_license = "MIT (gilbarbara/logos)"
                license_entries.append((vk, "gilbarbara/logos", f"{GILBARBARA_BASE}/{slug}.svg", "MIT"))
                stats["gilbarbara"] += 1
                break

        if light_content is None:
            for slug in slugs:
                content = try_simpleicons(slug)
                if content and is_valid_svg(content):
                    light_content = content
                    light_source = "simpleicons"
                    light_license = "CC0 (SimpleIcons)"
                    license_entries.append((vk, "simpleicons", f"{SIMPLEICONS_BASE}/{slug}.svg", "CC0"))
                    stats["simpleicons"] += 1
                    break

        # 2. For DARK: prefer existing demisto _dark.svg
        existing_dark = find_existing_dark_svg(packs)
        if existing_dark:
            dark_content = existing_dark
            dark_source = "demisto/content"
            dark_license = "MIT (demisto/content)"
            license_entries.append((vk, "demisto/content", f"Packs/{packs[0]}/...", "MIT"))
            stats["demisto_dark"] += 1
        else:
            # 3. Wordmark fallback for dark
            dark_content = render_wordmark_svg(display, color, "dark")
            dark_source = "wordmark-fallback"
            dark_license = "internal"
            stats["wordmark_fallback"] += 1

        # If no light SVG found online, fallback to wordmark
        if light_content is None:
            light_content = render_wordmark_svg(display, color, "light")
            light_source = "wordmark-fallback"
            light_license = "internal"
            stats["wordmark_fallback"] += 1

        # Write
        light_path = VENDOR_SVGS_DIR / f"{vk}_light.svg"
        dark_path = VENDOR_SVGS_DIR / f"{vk}_dark.svg"
        light_path.write_bytes(light_content)
        dark_path.write_bytes(dark_content)

        # Update vendor_map.yaml in-memory with sources + fidelity
        info["sources"] = {"light": light_source, "dark": dark_source}
        info["fidelity"] = "branded" if light_source not in ("wordmark-fallback", "none") else "wordmark"

        print(f"  {vk:30s}  light={light_source:25s}  dark={dark_source}")

    # Write back vendor_map.yaml
    VENDOR_MAP_PATH.write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=False, width=120))

    # Write LICENSES.md
    license_lines = [
        "# Vendor SVG Logo Sources + Licenses",
        "",
        "Per-vendor SVG provenance for the cortex-content catalog.",
        "",
        "All non-wordmark-fallback SVGs are sourced under MIT or CC0 / public-domain licenses.",
        "Wordmark fallbacks are internal renderings (text in vendor's brand color on transparent bg).",
        "",
        "| Vendor | Source | URL | License |",
        "|---|---|---|---|",
    ]
    for vk, source, url, lic in license_entries:
        license_lines.append(f"| {vk} | {source} | {url} | {lic} |")
    LICENSES_PATH.write_text("\n".join(license_lines) + "\n")

    print()
    print("=== sourcing summary ===")
    for k, v in stats.items():
        print(f"  {k:25s}  {v}")
    print()
    print(f"vendor_map.yaml updated: {VENDOR_MAP_PATH}")
    print(f"LICENSES.md written:     {LICENSES_PATH}")
    print(f"SVGs in vendor_svgs/:    {sum(1 for _ in VENDOR_SVGS_DIR.glob('*.svg'))}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
