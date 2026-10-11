"""
Unit tests for phantom-updater.

These exercise the auth middleware + version-parsing helpers. Tests
that need a real docker daemon or GHCR access are gated behind
PHANTOM_TEST_E2E=1 and skipped by default — they're meant for an
on-VM run, not unit CI.
"""

import os

# Set MCP_TOKEN before importing src.main so the auth middleware is
# enabled with a known value. Tests run in this same process, so
# module-level import order matters.
os.environ.setdefault("MCP_TOKEN", "test-mcp-token")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.main import (  # noqa: E402
    _parse_image_ref,
    _semver_gt,
    app,
)


client = TestClient(app)


# ─── /healthz: open, no auth ─────────────────────────────────────────


def test_healthz_open():
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "ts" in body


# ─── Auth middleware ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/version/current",
        "/api/v1/version/check",
        "/api/v1/update/status",
    ],
)
def test_protected_routes_reject_no_auth(path):
    r = client.get(path)
    assert r.status_code == 401
    assert "bearer" in r.json()["detail"].lower()


@pytest.mark.parametrize(
    "header",
    [
        "Bearer wrong-token",
        "Basic dXNlcjpwYXNz",
        "test-mcp-token",  # no Bearer prefix
    ],
)
def test_protected_routes_reject_bad_auth(header):
    r = client.get(
        "/api/v1/update/status",
        headers={"Authorization": header},
    )
    assert r.status_code == 401


def test_protected_route_accepts_correct_token():
    r = client.get(
        "/api/v1/update/status",
        headers={"Authorization": "Bearer test-mcp-token"},
    )
    assert r.status_code == 200
    assert r.json() == {"in_progress": False}


def test_post_update_rejects_no_auth():
    # POST /update is the dangerous one — make sure it's gated too.
    r = client.post("/api/v1/update")
    assert r.status_code == 401


# ─── Helpers: _parse_image_ref ───────────────────────────────────────


@pytest.mark.parametrize(
    "ref, expected",
    [
        # Full GHCR ref
        (
            "ghcr.io/ayman-m/phantom-agent-oss:1.2.0",
            ("ghcr.io", "ayman-m/phantom-agent-oss", "1.2.0"),
        ),
        # Docker Hub-style
        (
            "aymanam/caldera:5.3.0",
            ("", "aymanam/caldera", "5.3.0"),
        ),
        # Bare image name
        (
            "phantom-agent-oss",
            ("", "phantom-agent-oss", "latest"),
        ),
        # Image name with tag, no registry
        (
            "phantom-xlog-oss:latest",
            ("", "phantom-xlog-oss", "latest"),
        ),
        # Image with digest-style tag (uncommon but valid)
        (
            "ghcr.io/ayman-m/phantom-agent-oss:1.2",
            ("ghcr.io", "ayman-m/phantom-agent-oss", "1.2"),
        ),
    ],
)
def test_parse_image_ref(ref, expected):
    assert _parse_image_ref(ref) == expected


# ─── Helpers: _semver_gt ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ("1.2.0", "1.1.0", True),
        ("1.2.1", "1.2.0", True),
        ("2.0.0", "1.99.99", True),
        ("1.2.0", "1.2.0", False),  # equal is not greater
        ("1.1.0", "1.2.0", False),
        # Non-semver: never greater. Important for safety — we don't
        # want a "latest" tag to compare > "1.2.0" and trigger an
        # erroneous update.
        ("latest", "1.2.0", False),
        ("1.2.0", "latest", False),
        ("1.2", "1.1.0", False),
    ],
)
def test_semver_gt(a, b, expected):
    assert _semver_gt(a, b) is expected


# ─── E2E (gated) ─────────────────────────────────────────────────────
# Only runs when PHANTOM_TEST_E2E=1 — needs a real docker daemon and
# network access to the public images. Use this after deploying a release.


_e2e_skip = pytest.mark.skipif(
    os.environ.get("PHANTOM_TEST_E2E") != "1",
    reason="set PHANTOM_TEST_E2E=1 to run end-to-end tests",
)


@_e2e_skip
def test_e2e_version_current():
    r = client.get(
        "/api/v1/version/current",
        headers={"Authorization": "Bearer test-mcp-token"},
    )
    assert r.status_code == 200
    body = r.json()
    # All three managed services should be present.
    assert set(body.keys()) == {"xlog", "caldera", "phantom-agent"}


@_e2e_skip
def test_e2e_version_check():
    r = client.get(
        "/api/v1/version/check",
        headers={"Authorization": "Bearer test-mcp-token"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "updates_available" in body
    assert "services" in body


# ─── compose helpers: project-name + correct subcommand ──────────────


def _stub_subprocess_and_project(monkeypatch):
    """Shared test fixture: pin the project-name resolver to "phantom"
    and capture the next subprocess.run cmd, returning the captured
    dict for assertions."""
    from src import main as updater_main

    captured: dict[str, object] = {}

    def fake_run(cmd, **_kwargs):
        captured["cmd"] = cmd

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setattr(updater_main, "_COMPOSE_PROJECT_NAME", "phantom")
    monkeypatch.setattr(updater_main.subprocess, "run", fake_run)
    return updater_main, captured


def test_compose_up_services_passes_project_name(monkeypatch):
    """
    _compose_up_services must invoke
    `docker compose --project-name <project> ...` so it talks to
    the same compose project the running stack is a member of.

    Without --project-name, compose derives the project from the
    compose-file's directory ("/host" inside the updater container)
    and tries to CREATE new containers under that project, hitting
    a 409 on the container_name pin (e.g. "/caldera"). The updater
    reads its own com.docker.compose.project label and passes it
    explicitly.
    """
    main, captured = _stub_subprocess_and_project(monkeypatch)

    rc, _ = main._compose_up_services(["caldera"])
    assert rc == 0
    cmd = captured["cmd"]
    assert "--project-name" in cmd, f"--project-name missing from {cmd!r}"
    pn_idx = cmd.index("--project-name")
    assert cmd[pn_idx + 1] == "phantom", f"unexpected project: {cmd[pn_idx + 1]!r}"
    # up flow uses `up -d`
    assert "up" in cmd and "-d" in cmd
    assert "caldera" in cmd


def test_compose_restart_service_uses_restart_verb(monkeypatch):
    """
    _compose_restart_service must use
    the `restart` subcommand, NOT `up -d`. `up -d` is a no-op for
    a healthy container with unchanged config — compose sees no
    diff and exits 0 without bouncing anything. We need the entrypoint
    to actually re-run (so caldera re-reads /operator-creds/caldera.yaml),
    which requires a real restart (SIGTERM the main process,
    relaunch). Reusing _compose_up_services here would silently no-op
    against an already-running caldera: the HTTP response would be 200
    but StartedAt wouldn't change and the new operator password
    wouldn't be applied.
    """
    main, captured = _stub_subprocess_and_project(monkeypatch)

    rc, _ = main._compose_restart_service("caldera")
    assert rc == 0
    cmd = captured["cmd"]
    # Must use the restart subcommand, NOT up
    assert "restart" in cmd, f"restart verb missing from {cmd!r}"
    assert "up" not in cmd, f"up should NOT be in restart cmd: {cmd!r}"
    # Project name is still required
    assert "--project-name" in cmd
    pn_idx = cmd.index("--project-name")
    assert cmd[pn_idx + 1] == "phantom"
    # The targeted service is the last positional arg
    assert cmd[-1] == "caldera"
