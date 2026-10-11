"""Web connector — aggregator module.

Re-exports the public tool functions under one namespace so the
embedded MCP and `connector.yaml.source.entrypoint` can both point at a
single import target. Mirrors the structure xlog uses (one module per
concern, this file pulls them together) — the surface is
small enough to live in a single `browser.py`, but the aggregator
shape is preserved so future modules (e.g. a `pdf.py` for inline PDF
fetch+extract, or `harvester.py` for multi-link batch retrieval) can
slot in without touching the manifest.

Tool names in `connector.yaml.spec.tools[].name` are bare verbs
(`navigate`, `get_text`, ...). The `runtimeMapping.functionPrefix` is
`phantom_web_` so the actual callables are
`phantom_web_navigate`, `phantom_web_get_text`, ... — matches the
xlog convention of using a `phantom_` prefix to make audit-row tool
names self-identifying even when the namespace is stripped.
"""

from .browser import (
    phantom_web_click,
    phantom_web_close_session,
    phantom_web_extract_links,
    phantom_web_fill,
    phantom_web_get_html,
    phantom_web_get_text,
    phantom_web_list_sessions,
    phantom_web_navigate,
    phantom_web_screenshot,
    phantom_web_wait_for,
)

__all__ = [
    "phantom_web_navigate",
    "phantom_web_get_text",
    "phantom_web_get_html",
    "phantom_web_screenshot",
    "phantom_web_click",
    "phantom_web_fill",
    "phantom_web_wait_for",
    "phantom_web_extract_links",
    "phantom_web_close_session",
    "phantom_web_list_sessions",
]
