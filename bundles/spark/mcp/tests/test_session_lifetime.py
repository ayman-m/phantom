"""Operator-configurable UI session lifetime.

The lifetime lives in ONE place: the `auth_settings` table of
`auth_sessions.db`, owned by AuthStore. These tests cover:

  - the store: default, bounds (whole hours 1..24, no bool/float/str),
    persistence across a store reload, create_session using the stored
    value, already-minted sessions keeping their expiry
  - the REST surface `/api/v1/ui/auth/session_lifetime`: GET, POST/PUT,
    401 on a bad session, 403 on a wrong current password, 400 on bad
    hours, the audit rows (old/new hours, never a secret)
  - the guardrail: REST/UI-only. No agent tool, no settings key, and no
    API-key route reaches it.
"""
from __future__ import annotations

import base64
import os
import sqlite3
import time

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.auth import api_key_allows
from api.ui_auth import register_ui_auth_routes
from config.config import config as _config
from usecase import auth_store as auth_store_module
from usecase import connector_loader
from usecase.api_keys import SqliteApiKeyStore, set_api_key_store
from usecase.audit_log import SqliteAuditLog, set_audit_log
from usecase.auth_store import (
    DEFAULT_SESSION_TTL_HOURS,
    MAX_SESSION_TTL_HOURS,
    MIN_SESSION_TTL_HOURS,
    AuthStore,
    SessionLifetimeError,
)
from usecase.secret_store import KEK_ENV_VAR, SecretStore

PASSWORD = "CorrectHorse9"
PATH = "/api/v1/ui/auth/session_lifetime"
BEARER = {"Authorization": "Bearer test-mcp-token"}


@pytest.fixture
def kek(monkeypatch):
    monkeypatch.setenv(KEK_ENV_VAR, base64.b64encode(os.urandom(32)).decode())


def _new_store(tmp_path) -> AuthStore:
    return AuthStore(
        SecretStore(data_root=tmp_path), sessions_db_path=tmp_path / "sessions.db",
    )


@pytest.fixture
def store(tmp_path, kek) -> AuthStore:
    s = _new_store(tmp_path)
    s.seed_admin_defaults_if_empty("admin", PASSWORD)
    return s


# ─── Store ───────────────────────────────────────────────────────


def test_default_is_two_hours(store):
    assert DEFAULT_SESSION_TTL_HOURS == 2
    assert store.session_ttl_hours() == 2


def test_create_session_without_setting_expires_in_two_hours(store):
    before = int(time.time() * 1000)
    token = store.create_session("admin")
    expires = store.validate_session(token)["expires_at_ms"]
    assert abs((expires - before) - 2 * 3600 * 1000) < 5_000


@pytest.mark.parametrize("hours", [1, 2, 10, 24])
def test_set_accepts_whole_hours_in_range(store, hours):
    store.set_session_ttl_hours(hours)
    assert store.session_ttl_hours() == hours


@pytest.mark.parametrize(
    "bad", [0, -1, 25, 100, 1.5, 2.0, "10", "", None, True, False, [10], {"h": 10}],
)
def test_set_rejects_everything_else(store, bad):
    store.set_session_ttl_hours(6)
    with pytest.raises(SessionLifetimeError):
        store.set_session_ttl_hours(bad)
    assert store.session_ttl_hours() == 6  # unchanged


def test_bounds_constants():
    assert (MIN_SESSION_TTL_HOURS, MAX_SESSION_TTL_HOURS) == (1, 24)


def test_set_returns_previous_value(store):
    assert store.set_session_ttl_hours(10) == 2
    assert store.set_session_ttl_hours(4) == 10


def test_value_survives_store_reload(tmp_path, kek):
    first = _new_store(tmp_path)
    first.set_session_ttl_hours(10)
    reloaded = _new_store(tmp_path)  # fresh instance, same files
    assert reloaded.session_ttl_hours() == 10


def test_create_session_uses_stored_value(store):
    store.set_session_ttl_hours(10)
    before = int(time.time() * 1000)
    token = store.create_session("admin")
    expires = store.validate_session(token)["expires_at_ms"]
    assert abs((expires - before) - 10 * 3600 * 1000) < 5_000


def test_existing_sessions_keep_their_expiry(store):
    old = store.create_session("admin")
    old_expiry = store.validate_session(old)["expires_at_ms"]
    store.set_session_ttl_hours(24)
    assert store.validate_session(old)["expires_at_ms"] == old_expiry
    new = store.create_session("admin")
    assert store.validate_session(new)["expires_at_ms"] > old_expiry + 20 * 3600 * 1000


def test_setting_is_not_shadowed_by_the_environment(store, monkeypatch):
    """One storage home: no PHANTOM_SECRET__* overlay or env var can override it."""
    store.set_session_ttl_hours(10)
    monkeypatch.setenv("PHANTOM_SECRET__UI__AUTH__SESSION_TTL_HOURS", "1")
    monkeypatch.setenv("SESSION_TTL_HOURS", "1")
    assert store.session_ttl_hours() == 10


