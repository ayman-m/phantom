"""Fetch vendor logos for cortex-content baked-catalog packs that lack them.

Some baked packs ship without any vendor logo. They're XSIAM modeling-rule-only
packs (no Integrations/ dir in demisto/content), so demisto/content has zero
logos for them. Packs that DO have logos get them from demisto/content's
Integrations/<int>/*_dark.svg files during the bake. The missing-logo packs
need an external source.

This script:
  1. Enumerates packs in `bundles/spark/connectors/cortex-content/baked/Packs/`
  2. Finds the ones with no existing logo (no SVG, no PNG, no Author_image)
  3. Resolves each to a vendor slug via the curated VENDOR_SLUG_MAP below
  4. Fetches an SVG from SimpleIcons CDN (CC0-licensed brand icons)
  5. Falls back to EXPLICIT_FALLBACKS for vendors not in SimpleIcons
  6. Saves the SVG to the standard logo-route discovery path:
     `Packs/<pack>/Integrations/<pack>/<pack>_dark.svg`
  7. Reports per-pack outcome (success, fallback, or unresolved)

Source license: SimpleIcons icons are released under CC0 1.0 (public domain),
explicitly safe for any use including commercial. Wikipedia Commons SVGs vary
per upload — the explicit fallbacks below are limited to CC0 or PD entries.

The SVGs are rendered as `currentColor` so they adapt to whatever surrounding
text color the data-sources UI uses (works in both light + dark themes via
the Material 3 token surface).

Maintainer-only — never invoked at runtime. Run via:

    python3 scripts/fetch_vendor_logos.py

Idempotent — re-running skips packs that already have logos. To force-refresh
a specific pack, delete its `Integrations/<pack>/<pack>_dark.svg` first.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BAKED_DIR = REPO_ROOT / "bundles/spark/connectors/cortex-content/baked/Packs"

# SimpleIcons CDN — https://simpleicons.org — CC0 1.0 licensed.
# Endpoint returns a clean monochrome SVG (black on transparent) sized 24x24.
# We append `?viewbox=auto` for consistent sizing.
SIMPLEICONS_URL = "https://cdn.simpleicons.org/{slug}"

# Map each missing pack to a SimpleIcons slug. Set to None for packs where
# SimpleIcons doesn't have the brand — those fall through to EXPLICIT_FALLBACKS.
# Slugs are documented at https://simpleicons.org/?q=<brand>
VENDOR_SLUG_MAP: dict[str, str | None] = {
    # Microsoft family
    "AzureAppService": "microsoftazure",
    "AzureFlowLogs": "microsoftazure",
    "MicrosoftADFS": "microsoft",
    "MicrosoftDHCP": "microsoft",
    "MicrosoftDNS": "microsoft",
    "MicrosoftDefenderforIdentity": "microsoft",
    "MicrosoftEntraID": "microsoftentra",
    "MicrosoftExchangeServer": "microsoft",
    "MicrosoftIISWebServer": "microsoft",
    "MicrosoftIntune": "microsoft",
    "MicrosoftWindowsAMSI": "windows",
    "MicrosoftWindowsEvents": "windows",
    "MicrosoftWindowsSysmon": "microsoft",
    "Office365": "microsoftoffice",
    # Other major vendors covered by SimpleIcons
    "CiscoCatalyst": "cisco",
    "CommvaultBackupSolutions": None,  # Commvault not in SimpleIcons today
    "CyberArkEPV": None,
    "CyberArk_Privileged_Threat_Analytics": None,
    "F5ASM": "f5",
    "GoogleChrome": "googlechrome",
    "HuaweiFW": "huawei",
    "IBMDirectoryServer": "ibm",
    "LinuxEventsCollection": "linux",
    "McAfeeDatabaseSecurity": "mcafee",
    "NVIDIA_DOCA_Argus": "nvidia",
    "Oracle": "oracle",
    "SymantecBlueCoatProxySG": "symantec",
    "TrendMicroTippingPoint": "trendmicro",
    "UbiquitiUnifi": "ubiquiti",
    "VMWareNSX": "vmware",
    "VMwareESXi": "vmware",
    "VMwareVCenter": "vmware",
    "ZscalerZPA": "zscaler",
    # Niche vendors — try SimpleIcons but expect fallback
    "Barracuda_Cloudgen_Firewall": None,
    "CorelightZeek": None,
    "DelineaALM": None,
    "Dragos_Platform": None,
    "ForcepointEmailSecurity": None,
    "ForcepointSWG": None,
    "ForeScoutCounterACT": None,
    "LenelS2NetBox": None,
    "ManageEngine-ADAudit": None,
    "ManageEngine-ADSelfServicePlus": None,
    "NasuniFileServices": None,
    "NetmotionVPN": None,
    "Portnox": None,
    "ProofpointCasb": None,
    "ProofpointObserveIT": None,
    "ReblazeWAF": None,
    "SynopsysCoverity": "synopsys",
    "Trellix_ePO": None,
    "WatchguardFirebox": None,
}

# Explicit fallback URLs for vendors not in SimpleIcons but with well-known
# brand SVGs on Wikipedia Commons. Wikipedia Commons SVGs vary in license;
# the entries below are limited to logos that the Commons {{trademark}}-only
# template applies to — i.e. trademark protected but NOT copyrighted (logos
# below the US "originality threshold"). Safe for fair-use display.
EXPLICIT_FALLBACK_URLS: dict[str, str] = {
    # Microsoft family — Microsoft's 4-square logo (2012-present)
    "microsoft-logo": "https://upload.wikimedia.org/wikipedia/commons/9/96/Microsoft_logo_%282012%29.svg",
    "microsoft-azure": "https://upload.wikimedia.org/wikipedia/commons/f/fa/Microsoft_Azure.svg",
    "microsoft-office": "https://upload.wikimedia.org/wikipedia/commons/5/5f/Microsoft_Office_logo_%282019%E2%80%93present%29.svg",
    "windows-11": "https://upload.wikimedia.org/wikipedia/commons/d/d6/Windows_11_logo_%28multicolor%29.svg",
    # Other enterprise vendors not in SimpleIcons
    "oracle-logo": "https://upload.wikimedia.org/wikipedia/commons/5/50/Oracle_logo.svg",
    "ibm-logo": "https://upload.wikimedia.org/wikipedia/commons/5/51/IBM_logo.svg",
    "proofpoint-logo": "https://upload.wikimedia.org/wikipedia/commons/f/f3/Proofpoint_R_Logo.png",
    "cyberark-logo": "https://upload.wikimedia.org/wikipedia/commons/8/82/CyberArk_Logo.svg",
    "zscaler-logo": "https://upload.wikimedia.org/wikipedia/commons/c/c4/Zscaler_logo.svg",
    "trellix-logo": "https://upload.wikimedia.org/wikipedia/commons/9/9a/Trellix_logo.svg",
}

# Maps each pack to a fallback URL key from EXPLICIT_FALLBACK_URLS. Use when
# the SimpleIcons slug in VENDOR_SLUG_MAP returned 404. Same pack-name keys
# as VENDOR_SLUG_MAP.
FALLBACK_KEY_MAP: dict[str, str] = {
    # Microsoft family — all share the Microsoft 4-square logo
    "AzureAppService": "microsoft-azure",
    "AzureFlowLogs": "microsoft-azure",
    "MicrosoftADFS": "microsoft-logo",
    "MicrosoftDHCP": "microsoft-logo",
    "MicrosoftDNS": "microsoft-logo",
    "MicrosoftDefenderforIdentity": "microsoft-logo",
    "MicrosoftEntraID": "microsoft-logo",
    "MicrosoftExchangeServer": "microsoft-logo",
    "MicrosoftIISWebServer": "microsoft-logo",
    "MicrosoftIntune": "microsoft-logo",
    "MicrosoftWindowsAMSI": "windows-11",
    "MicrosoftWindowsEvents": "windows-11",
    "MicrosoftWindowsSysmon": "microsoft-logo",
    "Office365": "microsoft-office",
    # Other enterprise vendors covered by Wikipedia entries
    "Oracle": "oracle-logo",
    "IBMDirectoryServer": "ibm-logo",
    "ProofpointCasb": "proofpoint-logo",
    "ProofpointObserveIT": "proofpoint-logo",
    "CyberArkEPV": "cyberark-logo",
    "CyberArk_Privileged_Threat_Analytics": "cyberark-logo",
    "ZscalerZPA": "zscaler-logo",
    "Trellix_ePO": "trellix-logo",
}

# Material Symbols-style fallback SVG (currentColor) for packs we can't resolve
# to a vendor logo. Better than a missing image — at least communicates "data
# source" instead of showing a broken image icon. The shield+database glyph
# below is Material Symbols' "security_update" path.
GENERIC_VENDOR_FALLBACK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-1 6h2v2h-2V7zm0 4h2v6h-2v-6z"/></svg>"""


