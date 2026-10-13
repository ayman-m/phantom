"""The MCP holds no model catalog.

The model registry in the agent (mcp/agent/lib/providers/registry) is the one
home for which models exist, what they cost and whether they are usable. The
MCP once kept a second list: `spec.models` in providers/vertex/provider.yaml,
served by GET /api/v1/models through `list_active_models`, with a
`Provider.list_models` placeholder. Nothing consumed it (the agent's own
/api/agent/models route replaced it), and a second list drifts. These tests pin
that it stays gone and that what remains of the provider loader still reports
instance counts.
"""

import sys
from pathlib import Path

import yaml

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_BUNDLE = Path(__file__).resolve().parents[2]

from api.providers import register_provider_routes
from usecase import provider_loader
from usecase.provider_store import ProviderStore


class _FakeMcp:
    """Captures the paths a register_* function mounts."""

    def __init__(self):
        self.routes: list[tuple[str, tuple[str, ...]]] = []

    def custom_route(self, path, methods=None, **_kw):
        self.routes.append((path, tuple(methods or ())))

        def deco(fn):
            return fn

        return deco


def test_models_route_is_not_mounted():
    mcp = _FakeMcp()
    register_provider_routes(mcp, ProviderStore.__new__(ProviderStore))
    paths = {p for p, _ in mcp.routes}
    assert "/api/v1/models" not in paths
    assert "/api/v1/providers" in paths
    assert not any(p.startswith("/api/v1/models") for p in paths)


def test_vertex_provider_yaml_declares_no_models():
    spec = yaml.safe_load((_BUNDLE / "providers" / "vertex" / "provider.yaml").read_text())
    assert "models" not in (spec.get("spec") or {})
    assert "spec" not in spec


def test_provider_class_has_no_list_models_placeholder():
    source = (_BUNDLE / "providers" / "vertex" / "src" / "provider.py").read_text()
    assert "list_models" not in source


def test_loader_exposes_no_catalog_surface():
    assert not hasattr(provider_loader, "list_active_models")
    assert not hasattr(provider_loader, "ProviderModel")
    assert not hasattr(provider_loader, "_instantiate_provider")


def test_provider_summary_counts_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("BUNDLE_ROOT", str(_BUNDLE))
    store = ProviderStore(data_root=tmp_path)
    assert provider_loader.provider_summary(store=store) == {"vertex": 0, "anthropic": 0, "openai": 0}
    store.create("vertex", "primary-vertex", {"project_id": "p"}, {"serviceAccountJson": "{}"})
    assert provider_loader.provider_summary(store=store) == {"vertex": 1, "anthropic": 0, "openai": 0}
    store.create("openai", "primary-openai", {}, {"api_key": "k"})
    assert provider_loader.provider_summary(store=store) == {"vertex": 1, "anthropic": 0, "openai": 1}