# ─── REST ────────────────────────────────────────────────────────


class _FakeMcp:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods=None, include_in_schema=True):
        def deco(fn):
            for m in methods or ["GET"]:
                self.routes[(path, m)] = fn
            return fn

        return deco


@pytest.fixture
def api(tmp_path, kek, monkeypatch):
    monkeypatch.setattr(_config, "mcp_token", "test-mcp-token")
    s = _new_store(tmp_path)
    s.seed_admin_defaults_if_empty("admin", PASSWORD)
    auth_store_module.reset_for_tests()
    auth_store_module._store = s
    audit = SqliteAuditLog(data_root=tmp_path / "audit")
    set_audit_log(audit)
    mcp = _FakeMcp()
    register_ui_auth_routes(mcp)
    app = Starlette()
    for (path, method), fn in mcp.routes.items():
        app.add_route(path, fn, methods=[method])
    yield TestClient(app), s, audit
    set_audit_log(None)
    auth_store_module.reset_for_tests()


def _post(c, token, **body):
    payload = {"session_token": token, "current_password": PASSWORD, "hours": 10}
    payload.update(body)
    return c.post(PATH, json=payload, headers=BEARER)


def test_get_returns_hours_and_default(api):
    c, s, _ = api
    assert c.get(PATH, headers=BEARER).json() == {"hours": 2, "default_hours": 2}
    s.set_session_ttl_hours(10)
    assert c.get(PATH, headers=BEARER).json() == {"hours": 10, "default_hours": 2}


def test_get_and_post_require_the_mcp_token(api):
    c, s, _ = api
    token = s.create_session("admin")
    assert c.get(PATH).status_code in (401, 403)
    r = c.post(PATH, json={"session_token": token, "current_password": PASSWORD, "hours": 10})
    assert r.status_code in (401, 403)
    assert s.session_ttl_hours() == 2


def test_post_sets_the_value_and_applies_to_new_sessions(api):
    c, s, _ = api
    token = s.create_session("admin")
    old_expiry = s.validate_session(token)["expires_at_ms"]
    r = _post(c, token, hours=10)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "hours": 10, "previous_hours": 2, "default_hours": 2}
    assert s.session_ttl_hours() == 10
    assert s.validate_session(token)["expires_at_ms"] == old_expiry  # not extended
    # Login now returns a 10 hour expiry, which is what the cookie is derived from.
    login = c.post(
        "/api/v1/ui/auth/login",
        json={"username": "admin", "password": PASSWORD},
        headers=BEARER,
    ).json()
    assert abs((login["expires_at_ms"] - time.time() * 1000) - 10 * 3600 * 1000) < 5_000


def test_put_is_accepted_too(api):
    c, s, _ = api
    token = s.create_session("admin")
    r = c.put(
        PATH,
        json={"session_token": token, "current_password": PASSWORD, "hours": 8},
        headers=BEARER,
    )
    assert r.status_code == 200
    assert s.session_ttl_hours() == 8


def test_invalid_session_is_401(api):
    c, s, _ = api
    r = _post(c, "not-a-real-token")
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_session"
    assert s.session_ttl_hours() == 2


def test_revoked_session_is_401(api):
    c, s, _ = api
    token = s.create_session("admin")
    s.revoke_session(token)
    assert _post(c, token).status_code == 401
    assert s.session_ttl_hours() == 2


def test_wrong_current_password_is_refused_and_changes_nothing(api):
    """Same contract as change_password: 401 = bad session, 403 = wrong password."""
    c, s, audit = api
    token = s.create_session("admin")
    r = _post(c, token, current_password="WrongPassword1")
    assert r.status_code == 403
    assert r.json()["code"] == "current_password_incorrect"
    assert s.session_ttl_hours() == 2
    rows = audit.query(action="session_lifetime_change_rejected")
    assert len(rows) == 1
    assert rows[0]["status"] == "failure"
    assert "WrongPassword1" not in str(rows[0]) and PASSWORD not in str(rows[0])


@pytest.mark.parametrize("bad", [0, 25, -3, 1.5, "10", None, True])
def test_out_of_bounds_or_wrong_type_is_400(api, bad):
    c, s, _ = api
    token = s.create_session("admin")
    r = _post(c, token, hours=bad)
    assert r.status_code == 400
    assert s.session_ttl_hours() == 2


def test_missing_fields_are_400(api):
    c, s, _ = api
    token = s.create_session("admin")
    for field in ("session_token", "current_password", "hours"):
        body = {"session_token": token, "current_password": PASSWORD, "hours": 10}
        del body[field]
        assert c.post(PATH, json=body, headers=BEARER).status_code == 400
    assert s.session_ttl_hours() == 2


def test_success_writes_an_audit_row_with_old_and_new_hours_and_no_secret(api):
    c, s, audit = api
    token = s.create_session("admin")
    assert _post(c, token, hours=10).status_code == 200
    rows = audit.query(action="session_lifetime_changed")
    assert len(rows) == 1
    row = rows[0]
    assert row["actor"] == "user:admin"
    assert row["status"] == "success"
    meta = row["metadata"]
    assert meta["old_hours"] == 2 and meta["new_hours"] == 10
    blob = str(row)
    assert PASSWORD not in blob and token not in blob


