"""Shared MCP runtime infrastructure.

Per-connector helpers live in each connector's `src/_*.py` so
connectors are self-contained. Only truly cross-connector infra
(logging) lives here.
"""

from .setup_logging import setup_logging

__all__ = ["setup_logging"]
