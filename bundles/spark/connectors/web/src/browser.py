"""Headless-browser tool implementations for the `web` connector.

Talks to a remote Chromium over CDP (defaults to the
`phantom-browser` sidecar in docker-compose). Playwright Python
handles the protocol; the sidecar provides the actual Chromium
binary, keeping browser-binary weight (~250MB) out of the
phantom-agent image.

# Lifecycle model

- One `Playwright` + one `Browser` per process, lazy-initialized on
  the first tool call. Cached in module globals.
- Each agent-supplied `session_id` maps to one isolated `BrowserContext`
  + one `Page` inside it. Different session_ids = different cookie
  jars, localStorage, etc. The agent picks session_ids; convention is
  to reuse the chat session id for stateful flows ("login then
  navigate to authed page"), or use ephemeral ids for one-shot fetches.
- Sessions are GC'd lazily: every tool call scans the registry and
  closes any session idle > `_SESSION_IDLE_TTL` (10 min default). This
  prevents a forgotten session from pinning a tab forever, without
  needing a background task.

# Why connect_over_cdp instead of launching Chromium in-process

The phantom-agent container ships only the Playwright Python *library*
(no browser binaries). Spawning Chromium in-process would require
`playwright install chromium` at image build time (+250MB) and the
shared libraries needed by Chromium (libnss3, fontconfig, etc.).
Connecting to a remote CDP endpoint sidesteps both — the sidecar is
chromedp/headless-shell (~150MB), already bundled with Chromium and
its system deps. The connector just speaks JSON-over-WebSocket.

# What about errors?

Every tool catches its own exceptions and returns `{"error": "..."}`
rather than raising — keeps the FastMCP wrapper from converting them
into protocol-level failures the agent can't reason about. The error
strings are operator-friendly (no stack traces) and include enough
context to file a useful bug or check the sidecar's health.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("Phantom MCP.web")

# ─── Imports that may fail at import time ────────────────────────────
# Playwright is REQUIRED — the connector is useless without it. If
# the import fails, every tool call returns a clear error rather than
# raising on import (which would block the entire MCP from booting).
_PLAYWRIGHT_IMPORT_ERROR: Exception | None = None
try:
    from playwright.async_api import (
        Browser,
        BrowserContext,
        Page,
        Playwright,
        async_playwright,
    )
except Exception as exc:  # noqa: BLE001
    _PLAYWRIGHT_IMPORT_ERROR = exc
    Browser = BrowserContext = Page = Playwright = Any  # type: ignore[assignment, misc]
    async_playwright = None  # type: ignore[assignment]

# Trafilatura is OPTIONAL — only `get_text(mode='readable')` and
# `mode='markdown')` need it. `mode='body'` works without it. Soft-fail
# on import so a deploy that didn't install trafilatura can still use
# the connector for body-mode extraction and screenshots.
_TRAFILATURA_IMPORT_ERROR: Exception | None = None
try:
    import trafilatura
except Exception as exc:  # noqa: BLE001
    _TRAFILATURA_IMPORT_ERROR = exc
    trafilatura = None  # type: ignore[assignment]


# ─── Module-level state ──────────────────────────────────────────────

# Default values for instance config keys — used when get_config()
# can't find the attribute (instance has no override AND Settings has
# no fallback). Keep in sync with bundles/spark/connectors/web/connector.yaml
# configSchema defaults.
_DEFAULT_CDP_URL = "http://phantom-browser:9222"
_DEFAULT_TIMEOUT_MS = 30_000
_DEFAULT_EXTRACTOR_MODE = "readable"

# Idle session TTL. The agent rarely needs a page open for >10 min;
# anything older is almost certainly forgotten. Cheap to recreate.
_SESSION_IDLE_TTL = 600.0  # seconds

# Cap on returned text/HTML/links so a single tool call can't blow
# past the LLM's input budget. Caller can lower further per-call via
# the `max_chars` arg; these are the absolute upper bounds.
_TEXT_MAX_CHARS_DEFAULT = 50_000
_HTML_MAX_CHARS_DEFAULT = 200_000
_LINKS_MAX_DEFAULT = 200


class _Session:
    """One agent-facing session = one BrowserContext + one Page.

    Tracks last-used time so the lazy GC can evict idle ones.
    """

    __slots__ = ("session_id", "context", "page", "opened_at", "last_used_at")

    def __init__(self, session_id: str, context: BrowserContext, page: Page) -> None:
        self.session_id = session_id
        self.context = context
        self.page = page
        now = time.monotonic()
        self.opened_at = now
        self.last_used_at = now

    def touch(self) -> None:
        self.last_used_at = time.monotonic()


# Module globals — lazy-initialized.
_playwright: Playwright | None = None
_browser: Browser | None = None
_sessions: dict[str, _Session] = {}
# Single lock guards both the connection init AND registry mutations.
# The async wait points inside the connector (page.goto, page.click)
# release the lock — only the bookkeeping (registry insert/evict,
# connect_over_cdp call) holds it. Fine-grained per-session locks
# would be marginally faster but the contention is low (the agent is
# inherently sequential per chat turn).
_lock = asyncio.Lock()


def _instance_config() -> dict[str, Any]:
    """Read this instance's config via the shared _ConfigProxy.

    Falls back to module-level defaults when an attribute isn't set on
    either the instance overrides or the env-var Settings — see
    src/config/config.py for the proxy behavior.
    """
    from config.config import get_config

    cfg = get_config()
    # getattr with default avoids AttributeError when neither the
    # instance overrides NOR the Settings class defines the key.
    return {
        "cdp_url": getattr(cfg, "cdp_url", None) or _DEFAULT_CDP_URL,
        "default_timeout_ms": int(
            getattr(cfg, "default_timeout_ms", None) or _DEFAULT_TIMEOUT_MS
        ),
        "user_agent": getattr(cfg, "user_agent", "") or "",
        "allowed_domains": list(getattr(cfg, "allowed_domains", None) or []),
        "block_resource_types": list(
            getattr(cfg, "block_resource_types", None) or []
        ),
        "extractor_mode": (
            getattr(cfg, "extractor_mode", None) or _DEFAULT_EXTRACTOR_MODE
        ),
    }


def _resolve_cdp_url_to_ip(cdp_url: str) -> str:
    """Rewrite a hostname-based CDP URL into an IP-based one.

    Why: Chromium's headless DevTools server enforces a Host-header
    check — it accepts only `localhost` or an IP address. When
    Playwright connects via `http://phantom-browser:9222`, the
    outbound `Host: phantom-browser:9222` fails the check and
    /json/version returns HTTP 500 with "Host header is specified
    and is not an IP address or localhost." The fix is to resolve
    the hostname to its container IP before handing the URL to
    Playwright — Chromium then sees `Host: 172.18.0.3:9222` and the
    IP-address branch of the check passes.

    --remote-allow-origins=* (set in the sidecar's Dockerfile CMD)
    only relaxes the WebSocket Origin check, NOT the HTTP Host
    check; those are two separate guards. There's no Chromium flag
    to disable the Host check, so we work around it here.

    Returns the rewritten URL when the host part resolves to a
    different IP; returns the original URL unchanged when it's
    already an IP, or 'localhost', or when resolution fails (let
    Playwright surface the error).
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse, urlunparse

    try:
        parsed = urlparse(cdp_url)
        host = parsed.hostname or ""
        if not host or host == "localhost":
            return cdp_url
        # Already an IP literal (v4 or v6) — leave alone.
        try:
            ipaddress.ip_address(host)
            return cdp_url
        except ValueError:
            pass
        ip = socket.gethostbyname(host)
        if ip == host:
            return cdp_url  # no change needed
        # Replace the hostname in the netloc, preserve the port.
        port = f":{parsed.port}" if parsed.port else ""
        new_netloc = f"{ip}{port}"
        return urlunparse(parsed._replace(netloc=new_netloc))
    except Exception as exc:  # noqa: BLE001
        logger.debug("web connector: CDP URL host resolution skipped (%s)", exc)
        return cdp_url


async def _ensure_browser() -> Browser:
    """Lazy-connect to the CDP endpoint. Idempotent.

    On first call, starts the Playwright runtime and connects over
    CDP. Subsequent calls return the cached `Browser`. Raises
    RuntimeError with operator-actionable text on connection failure
    (most common: sidecar isn't running, or `cdp_url` is wrong).
    """
    global _playwright, _browser

    if _PLAYWRIGHT_IMPORT_ERROR is not None:
        raise RuntimeError(
            "playwright not installed in phantom-agent. Add `playwright` to "
            "bundles/spark/mcp/requirements.txt and rebuild the image. "
            f"(import error: {_PLAYWRIGHT_IMPORT_ERROR})"
        )

    if _browser is not None and _browser.is_connected():
        return _browser

    cfg = _instance_config()
    cdp_url_configured = cfg["cdp_url"]
    # Resolve hostname → IP to dodge Chromium's HTTP Host-header check.
    # See _resolve_cdp_url_to_ip() docstring for the why.
    cdp_url = _resolve_cdp_url_to_ip(cdp_url_configured)
    if cdp_url != cdp_url_configured:
        logger.debug(
            "web connector: rewrote CDP URL %r -> %r (DNS for Host-header check)",
            cdp_url_configured, cdp_url,
        )

    try:
        if _playwright is None:
            _playwright = await async_playwright().start()
        # connect_over_cdp accepts http:// or ws://; Playwright fetches
        # /json/version on http to discover the WS endpoint.
        _browser = await _playwright.chromium.connect_over_cdp(cdp_url)
    except Exception as exc:  # noqa: BLE001
        # Most common errors here: connection refused (sidecar down),
        # 404 on /json/version (wrong URL), DNS failure (wrong host).
        # Produce a single actionable line for the operator.
        raise RuntimeError(
            f"could not connect to browser sidecar at {cdp_url_configured!r} "
            f"(resolved to {cdp_url!r}): {exc}. "
            "Is the phantom-browser container up? Bring it up with: "
            "`docker compose --profile browser up -d phantom-browser`"
        ) from exc

    logger.info("web connector: connected to CDP at %s", cdp_url)
    return _browser


async def _gc_idle_sessions() -> None:
    """Evict sessions idle past _SESSION_IDLE_TTL. Caller holds _lock."""
    now = time.monotonic()
    stale = [
        sid for sid, sess in _sessions.items()
        if now - sess.last_used_at > _SESSION_IDLE_TTL
    ]
    for sid in stale:
        sess = _sessions.pop(sid, None)
        if sess is None:
            continue
        try:
            await sess.context.close()
        except Exception:  # noqa: BLE001 — closing a dead context is fine
            pass
        logger.info("web connector: GC'd idle session %s", sid)


async def _get_or_create_session(
    session_id: str | None,
    cfg: dict[str, Any],
) -> _Session:
    """Return the session for `session_id`, creating one if absent.

    None / empty session_id → caller wants a one-shot ephemeral session;
    we mint a unique id and return it. Caller should `close_session`
    afterwards (or rely on GC).
    """
    browser = await _ensure_browser()

    if not session_id:
        # Ephemeral id — caller didn't supply one. Use a short stable
        # token derived from monotonic ns so different one-shots in
        # the same chat don't clobber each other's pages.
        session_id = f"ephemeral-{time.monotonic_ns()}"

    existing = _sessions.get(session_id)
    if existing is not None:
        existing.touch()
        return existing

    # Create a fresh isolated context.
    context_kwargs: dict[str, Any] = {}
    if cfg["user_agent"]:
        context_kwargs["user_agent"] = cfg["user_agent"]
    context = await browser.new_context(**context_kwargs)
    context.set_default_timeout(cfg["default_timeout_ms"])

    # Resource-type blocking: register a route handler that aborts
    # the listed types before the network request fires.
    blocked = set(cfg["block_resource_types"])
    if blocked:
        async def _route_handler(route, request):  # noqa: ANN001
            if request.resource_type in blocked:
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", _route_handler)

    page = await context.new_page()
    sess = _Session(session_id, context, page)
    _sessions[session_id] = sess
    logger.debug("web connector: opened session %s", session_id)
    return sess


def _check_allowed_domain(url: str, allowed: list[str]) -> str | None:
    """Return None if allowed (or no allow-list), else an error string.

    Allow-list semantics:
      - exact host match: "intel.example.com" matches only that host
      - leading-dot wildcard: ".example.com" matches any subdomain of
        example.com AND example.com itself

    Empty `allowed` = no restriction.
    """
    if not allowed:
        return None
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return f"could not parse host from URL {url!r}"
    if not host:
        return f"URL {url!r} has no host component"
    for entry in allowed:
        e = entry.strip().lower()
        if e.startswith("."):
            suffix = e
            if host.endswith(suffix) or host == suffix.lstrip("."):
                return None
        elif host == e:
            return None
    return (
        f"navigation to {host!r} blocked: not in allowed_domains "
        f"(configure on the connector instance)"
    )


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Return (text, was_truncated). Negative/None max_chars = no truncation."""
    if max_chars is None or max_chars < 0:
        return text, False
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


# ────────────────────────────────────────────────────────────────────
# Tool implementations
# ────────────────────────────────────────────────────────────────────


async def phantom_web_navigate(
    url: str,
    session_id: str | None = None,
    wait_until: str = "load",
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    """Navigate to URL. See connector.yaml for full signature docs."""
    if not isinstance(url, str) or not url:
        return {"error": "url must be a non-empty string"}

    cfg = _instance_config()
    deny_reason = _check_allowed_domain(url, cfg["allowed_domains"])
    if deny_reason:
        return {"error": deny_reason}

    if wait_until not in ("load", "domcontentloaded", "networkidle", "commit"):
        return {
            "error": f"wait_until must be one of "
            f"'load' | 'domcontentloaded' | 'networkidle' | 'commit' "
            f"(got {wait_until!r})"
        }

    started_at = time.monotonic()
    async with _lock:
        await _gc_idle_sessions()
        sess = await _get_or_create_session(session_id, cfg)

    try:
        response = await sess.page.goto(
            url,
            wait_until=wait_until,
            timeout=timeout_ms or cfg["default_timeout_ms"],
        )
        sess.touch()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"navigation failed: {type(exc).__name__}: {exc}"}

    return {
        "url": sess.page.url,
        "status": response.status if response is not None else None,
        "title": await sess.page.title(),
        "session_id": sess.session_id,
        "load_time_ms": int((time.monotonic() - started_at) * 1000),
    }


async def phantom_web_get_text(
    session_id: str,
    mode: str | None = None,
    max_chars: int | None = None,
) -> dict[str, Any]:
    """Extract text content from the page. See connector.yaml."""
    if not session_id:
        return {"error": "session_id is required (call navigate first)"}
    cfg = _instance_config()
    sess = _sessions.get(session_id)
    if sess is None:
        return {"error": f"unknown session_id {session_id!r}"}
    sess.touch()

    chosen_mode = (mode or cfg["extractor_mode"]).lower()
    if chosen_mode not in ("readable", "body", "markdown"):
        return {
            "error": f"mode must be 'readable' | 'body' | 'markdown' "
            f"(got {chosen_mode!r})"
        }

    cap = max_chars if max_chars is not None else _TEXT_MAX_CHARS_DEFAULT

    try:
        if chosen_mode == "body":
            # Cheap path — no Trafilatura dependency.
            raw = await sess.page.evaluate("() => document.body.innerText")
            text = (raw or "").strip()
            extractor = "body.innerText"
        else:
            if _TRAFILATURA_IMPORT_ERROR is not None:
                return {
                    "error": (
                        f"mode={chosen_mode!r} requires trafilatura, which "
                        f"failed to import: {_TRAFILATURA_IMPORT_ERROR}. "
                        "Either install it (add to requirements.txt) or "
                        "use mode='body' which doesn't need trafilatura."
                    )
                }
            html = await sess.page.content()
            output_format = "markdown" if chosen_mode == "markdown" else "txt"
            extracted = trafilatura.extract(
                html,
                output_format=output_format,
                include_comments=False,
                include_tables=True,
                favor_recall=True,
            )
            text = (extracted or "").strip()
            extractor = f"trafilatura/{output_format}"
            # Trafilatura returns None when it can't find any
            # main-content. Fall back to body.innerText so the agent
            # still gets something usable instead of an empty string.
            if not text:
                raw = await sess.page.evaluate(
                    "() => document.body.innerText"
                )
                text = (raw or "").strip()
                extractor += " (empty → body fallback)"
    except Exception as exc:  # noqa: BLE001
        return {"error": f"text extraction failed: {type(exc).__name__}: {exc}"}

    truncated_text, was_truncated = _truncate(text, cap)
    return {
        "text": truncated_text,
        "length": len(text),
        "truncated": was_truncated,
        "extractor": extractor,
    }


async def phantom_web_get_html(
    session_id: str,
    max_chars: int | None = None,
) -> dict[str, Any]:
    """Return raw HTML of the current page. See connector.yaml."""
    if not session_id:
        return {"error": "session_id is required"}
    sess = _sessions.get(session_id)
    if sess is None:
        return {"error": f"unknown session_id {session_id!r}"}
    sess.touch()

    cap = max_chars if max_chars is not None else _HTML_MAX_CHARS_DEFAULT

    try:
        html = await sess.page.content()
        url = sess.page.url
    except Exception as exc:  # noqa: BLE001
        return {"error": f"HTML read failed: {type(exc).__name__}: {exc}"}

    truncated_html, was_truncated = _truncate(html, cap)
    return {
        "html": truncated_html,
        "length": len(html),
        "truncated": was_truncated,
        "url": url,
    }


async def phantom_web_screenshot(
    session_id: str,
    full_page: bool = True,
    format: str = "png",  # noqa: A002 — name matches connector.yaml schema
    quality: int = 70,
) -> dict[str, Any]:
    """Capture a screenshot. See connector.yaml."""
    if not session_id:
        return {"error": "session_id is required"}
    sess = _sessions.get(session_id)
    if sess is None:
        return {"error": f"unknown session_id {session_id!r}"}
    sess.touch()

    if format not in ("png", "jpeg"):
        return {"error": f"format must be 'png' or 'jpeg' (got {format!r})"}

    kwargs: dict[str, Any] = {"full_page": bool(full_page), "type": format}
    if format == "jpeg":
        # Playwright wants 0-100; clamp.
        kwargs["quality"] = max(1, min(100, int(quality)))

    try:
        png_bytes = await sess.page.screenshot(**kwargs)
        # Width/height isn't directly returned by screenshot(); query
        # the viewport to give the LLM a sense of scale.
        viewport = sess.page.viewport_size or {"width": None, "height": None}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"screenshot failed: {type(exc).__name__}: {exc}"}

    return {
        "image_b64": base64.b64encode(png_bytes).decode("ascii"),
        "format": format,
        "bytes": len(png_bytes),
        "width": viewport.get("width"),
        "height": viewport.get("height"),
    }


async def phantom_web_extract_links(
    session_id: str,
    same_domain_only: bool = False,
    max_links: int | None = None,
) -> dict[str, Any]:
    """Return all anchor links on the page."""
    if not session_id:
        return {"error": "session_id is required"}
    sess = _sessions.get(session_id)
    if sess is None:
        return {"error": f"unknown session_id {session_id!r}"}
    sess.touch()

    cap = max_links if max_links is not None else _LINKS_MAX_DEFAULT

    # Return-shape choice: list of {text, href, host, is_external}.
    # Done in-page via JS so we don't pay a round-trip per link. The
    # querySelectorAll walk is O(n) and the (limited) list comes back
    # as a single JSON blob.
    js = """
    () => {
      const out = [];
      const pageHost = location.host;
      for (const a of document.querySelectorAll('a[href]')) {
        const href = a.href;
        if (!href) continue;
        let host = '';
        try { host = new URL(href, location.href).host; } catch(e) { continue; }
        out.push({
          text: (a.innerText || a.textContent || '').trim().slice(0, 240),
          href: href,
          host: host,
          is_external: host && host !== pageHost,
        });
      }
      return out;
    }
    """
    try:
        links = await sess.page.evaluate(js)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"link extraction failed: {type(exc).__name__}: {exc}"}

    if same_domain_only:
        links = [link for link in links if not link.get("is_external")]

    if cap is not None and cap >= 0:
        links = links[:cap]

    return {"links": links, "count": len(links)}


async def phantom_web_click(
    session_id: str,
    selector: str,
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    """Click an element. See connector.yaml."""
    if not session_id or not selector:
        return {"error": "session_id and selector are required"}
    cfg = _instance_config()
    sess = _sessions.get(session_id)
    if sess is None:
        return {"error": f"unknown session_id {session_id!r}"}
    sess.touch()

    pre_url = sess.page.url
    try:
        # `wait_for_navigation` would race with click; the cleaner
        # pattern in modern Playwright is to just click and check
        # whether the URL changed afterward.
        await sess.page.click(
            selector, timeout=timeout_ms or cfg["default_timeout_ms"]
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"click failed for selector {selector!r}: "
            f"{type(exc).__name__}: {exc}"
        }

    post_url = sess.page.url
    return {
        "clicked": True,
        "selector": selector,
        "navigated_to": post_url if post_url != pre_url else None,
    }


async def phantom_web_fill(
    session_id: str,
    selector: str,
    value: str,
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    """Fill an input element."""
    if not session_id or not selector:
        return {"error": "session_id and selector are required"}
    if value is None:
        return {"error": "value is required (use empty string to clear)"}
    cfg = _instance_config()
    sess = _sessions.get(session_id)
    if sess is None:
        return {"error": f"unknown session_id {session_id!r}"}
    sess.touch()

    try:
        await sess.page.fill(
            selector,
            value,
            timeout=timeout_ms or cfg["default_timeout_ms"],
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"fill failed for selector {selector!r}: "
            f"{type(exc).__name__}: {exc}"
        }

    return {"filled": True, "selector": selector}


async def phantom_web_wait_for(
    session_id: str,
    selector: str,
    state: str = "visible",
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    """Wait for an element to reach the given state."""
    if not session_id or not selector:
        return {"error": "session_id and selector are required"}
    if state not in ("attached", "detached", "visible", "hidden"):
        return {
            "error": f"state must be 'attached' | 'detached' | "
            f"'visible' | 'hidden' (got {state!r})"
        }
    cfg = _instance_config()
    sess = _sessions.get(session_id)
    if sess is None:
        return {"error": f"unknown session_id {session_id!r}"}
    sess.touch()

    try:
        await sess.page.wait_for_selector(
            selector,
            state=state,
            timeout=timeout_ms or cfg["default_timeout_ms"],
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"wait_for failed: state={state!r} selector={selector!r}: "
            f"{type(exc).__name__}: {exc}"
        }

    return {"found": True, "selector": selector}


async def phantom_web_close_session(session_id: str) -> dict[str, Any]:
    """Close a session (idempotent)."""
    if not session_id:
        return {"error": "session_id is required"}
    async with _lock:
        sess = _sessions.pop(session_id, None)
        if sess is None:
            return {"closed": True, "was_open": False}
        try:
            await sess.context.close()
        except Exception:  # noqa: BLE001 — closing a dead context is fine
            pass
    return {"closed": True, "was_open": True}


async def phantom_web_list_sessions() -> dict[str, Any]:
    """List all open sessions on this connector instance."""
    now = time.monotonic()
    out = []
    for sess in _sessions.values():
        try:
            url = sess.page.url
        except Exception:  # noqa: BLE001
            url = None
        out.append({
            "session_id": sess.session_id,
            "url": url,
            "opened_at_iso": _monotonic_to_iso_approx(sess.opened_at),
            "last_used_at_iso": _monotonic_to_iso_approx(sess.last_used_at),
            "age_seconds": int(now - sess.opened_at),
        })
    return {"sessions": out, "count": len(out)}


def _monotonic_to_iso_approx(mono: float) -> str:
    """Best-effort ISO timestamp for a monotonic-clock reading.

    We don't have a wall-clock anchor at session-open time, so this is
    approximate — derived from the current wall-clock minus the
    monotonic delta. Off by tiny amounts compared to the true open
    time but stable enough for an operator-facing list.
    """
    import datetime

    delta = time.monotonic() - mono
    wall = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=delta
    )
    return wall.isoformat(timespec="seconds")
