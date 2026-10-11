"""`config` package shim — exposes the same public surface as
phantom-agent's `bundles/spark/mcp/src/config/__init__.py` so connector
code that imports `from config.config import get_config` works unchanged
when running in a container.

The actual implementation lives in `config.config`.
"""
