"""Connector image pins live in /host/connector-digests.env and nowhere else.

`.env` carries credentials and the core compose-substitution digests; the
per-connector pins (DIGEST_PHANTOM_CONNECTOR_*) are runtime data for the
updater and have their own file. The updater never reads a connector pin from
`.env`, and applying a release manifest writes the two files separately.
"""

import os

os.environ.setdefault("MCP_TOKEN", "test-mcp-token")

import pytest  # noqa: E402

from src import main as updater_main  # noqa: E402

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
CORE = "sha256:" + "c" * 64


@pytest.fixture()
def host_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(updater_main, "HOST_INSTALL_DIR", str(tmp_path))
    updater_main._invalidate_host_env_cache()
    updater_main._invalidate_host_connector_digests_cache()
    updater_main._HOST_CONNECTOR_DIGESTS_CACHE.clear()
    updater_main._HOST_ENV_CACHE.clear()
    yield tmp_path
    updater_main._HOST_CONNECTOR_DIGESTS_CACHE.clear()
    updater_main._HOST_ENV_CACHE.clear()


def test_connector_digest_is_read_from_connector_digests_env(host_dir):
    (host_dir / "connector-digests.env").write_text(
        f"DIGEST_PHANTOM_CONNECTOR_XSIAM={DIGEST_A}\n"
    )
    assert updater_main._connector_digest("xsiam") == DIGEST_A


def test_connector_digest_ignores_dotenv(host_dir):
    """A connector pin in .env is not consulted, with or without the file."""
    (host_dir / ".env").write_text(f"DIGEST_PHANTOM_CONNECTOR_XSIAM={DIGEST_A}\n")
    assert updater_main._connector_digest("xsiam") is None

    (host_dir / "connector-digests.env").write_text(
        f"DIGEST_PHANTOM_CONNECTOR_XSIAM={DIGEST_B}\n"
    )
    updater_main._invalidate_host_connector_digests_cache()
    assert updater_main._connector_digest("xsiam") == DIGEST_B


def test_apply_manifest_splits_core_and_connector_pins(host_dir):
    (host_dir / ".env").write_text(
        "MCP_TOKEN=keep-me\n"
        "PHANTOM_VERSION=0.1.0\n"
        f"DIGEST_PHANTOM_AGENT={DIGEST_B}\n"
        f"DIGEST_PHANTOM_CONNECTOR_XSIAM={DIGEST_B}\n"
    )
    updater_main._apply_manifest_to_env({
        "PHANTOM_VERSION": "0.2.0",
        "DIGEST_PHANTOM_AGENT": CORE,
        "DIGEST_PHANTOM_CONNECTOR_XSIAM": DIGEST_A,
        "DIGEST_PHANTOM_CONNECTOR_CALDERA": DIGEST_A,
    })

    env_text = (host_dir / ".env").read_text()
    assert "MCP_TOKEN=keep-me" in env_text
    assert "PHANTOM_VERSION=0.2.0" in env_text
    assert f"DIGEST_PHANTOM_AGENT={CORE}" in env_text
    assert "DIGEST_PHANTOM_CONNECTOR_" not in env_text

    pins = (host_dir / "connector-digests.env").read_text()
    assert f"DIGEST_PHANTOM_CONNECTOR_XSIAM={DIGEST_A}" in pins
    assert f"DIGEST_PHANTOM_CONNECTOR_CALDERA={DIGEST_A}" in pins
    assert "DIGEST_PHANTOM_AGENT" not in pins

    # The in-process caches see the new values immediately.
    assert updater_main._connector_digest("xsiam") == DIGEST_A
    assert updater_main._stack_digest("phantom-agent") == CORE
