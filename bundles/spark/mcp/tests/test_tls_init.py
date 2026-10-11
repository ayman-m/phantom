"""Shared-TLS ownership and boot order.

On a fresh volume the cert used to be written by phantom-agent, which compose
starts only after xlog is healthy, so xlog (and caldera) read an empty /tls,
served plain HTTP, and every `https://xlog:8000` client failed with
"[SSL] record layer failure" until a manual restart.

The fix is `mcp/agent/tls-init.sh` run by a one-shot `phantom-tls-init`
service that everything else waits for. These tests pin both halves: the
script's behaviour and the compose ordering that makes it effective.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "mcp" / "agent" / "tls-init.sh"
COMPOSE_FILES = [REPO / "installer" / "docker-compose.yml", REPO / "docker-compose.yml"]

# Built in pieces so secret scanners do not mistake an assertion about a PEM header for a key.
PEM_KEY_HEAD = "-----BEGIN " + "PRIVATE KEY-----"
PEM_CERT_HEAD = "-----BEGIN " + "CERTIFICATE-----"

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")


def _run(tls_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={**os.environ, "PHANTOM_TLS_DIR": str(tls_dir)},
        capture_output=True,
        text=True,
        timeout=60,
    )


@needs_openssl
def test_generates_a_cert_and_key_on_an_empty_volume(tmp_path):
    out = _run(tmp_path / "tls")
    assert out.returncode == 0, out.stderr
    cert, key = tmp_path / "tls" / "cert.pem", tmp_path / "tls" / "key.pem"
    assert cert.read_text().startswith(PEM_CERT_HEAD)
    assert key.read_text().startswith(PEM_KEY_HEAD)
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert stat.S_IMODE(cert.stat().st_mode) == 0o644
    # No half-written temp files left behind for a reader to trip over.
    assert sorted(p.name for p in (tmp_path / "tls").iterdir()) == ["cert.pem", "key.pem"]
    # The private key is never printed.
    assert "PRIVATE KEY" not in out.stdout + out.stderr


@needs_openssl
def test_cert_covers_every_name_the_stack_dials(tmp_path):
    _run(tmp_path)
    text = subprocess.run(
        ["openssl", "x509", "-in", str(tmp_path / "cert.pem"), "-noout", "-text"],
        capture_output=True, text=True, check=True,
    ).stdout
    for name in ("DNS:localhost", "DNS:phantom-agent", "DNS:xlog", "DNS:caldera", "IP Address:127.0.0.1"):
        assert name in text, name


@needs_openssl
def test_never_overwrites_an_existing_pair(tmp_path):
    (tmp_path / "cert.pem").write_text("operator-supplied cert")
    (tmp_path / "key.pem").write_text("operator-supplied key")
    out = _run(tmp_path)
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "cert.pem").read_text() == "operator-supplied cert"
    assert (tmp_path / "key.pem").read_text() == "operator-supplied key"
    assert "reusing" in out.stdout


@needs_openssl
def test_second_run_is_a_no_op(tmp_path):
    _run(tmp_path)
    first = (tmp_path / "cert.pem").read_bytes()
    _run(tmp_path)
    assert (tmp_path / "cert.pem").read_bytes() == first


@pytest.mark.parametrize("compose", COMPOSE_FILES, ids=lambda p: str(p.relative_to(REPO)))
def test_everything_that_reads_tls_waits_for_the_init_step(compose):
    services = yaml.safe_load(compose.read_text())["services"]
    init = services["phantom-tls-init"]
    # One-shot: runs the script, never restarts, nothing to wait for itself.
    assert init["entrypoint"] == ["/app/tls-init.sh"]
    assert init["restart"] == "no"
    assert "depends_on" not in init
    assert any(v.startswith("phantom_tls:/tls") and not v.endswith(":ro") for v in init["volumes"])
    for name in ("xlog", "phantom-agent"):
        dep = services[name]["depends_on"]["phantom-tls-init"]
        assert dep["condition"] == "service_completed_successfully", name


@pytest.mark.parametrize("compose", COMPOSE_FILES, ids=lambda p: str(p.relative_to(REPO)))
def test_agent_does_not_gate_the_cert_writer_on_its_consumer(compose):
    """The deadlock behind the fresh-install failure: the cert writer waiting for xlog while
    xlog waited for the cert. Whatever writes the cert must not depend on a
    service that reads it."""
    services = yaml.safe_load(compose.read_text())["services"]
    assert services["phantom-tls-init"].get("depends_on") is None
    for consumer in ("xlog",):
        assert "phantom-agent" not in services[consumer].get("depends_on", {}), consumer


@needs_openssl
def test_half_a_pair_is_kept_aside_not_overwritten(tmp_path):
    (tmp_path / "key.pem").write_text("operator key without its cert")
    out = _run(tmp_path)
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "key.pem.orphan").read_text() == "operator key without its cert"
    assert (tmp_path / "cert.pem").read_text().startswith(PEM_CERT_HEAD)
    assert (tmp_path / "key.pem").read_text().startswith(PEM_KEY_HEAD)
    assert "WARN" in out.stdout


def test_a_failing_openssl_shows_why(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "openssl").write_text("#!/bin/sh\necho 'boom: cannot allocate' >&2\nexit 1\n")
    (fake / "openssl").chmod(0o755)
    out = subprocess.run(
        ["bash", str(SCRIPT)],
        env={**os.environ, "PHANTOM_TLS_DIR": str(tmp_path / "tls"), "PATH": f"{fake}:{os.environ['PATH']}"},
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 1
    assert "boom: cannot allocate" in out.stderr
    assert not list((tmp_path / "tls").glob("*.tmp"))
