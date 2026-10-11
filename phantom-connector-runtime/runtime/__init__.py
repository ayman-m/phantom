"""phantom-connector-runtime — base library for per-instance connector
containers.

Submodules:
  - secret_store_client: read-only AES-GCM decrypt, mirrors
    bundles/spark/mcp/src/usecase/secret_store.py crypto envelope.
  - instance_store_client: read-only SQLite client, looks up instance
    config + secret_refs by INSTANCE_ID at boot.
  - audit_forwarder: fire-and-forget POST of audit events to the
    agent's /api/v1/audit endpoint.
  - entrypoint: bootstraps the FastMCP server, loads the connector
    module, wires per-instance config into the contextvar shim.
"""