def test_change_password_tags_its_401_and_403_the_same_way(api):
    """The Next.js client maps on `code`, so change_password carries it too."""
    c, s, _ = api
    token = s.create_session("admin")
    body = {"session_token": token, "current_password": "WrongPassword1", "new_password": "BrandNewPw99"}
    r = c.post("/api/v1/ui/auth/change_password", json=body, headers=BEARER)
    assert r.status_code == 403 and r.json()["code"] == "current_password_incorrect"
    body["session_token"] = "not-a-real-token"
    r = c.post("/api/v1/ui/auth/change_password", json=body, headers=BEARER)
    assert r.status_code == 401 and r.json()["code"] == "invalid_session"


def test_a_bad_bearer_is_a_bare_403_without_the_wrong_password_code(api):
    """require_bearer's own refusals must stay distinguishable from a wrong password."""
    c, s, _ = api
    token = s.create_session("admin")
    r = c.post(
        PATH,
        json={"session_token": token, "current_password": PASSWORD, "hours": 10},
        headers={"Authorization": "Bearer not-the-token"},
    )
    assert r.status_code == 403
    assert "code" not in r.json()
    assert s.session_ttl_hours() == 2


# ─── Existing installs: auth_sessions.db created before auth_settings ───

_OLD_SCHEMA = """
CREATE TABLE sessions (
    token_hash         TEXT PRIMARY KEY NOT NULL,
    username           TEXT NOT NULL,
    created_at_ms      INTEGER NOT NULL,
    expires_at_ms      INTEGER NOT NULL,
    user_agent_hash    TEXT,
    revoked_at_ms      INTEGER
);
CREATE INDEX idx_sessions_username ON sessions (username);
CREATE INDEX idx_sessions_expires ON sessions (expires_at_ms);
"""


def test_a_database_created_with_the_old_schema_upgrades_in_place(tmp_path, kek):
    db = tmp_path / "sessions.db"
    far_future = int(time.time() * 1000) + 3_600_000
    conn = sqlite3.connect(db)
    conn.executescript(_OLD_SCHEMA)
    conn.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, NULL, NULL)",
        ("a" * 64, "admin", 1, far_future),
    )
    conn.commit()
    conn.close()
    tables = lambda: {  # noqa: E731
        r[0] for r in sqlite3.connect(db).execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "auth_settings" not in tables()

    store = AuthStore(SecretStore(data_root=tmp_path), sessions_db_path=db)
    assert "auth_settings" in tables()
    assert store.session_ttl_hours() == 2  # nothing stored yet: the default
    assert store.set_session_ttl_hours(10) == 2
    assert AuthStore(SecretStore(data_root=tmp_path), sessions_db_path=db).session_ttl_hours() == 10
    kept = sqlite3.connect(db).execute("SELECT username FROM sessions").fetchall()
    assert kept == [("admin",)]  # existing session rows untouched


# ─── Guardrail: REST/UI only ─────────────────────────────────────


def test_no_agent_tool_exposes_the_session_lifetime():
    names = [name for name, _fn in connector_loader._BUILTIN_LEGACY_TOOLS]
    assert not [n for n in names if "session_lifetime" in n or "session_ttl" in n]


def test_api_keys_cannot_reach_the_route_on_8080():
    for scopes in (["*"], ["settings:write"], ["settings:read"], ["agent:*"]):
        for method in ("GET", "POST", "PUT"):
            assert api_key_allows(scopes, method, PATH) is False


def test_settings_tooling_cannot_see_or_set_it():
    """settings_get/settings_update read the manifest-bounded settings store."""
    from pathlib import Path

    import yaml

    manifest = Path(__file__).resolve().parents[2] / "manifest.yaml"
    settings = yaml.safe_load(manifest.read_text(encoding="utf-8"))["settings"]
    keys = set(settings["defaults"]) | set(settings["overridable"])
    assert not [k for k in keys if "session" in k.lower() or "ttl" in k.lower()]


def test_a_real_api_key_is_refused_with_403_on_the_mcp_route(api, tmp_path):
    """Not just api_key_allows(): mint a key and call the route with it."""
    c, s, _ = api
    keys = SqliteApiKeyStore(data_root=tmp_path / "keys")
    set_api_key_store(keys)
    try:
        for scopes in (["*"], ["settings:write"], ["agent:*"]):
            plaintext = keys.create(label="t", scopes=scopes, actor="ayman").plaintext
            auth = {"Authorization": f"Bearer {plaintext}"}
            token = s.create_session("admin")
            assert c.get(PATH, headers=auth).status_code == 403
            body = {"session_token": token, "current_password": PASSWORD, "hours": 24}
            assert c.post(PATH, json=body, headers=auth).status_code == 403
            assert c.put(PATH, json=body, headers=auth).status_code == 403
            assert s.session_ttl_hours() == 2  # never changed
    finally:
        set_api_key_store(None)
