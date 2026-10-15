"""Test helper: the organization that reproduces the roster the six non-Windows profiles used to hard-code, and the masking.

`tests/fixtures/pre_organization_baseline.json` holds what `okta`, `proofpoint_tap`, `google_workspace`, `aws_cloudtrail`,
`gcp_audit` and `azure_ad_audit` produced BEFORE they read the shared organization: the old 12-person pool as an organization
document (`org`: same names, emails first.last@lab.test, Okta ids from the old `user_id`, home addresses from the old
`home_for(index)`, the old fixed AWS account and GCP project) and one sha256 per profile, scenario, seed and variant.

An old profile drew some values at random (the AWS account id, the GCP project, and for a named actor a random home address).
Those values now come from the organization, so both the old capture and a new run are MASKED the same way before they are
compared: each occurrence of the value (found in the output itself) is replaced by a placeholder, and the index-free JSON paths
that were replaced are recorded; the proof then requires identical hashes AND identical masked paths.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from runtime.organization_view import OrganizationView

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.profiles import ippools  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "pre_organization_baseline.json"
PLACEHOLDERS = {"aws_account": "<AWS_ACCOUNT>", "gcp_project": "<GCP_PROJECT>", "named_actor_home_ip": "<HOME_IP>"}


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def cut_view() -> OrganizationView:
    return OrganizationView(load_fixture()["org"])


def _enc(o: Any) -> Any:
    return dataclasses.asdict(o) if dataclasses.is_dataclass(o) else str(o)


def dump(obj: Any) -> str:
    """The serialization the baseline was hashed with."""
    return json.dumps(obj, sort_keys=True, default=_enc, indent=1)


def _mask(obj: Any, repl: dict[str, str], paths: set[str], path: str = "") -> Any:
    if isinstance(obj, dict):
        return {k: _mask(v, repl, paths, f"{path}.{k}") for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask(v, repl, paths, f"{path}[]") for v in obj]
    if isinstance(obj, str):
        out = obj
        for old in sorted(repl, key=len, reverse=True):
            out = out.replace(old, repl[old])
        if out != obj:
            paths.add(path)
        return out
    return obj


def replacements(kinds: list[str], events: list[dict[str, Any]], view: OrganizationView) -> dict[str, str]:
    """The values to mask in a NEW run: the organization's account / project and the home-pool addresses."""
    repl: dict[str, str] = {}
    if "aws_account" in kinds:
        repl[view.doc["cloud"]["aws"]["account_id"]] = PLACEHOLDERS["aws_account"]
    if "gcp_project" in kinds:
        repl[view.doc["cloud"]["gcp"]["project_id"]] = PLACEHOLDERS["gcp_project"]
    if "named_actor_home_ip" in kinds:
        repl.update({ippools.home_for(k)[0]: PLACEHOLDERS["named_actor_home_ip"] for k in range(len(ippools.HOME))})
    return repl


def masked_digest(events: list[dict[str, Any]], kinds: list[str], view: OrganizationView) -> tuple[str, list[str], str]:
    """(sha256, sorted index-free paths that were masked, the masked text) of a new run's events."""
    repl = replacements(kinds, events, view)
    paths: set[str] = set()
    masked = _mask(copy.deepcopy(events), repl, paths)
    text = dump(masked)
    return hashlib.sha256(text.encode()).hexdigest(), sorted(p.lstrip(".") for p in paths), text
