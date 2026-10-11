"""Source remaining vendor logos from Wikipedia + vendor sites.

Maintainer-only research tool per scripts/CLAUDE.md. Runtime never
re-runs this. Idempotent: skips YAMLs that already have inline logos.

## Why

After the simple-icons pass (source_missing_vendor_svgs.py), these vendor
cards would still show the placeholder because the vendors aren't in
simple-icons:

  Arista, Avaya, Brocade, Clearswift, Ivanti, Kiteworks, RSA,
  SecureAuth, Semperis, Squid, Tigera

Of those, **8 have public SVG/PNG assets we can pull from
Wikipedia Commons, VectorLogoZone, or the vendor's own site**:

| Vendor       | Source                                                |
|--------------|-------------------------------------------------------|
| Arista       | Wikipedia: File:Arista-networks-logo.svg              |
| Avaya        | Wikipedia: File:Avaya_Logo.svg                        |
| Brocade      | Wikipedia: File:Brocade_Communications_Systems_logo.svg |
| Ivanti       | Wikipedia: File:Ivanti_Logo_RGB_red.svg               |
| Kiteworks    | Wikipedia: File:Kiteworks_logo.svg                    |
| RSA          | VectorLogoZone: /logos/rsa/rsa-icon.svg               |
| Squid        | Wikipedia: File:Squid_Now.png (PNG; only available format)|
| Tigera       | tigera.io: /app/uploads/2026/01/Tigera-logo-2026-black-text.svg |

The remaining 3 (Clearswift, SecureAuth, Semperis) couldn't be sourced
from public CDNs — Clearswift only has JPG on Wikidata, SecureAuth
has no Wiki article + no public press kit URL, Semperis uses an
inline-data-URI logo on their site. Operators can hand-curate these
by downloading from each vendor's official brand page and dropping
into the YAML.

## How

1. For each vendor, resolve the source URL (either direct or via the
   MediaWiki API for Wikipedia files).
2. Fetch bytes, decide mime_type from the URL suffix.
3. Base64-encode and inline-embed into the data_source.yaml's `logo:`
   block with provenance + license fields.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_SOURCES_DIR = REPO_ROOT / "bundles" / "spark" / "data-sources"

# ─── Source-URL table ──────────────────────────────────────────────────
#
# Each entry maps a YAML pack_name to a logo source descriptor. Three
# source kinds today:
#   * ("wikipedia", "File:<name>.svg") — resolve via MediaWiki API
#   * ("direct",    "https://…/logo.svg") — fetch directly
#   * ("direct-png","https://…/logo.png") — fetch directly, force PNG mime

PACK_TO_SOURCE: dict[str, tuple[str, str, str]] = {
    # (kind, locator, license_note)
    # ── Arista ─────────────────────────────────────────────────────────
    "AristaSwitch":               ("wikipedia", "File:Arista-networks-logo.svg",                   "Wikimedia Commons / vendor trademark"),
    # ── Avaya ──────────────────────────────────────────────────────────
    "Avaya":                       ("wikipedia", "File:Avaya_Logo.svg",                             "Wikimedia Commons / vendor trademark"),
    "AvayaAuraCommunicationManager": ("wikipedia", "File:Avaya_Logo.svg",                           "Wikimedia Commons / vendor trademark"),
    # ── Brocade ────────────────────────────────────────────────────────
    "BrocadeSwitch":               ("wikipedia", "File:Brocade_Communications_Systems_logo.svg",   "Wikimedia Commons / vendor trademark"),
    # ── Ivanti ─────────────────────────────────────────────────────────
    "IvantiConnectSecure":         ("wikipedia", "File:Ivanti_Logo_RGB_red.svg",                   "Wikimedia Commons CC BY-SA 4.0"),
    "IvantiPulseSecureVTM":        ("wikipedia", "File:Ivanti_Logo_RGB_red.svg",                   "Wikimedia Commons CC BY-SA 4.0"),
    # ── Kiteworks ──────────────────────────────────────────────────────
    "Kiteworks":                   ("wikipedia", "File:Kiteworks_logo.svg",                         "Wikimedia Commons CC BY-SA 3.0"),
    # ── RSA ────────────────────────────────────────────────────────────
    "RSASecureID":                 ("direct",    "https://www.vectorlogo.zone/logos/rsa/rsa-icon.svg", "VectorLogoZone / vendor trademark"),
    # ── Squid (PNG only — Wikipedia doesn't have SVG for this one) ─────
    "Squid":                       ("direct-png","https://upload.wikimedia.org/wikipedia/commons/0/0b/Squid_Now.png", "Wikimedia Commons / project logo"),
    # ── Tigera ─────────────────────────────────────────────────────────
    "TigeraCalico":                ("direct",    "https://www.tigera.io/app/uploads/2026/01/Tigera-logo-2026-black-text.svg", "tigera.io / vendor trademark"),
}


def resolve_wikipedia_url(file_title: str) -> str | None:
    """Use the MediaWiki API to get a direct upload.wikimedia.org URL."""
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": file_title,
        "prop": "imageinfo",
        "iiprop": "url",
        "format": "json",
    }
    query = "&".join(f"{k}={urllib.parse.quote(v)}" for k, v in params.items())
    url = f"{api}?{query}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "phantom-maintainer/0.17.31"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        print(f"  ⚠ MediaWiki API error: {exc}", file=sys.stderr)
        return None
    pages = data.get("query", {}).get("pages", {})
    for _page_id, info in pages.items():
        ii = info.get("imageinfo") or []
        if ii and ii[0].get("url"):
            return ii[0]["url"]
    return None


def fetch_bytes(url: str, max_retries: int = 4) -> bytes | None:
    """Fetch with retry-on-429. Wikipedia rate-limits anonymous bot UAs;
    a short backoff between requests typically clears it.
    """
    import time
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "phantom-maintainer/0.17.31 "
                        "(maintainer research tool; "
                        "https://github.com/ayman-m/phantom)"
                    ),
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s, 8s
                print(f"  ⏳ HTTP 429 — wait {wait}s + retry ({attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
            print(f"  ⚠ HTTP {e.code} fetching {url}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"  ⚠ Fetch error for {url}: {e}", file=sys.stderr)
            return None
    return None


def mime_for(url: str, kind: str) -> str:
    if kind == "direct-png":
        return "image/png"
    if url.lower().endswith(".svg"):
        return "image/svg+xml"
    if url.lower().endswith(".png"):
        return "image/png"
    return "image/svg+xml"  # default; most Wikipedia logos are svg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    yaml_dirs = sorted(d for d in DATA_SOURCES_DIR.iterdir() if d.is_dir())

    candidates: list[tuple[Path, str, tuple[str, str, str]]] = []
    skipped_has_logo = 0
    skipped_no_mapping: list[str] = []
    yaml_by_pack: dict[str, list[Path]] = {}

    for d in yaml_dirs:
        yaml_path = d / "data_source.yaml"
        if not yaml_path.is_file():
            continue
        try:
            doc = yaml.safe_load(yaml_path.read_text())
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        pack_name = doc.get("pack_name")
        if not pack_name:
            continue
        yaml_by_pack.setdefault(pack_name, []).append(yaml_path)
        if doc.get("logo"):
            skipped_has_logo += 1
            continue
        if pack_name not in PACK_TO_SOURCE:
            skipped_no_mapping.append(pack_name)
            continue
        candidates.append((yaml_path, pack_name, PACK_TO_SOURCE[pack_name]))

    print(f"=== Source summary ===")
    print(f"  YAMLs with existing inline logo (skipped): {skipped_has_logo}")
    print(f"  YAMLs with no mapping in PACK_TO_SOURCE: {len(skipped_no_mapping)}")
    print(f"  YAMLs to fetch: {len(candidates)}")
    print()

    # Dedupe by URL: multiple packs may share the same logo
    # source (e.g. Ivanti's two rule variants both want Ivanti_Logo).
    # Fetch each URL once, embed in all matching YAMLs.
    import time
    url_cache: dict[str, tuple[bytes, str]] = {}  # url → (bytes, mime)
    fetched = 0
    not_found = 0

    for yaml_path, pack_name, (kind, locator, license_note) in candidates:
        if kind == "wikipedia":
            url = resolve_wikipedia_url(locator)
            if url is None:
                print(f"  ✗ {pack_name:40s} {locator} → MediaWiki API miss")
                not_found += 1
                continue
        else:
            url = locator

        if url in url_cache:
            data, mime = url_cache[url]
        else:
            data = fetch_bytes(url)
            if data is None:
                print(f"  ✗ {pack_name:40s} {url} → fetch failed")
                not_found += 1
                continue
            mime = mime_for(url, kind)
            url_cache[url] = (data, mime)
            # Polite pacing: 0.5s between distinct URLs, helps Wikipedia
            # / CDNs not rate-limit the maintainer-bot UA.
            time.sleep(0.5)

        doc = yaml.safe_load(yaml_path.read_text())
        doc["logo"] = {
            "mime_type": mime,
            "data": base64.b64encode(data).decode("ascii"),
            "source": f"{kind}:{locator}",
            "license": license_note,
            "fidelity": "branded",
        }

        if not args.dry_run:
            with yaml_path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)

        print(f"  ✓ {pack_name:40s} {url} → {len(data):,} B {mime}")
        fetched += 1

    print()
    print(f"=== Results ===")
    print(f"  Newly inline-embedded: {fetched}")
    print(f"  Failed:                {not_found}")
    if args.dry_run:
        print("\n(dry-run; no files written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
