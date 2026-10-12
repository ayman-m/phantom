"""Configuration settings for Phantom MCP Server.

Per-call instance config injection via contextvar.

The MCP wrapper sets `_current_instance_overrides` before invoking each
tool to the calling instance's resolved config + secrets. `get_config()`
returns a `_ConfigProxy` that reads first from the overrides, then
delegates to the env-var Settings — so connector functions don't need
to know whether they're running under an instance or env-var fallback.

This is the keystone of per-instance config: each tool call honors its
connector instance's config without touching function signatures.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuration model using Pydantic.
    Loads settings from environment variables.
    """

    # --- Xlog (log-generation service) Settings ---
    # xlog is the standalone GraphQL log-gen service. The agent product
    # is "phantom-agent"; this is the underlying service its xlog
    # connector talks to.
    # The default is https://localhost:8000 because xlog serves HTTPS
    # unconditionally. The default
    # applies in unit tests / dev shells where XLOG_URL env var is unset;
    # production always sets XLOG_URL=https://xlog:8000 via compose env.
    xlog_url: str = Field("https://localhost:8000", validation_alias="XLOG_URL")
    xlog_port: int = Field(8000, validation_alias="XLOG_PORT")
    # Bearer token presented to xlog on every connector call. Per-
    # instance value comes from the SecretStore (resolved through the
    # contextvar at tool-call time); the env-var fallback is mostly
    # for legacy / pre-instance dev setups.
    xlog_api_token: str | None = Field(None, validation_alias="XLOG_API_TOKEN")

    # --- MCP Server Settings ---
    mcp_transport: str = Field("stdio", validation_alias="MCP_TRANSPORT")
    mcp_host: str = Field("0.0.0.0", validation_alias="MCP_HOST")
    mcp_port: int = Field(8080, validation_alias="MCP_PORT")
    mcp_path: str = Field("/api/v1/stream/mcp", validation_alias="MCP_PATH")

    # --- SSL Settings ---
    # PHANTOM_TLS_CERT_FILE / PHANTOM_TLS_KEY_FILE are the preferred env
    # names. SSL_CERT_FILE / SSL_KEY_FILE collide with OpenSSL/Python's
    # outbound-trust semantics: setting SSL_CERT_FILE in the process env
    # causes Python's ssl module to use that single PEM as the entire CA
    # trust bundle, breaking every outbound HTTPS call (Vertex AI
    # embeddings, Gemini, etc.) with CERTIFICATE_VERIFY_FAILED.
    # AliasChoices keeps SSL_CERT_FILE readable as a fallback for
    # environments that still set it, but deployments should use the
    # PHANTOM_-prefixed names, which the entrypoint script exports.
    ssl_cert_file: str | None = Field(
        None,
        validation_alias=AliasChoices("PHANTOM_TLS_CERT_FILE", "SSL_CERT_FILE"),
    )
    ssl_key_file: str | None = Field(
        None,
        validation_alias=AliasChoices("PHANTOM_TLS_KEY_FILE", "SSL_KEY_FILE"),
    )
    ssl_cert_pem: str | None = Field(None, validation_alias="SSL_CERT_PEM")
    ssl_key_pem: str | None = Field(None, validation_alias="SSL_KEY_PEM")

    # --- Log Settings ---
    log_level: str = Field("INFO", validation_alias="LOG_LEVEL")
    log_file_path: str | None = Field(None, validation_alias="LOG_FILE_PATH")

    # --- XSIAM PAPI Settings ---
    papi_url_env_key: str = Field("", validation_alias="CORTEX_MCP_PAPI_URL")
    papi_auth_header_key: str = Field("", validation_alias="CORTEX_MCP_PAPI_AUTH_HEADER")
    papi_auth_id_key: str = Field("", validation_alias="CORTEX_MCP_PAPI_AUTH_ID")
    playground_id: str = Field("", validation_alias="PLAYGROUND_ID")
    webhook_endpoint: str | None = Field(None, validation_alias="WEBHOOK_ENDPOINT")
    webhook_key: str | None = Field(None, validation_alias="WEBHOOK_KEY")

    # --- Caldera Settings ---
    caldera_url: str = Field("http://localhost:8888/api/v2/", validation_alias="CALDERA_URL")
    caldera_api_key: str = Field("ADMIN123", validation_alias="CALDERA_API_KEY")


    # --- admin HTTP API auth ---
    mcp_token: str | None = Field(
        None,
        validation_alias="MCP_TOKEN",
        description=(
            "Shared bearer token guarding the MCP's admin endpoints "
            "(/api/v1/instances, /api/v1/providers, ...). The Next.js "
            "agent's /api/agent/* proxies send this in the Authorization header. "
            "When unset the admin endpoints reject all requests."
        ),
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Global config instance (env-var-backed)
config = Settings()


# ─────────────────────────────────────────────────────────────────
# Per-call instance config injection
# ─────────────────────────────────────────────────────────────────


_current_instance_overrides: ContextVar[dict[str, Any] | None] = ContextVar(
    "_current_instance_overrides", default=None,
)


class _ConfigProxy:
    """Merges per-instance overrides on top of env-var Settings.

    Read of `.attr`:
      - if instance overrides has a key matching the attribute → return it
      - else delegate to underlying Settings via getattr

    The override dict is the instance's `config + secrets` flattened
    (see InstanceStore.Instance.merged_config). Keys MUST match the
    Settings attribute names that connector functions read; the
    instance materialization step (see connector_loader.auto_migrate
    + the setup.bindsInstances mapping) is responsible for
    using the right key names.
    """

    __slots__ = ("_overrides", "_settings")

    def __init__(self, overrides: dict[str, Any], settings: Settings) -> None:
        self._overrides = overrides
        self._settings = settings

    def __getattr__(self, name: str) -> Any:
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._settings, name)


def reload_config():
    """Reload the global config instance from current env vars."""
    global config
    config = Settings()
    return config


def get_config():
    """Return the active config — instance-aware when called inside a tool.

    During a tool invocation (the MCP wrapper has set the contextvar),
    this returns a `_ConfigProxy` that overlays the instance's
    `config + secrets` on top of the env-var `Settings`. Outside a tool
    invocation (e.g. server bootstrap reading `mcp_host`/`mcp_port`),
    it returns the underlying `Settings` directly.
    """
    overrides = _current_instance_overrides.get()
    if overrides:
        return _ConfigProxy(overrides, config)
    return config


def set_current_instance(overrides: dict[str, Any] | None) -> Any:
    """Set the per-call instance overrides; returns a token for `reset_current_instance`."""
    return _current_instance_overrides.set(overrides)


def reset_current_instance(token: Any) -> None:
    """Reset the contextvar to its prior value (paired with `set_current_instance`)."""
    _current_instance_overrides.reset(token)