# ───────────────────────────────────────────────────────────────────────────


@dataclass
class FetchResult:
    pack: str
    outcome: str  # "ok-simpleicons" | "ok-generic-fallback" | "skipped" | "error"
    bytes: int
    detail: str


def _ua_request(url: str, timeout: float = 10.0) -> bytes:
    """Fetch a URL with a polite user agent + timeout. Raises on HTTP errors."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "phantom-fetch-vendor-logos/0.1 (+https://github.com/ayman-m/phantom)",
            "Accept": "image/svg+xml,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _validate_svg(content: bytes) -> bool:
    """A safety net so we never write garbage to the catalog. Confirms the
    bytes are: (a) reasonable size — between 100 bytes and 200 KB; (b) parse
    as XML; (c) have an <svg> root element."""
    if len(content) < 100 or len(content) > 200_000:
        return False
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return False
    tag = root.tag.lower()
    return tag == "svg" or tag.endswith("}svg")


def _enumerate_missing(baked_dir: Path) -> list[str]:
    """Pack names that have no SVG/PNG/Author_image anywhere."""
    missing: list[str] = []
    for pack_dir in sorted(baked_dir.iterdir()):
        if not pack_dir.is_dir():
            continue
        # Any image at any depth under Integrations/
        int_dir = pack_dir / "Integrations"
        has_image = False
        if int_dir.exists():
            for image_path in int_dir.glob("*/*"):
                if image_path.suffix.lower() in (".svg", ".png"):
                    has_image = True
                    break
        if not has_image and not (pack_dir / "Author_image.png").is_file():
            missing.append(pack_dir.name)
    return missing


def _logo_path(pack: str) -> Path:
    """The standard discovery path the data-sources logo route walks."""
    return (
        BAKED_DIR / pack / "Integrations" / pack / f"{pack}_dark.svg"
    )


def _save_svg(pack: str, content: bytes) -> Path:
    out = _logo_path(pack)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)
    return out


def _try_simpleicons(slug: str) -> bytes | None:
    """Returns SVG bytes on success, None on 404 (slug not in SimpleIcons)."""
    url = SIMPLEICONS_URL.format(slug=slug)
    try:
        content = _ua_request(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if not _validate_svg(content):
        return None
    return content


def _try_explicit_fallback(pack: str) -> tuple[bytes, str] | None:
    """For packs that don't have a SimpleIcons slug or got 404 from one, try
    a curated Wikipedia Commons URL. Returns (bytes, fallback_key) on success.
    """
    key = FALLBACK_KEY_MAP.get(pack)
    if not key:
        return None
    url = EXPLICIT_FALLBACK_URLS.get(key)
    if not url:
        return None
    try:
        content = _ua_request(url, timeout=15.0)
    except urllib.error.HTTPError:
        return None
    except Exception:  # network blip, redirect issue, etc
        return None
    # Accept SVG OR PNG (Wikipedia has both). PNG entries store as
    # `<pack>_image.png` — the route discovers them with the same priority.
    is_svg = _validate_svg(content)
    is_png = content[:8] == b"\x89PNG\r\n\x1a\n"
    if not (is_svg or is_png):
        return None
    if is_png and len(content) > 200_000:
        # Cap PNG size — Wikipedia originals can be 1MB+; we want icons not
        # marketing images.
        return None
    return content, key


def _apply_currentcolor(svg_bytes: bytes) -> bytes:
    """Rewrite explicit fill colors to `currentColor` so the icon adapts to
    the surrounding text color in light + dark themes. SimpleIcons returns
    black fills by default; we normalize them.
    """
    text = svg_bytes.decode("utf-8", errors="replace")
    # The SimpleIcons SVGs use fill="#000000" or fill="black" on the inner
    # path. Replace those with currentColor; leave any other colors alone.
    for needle in ('fill="#000000"', 'fill="#000"', 'fill="black"'):
        text = text.replace(needle, 'fill="currentColor"')
    # If no fill attribute exists on the <svg> root, inject one so the icon
    # actually picks up the surrounding color.
    if "fill=" not in text.split(">", 1)[0]:
        text = text.replace("<svg ", '<svg fill="currentColor" ', 1)
    return text.encode("utf-8")


def _save_png(pack: str, content: bytes) -> Path:
    """For Wikipedia PNG fallbacks. The data-sources logo route discovers
    both `<pack>_dark.svg` and `<pack>_image.png` in priority order."""
    out = (
        BAKED_DIR / pack / "Integrations" / pack / f"{pack}_image.png"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)
    return out


def fetch_all(packs: list[str], force: bool = False) -> list[FetchResult]:
    """Fetch a logo for each pack. Returns the per-pack outcome record.

    Args:
      packs: pack names to fetch logos for.
      force: when True, overwrite existing logos. Default False — re-runs
        skip packs that already have a logo file, so the script is safe to
        invoke repeatedly.
    """
    results: list[FetchResult] = []
    for i, pack in enumerate(packs, 1):
        slug = VENDOR_SLUG_MAP.get(pack)
        progress = f"[{i:2d}/{len(packs)}] {pack:42s}"

        # Idempotence: if we already wrote a logo, skip unless --force.
        if _logo_path(pack).is_file() and not force:
            print(f"{progress} → already-has-logo (skipping)")
            results.append(FetchResult(pack, "skipped", 0, "already exists"))
            continue

        # Tier 1: SimpleIcons — clean monochrome SVGs, CC0 1.0 license.
        if slug:
            try:
                content = _try_simpleicons(slug)
            except Exception as exc:  # network blip
                content = None
                print(f"{progress} → SimpleIcons error: {exc}")
            if content:
                normalized = _apply_currentcolor(content)
                out = _save_svg(pack, normalized)
                print(
                    f"{progress} → simpleicons/{slug} "
                    f"({len(normalized)} bytes → {out.relative_to(REPO_ROOT)})"
                )
                results.append(
                    FetchResult(pack, "ok-simpleicons", len(normalized), slug)
                )
                time.sleep(0.1)  # be polite to SimpleIcons CDN
                continue

        # Tier 2: explicit Wikipedia Commons fallback for high-value brands
        # not in SimpleIcons (Microsoft family, Oracle, IBM, etc).
        explicit = _try_explicit_fallback(pack)
        if explicit is not None:
            content, fallback_key = explicit
            is_svg = content[:5] != b"\x89PNG\r"
            if is_svg:
                out = _save_svg(pack, content)
            else:
                out = _save_png(pack, content)
            print(
                f"{progress} → wikipedia/{fallback_key} "
                f"({len(content)} bytes → {out.relative_to(REPO_ROOT)})"
            )
            results.append(
                FetchResult(pack, "ok-wikipedia", len(content), fallback_key)
            )
            time.sleep(0.2)  # be polite to Wikipedia
            continue

        # Tier 3: generic shield icon. Always succeeds — at least no broken
        # image. Operator can override later by dropping a real logo file
        # at the same path.
        out = _save_svg(pack, GENERIC_VENDOR_FALLBACK_SVG.encode())
        print(
            f"{progress} → generic-fallback "
            f"({len(GENERIC_VENDOR_FALLBACK_SVG)} bytes → {out.relative_to(REPO_ROOT)})"
        )
        results.append(
            FetchResult(
                pack,
                "ok-generic-fallback",
                len(GENERIC_VENDOR_FALLBACK_SVG),
                "no simpleicons slug + no wikipedia fallback; generic shield icon",
            )
        )
    return results


def main() -> int:
    if not BAKED_DIR.is_dir():
        print(f"ERROR: baked dir not found at {BAKED_DIR}", file=sys.stderr)
        return 1

    force = "--force" in sys.argv
    # IMPORTANT: only iterate packs that actually exist in the baked tree.
    # Otherwise a typo in VENDOR_SLUG_MAP or FALLBACK_KEY_MAP would create a
    # phantom directory under Packs/ with no real schema content — a junk
    # entry the next bake would carry forward forever.
    on_disk = {p.name for p in BAKED_DIR.iterdir() if p.is_dir()}
    if force:
        candidates = sorted(
            (set(VENDOR_SLUG_MAP) | set(FALLBACK_KEY_MAP)) & on_disk
        )
        print(f"=== --force mode: refreshing {len(candidates)} pack(s) ===")
        missing = candidates
    else:
        missing = _enumerate_missing(BAKED_DIR)
        print(f"=== Found {len(missing)} pack(s) missing logos ===")
    print()

    results = fetch_all(missing, force=force)

    print()
    print("=== Summary ===")
    by_outcome: dict[str, int] = {}
    for r in results:
        by_outcome[r.outcome] = by_outcome.get(r.outcome, 0) + 1
    for outcome in sorted(by_outcome):
        print(f"  {outcome:30s}  {by_outcome[outcome]:3d}")

    # Final audit — how many packs still have no logo?
    still_missing = _enumerate_missing(BAKED_DIR)
    print()
    print(f"=== Post-fetch coverage ===")
    print(f"  Still-missing: {len(still_missing)}")
    if still_missing:
        for p in still_missing[:10]:
            print(f"    - {p}")
        if len(still_missing) > 10:
            print(f"    ... and {len(still_missing) - 10} more")
    else:
        print("  All packs now have logos. ✓")

    return 0


if __name__ == "__main__":
    sys.exit(main())
