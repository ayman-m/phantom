"""A connector image built on a runtime base that predates the organization must still load and serve its other tools."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

CONNECTOR = Path(__file__).resolve().parents[1]


def test_xlog_tools_import_without_the_runtime_organization_modules():
    code = textwrap.dedent(f"""
        import importlib.abc, sys, types
        class Block(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if name == "runtime" or name.startswith("runtime."):
                    raise ImportError("runtime blocked for this test")
        sys.meta_path.insert(0, Block())
        # the usual hermetic stub for the host config module
        cfg_pkg, cfg = types.ModuleType("config"), types.ModuleType("config.config")
        cfg.get_config = lambda: types.SimpleNamespace(xlog_url="http://x")
        cfg_pkg.config = cfg
        sys.modules["config"], sys.modules["config.config"] = cfg_pkg, cfg
        sys.path.insert(0, {str(CONNECTOR)!r})
        from src import workers, scenarios, data_faker
        assert callable(workers.phantom_kill_worker) and callable(workers.phantom_list_workers)
        print("ok")
    """)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and "ok" in out.stdout, out.stderr[-800:]
