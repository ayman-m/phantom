#!/usr/bin/env python3
"""Build the JSON body for the CI bootstrap step's POST /api/v1/setup.

Runs on the CI host (not inside the agent container). Reads the
GitHub-Secret-backed Caldera credentials from env, fills compose-
service URLs for xlog + caldera, and supplies placeholder values
for XSIAM + Vertex (instance materializes; runtime calls would
fail against the placeholder URL — that's intentional, the smoke
test asserts on tool advertisement, not on every tool actually
completing).

Usage:
    python3 scripts/ci_bootstrap_setup_body.py > /tmp/setup-body.json

Required env vars:
    CALDERA_API_KEY
    CALDERA_RED_USER
    CALDERA_RED_PASSWORD

Lives as a separate file (not inline in the workflow) because YAML's
mandatory leading-space indentation breaks heredoc'd Python: top-
level statements with indent raise IndentationError. Putting the
body builder in a real file sidesteps that.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    required = ("CALDERA_API_KEY", "CALDERA_RED_USER", "CALDERA_RED_PASSWORD")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"missing required env vars: {', '.join(missing)}", file=sys.stderr)
        return 2

    # xlogApiToken: must match the value xlog was built with via
    # XLOG_API_KEY env var. When the secret isn't set (e.g. an
    # operator running locally without GitHub Secrets), fall back to
    # "ci-placeholder" — xlog's auth middleware runs in permissive
    # mode without XLOG_API_KEY, so the placeholder works fine.
    xlog_api_token = os.environ.get("XLOG_API_KEY") or "ci-placeholder"

    body = {
        "values": {
            # Real Caldera (CI brings up a real Caldera container the MCP
            # can reach). Creds from the existing 7-secret CI boundary.
            "calderaBaseUrl":     "http://caldera:8888",
            "calderaRedUser":     os.environ["CALDERA_RED_USER"],
            "calderaApiKey":      os.environ["CALDERA_API_KEY"],
            "calderaRedPassword": os.environ["CALDERA_RED_PASSWORD"],
            # xlog runs in the same compose network — service-name URL.
            "xlogBaseUrl":         "http://xlog:8000",
            "xlogWebhookEndpoint": "http://xlog:8000/webhook",
            # Real xlog token from the GitHub secret (when present)
            # so the bearer agent presents matches what xlog enforces.
            "xlogApiToken":        xlog_api_token,
            "xlogWebhookKey":      "ci-placeholder",
            # XSIAM is external; CI doesn't have a tenant, so placeholder
            # values let the connector instance MATERIALIZE (tools
            # advertise) but runtime calls would 404. That's fine for
            # the smoke test's tool-advertisement assertions.
            "xsiamPapiUrl":           "https://ci-placeholder.xsiam.invalid/api",
            "xsiamPapiAuthId":        "ci-placeholder",
            "xsiamPapiAuthHeader":    "ci-placeholder",
            "xsiamPlaygroundId":      "ci-placeholder",
            "xsiamWebhookEndpoint":   "https://ci-placeholder.xsiam.invalid/webhook",
            "xsiamWebhookKey":        "ci-placeholder",
            # Vertex provider — same placeholder strategy. The
            # serviceAccountJson must parse as valid JSON for the
            # provider __init__ to accept it; minimal stub passes that.
            "vertexProjectId": "ci-placeholder",
            "vertexRegion":    "us-central1",
            "vertexServiceAccountJson":
                '{"type":"service_account","project_id":"ci-placeholder"}',
            # Operator UI: gated behind a password. CI doesn't actually
            # log in via the browser; setting it here just prevents the
            # setup endpoint from rejecting the body for missing fields.
            "uiPassword": "ci-placeholder-not-a-real-password",
        },
        # NON-DESTRUCTIVE bootstrap: replace=False means "only create
        # instances that don't yet exist; leave operator-supplied
        # real values alone". Critical because the same persistent
        # runner state can hold values an operator filled in via the
        # setup form. Earlier replace=True silently overwrote real
        # creds with these placeholders — surfaced as the OpenSSL
        # DECODER error when chat tried to use the placeholder
        # vertex SA JSON.
        "replace": False,
    }
    json.dump(body, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
