"""Every http-sender test sees the bundled Phantom Lab as the active organization (the container reads organization.db instead)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[5]
RUNTIME = REPO / "phantom-connector-runtime"
SEED = REPO / "bundles" / "spark" / "organization" / "phantom-lab.yaml"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))


@pytest.fixture(autouse=True)
def bundled_organization():
    from runtime import organization_view as ov
    doc = yaml.safe_load(SEED.read_text(encoding="utf-8"))
    ov.set_organization_loader(lambda pinned: doc)
    yield doc
    ov.set_organization_loader(None)
