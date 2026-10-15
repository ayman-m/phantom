"""Permanent proof that moving the six profiles onto the organization changed nothing it did not have to.

The fixture (`fixtures/pre_organization_baseline.json`, see `pre_organization.py`) holds the sha256 of every profile, scenario,
seed and variant as the profiles produced them BEFORE they read the organization, with the values the old code drew at random
masked. Running the same calls through the cut organization (the old 12-person pool as an organization document) must give
byte-identical output, and the masks must hit exactly the same JSON paths.

If this fails after an intended change, do not edit the fixture to match: say what changed and why, and rebuild only the
affected cases.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pre_organization as pre  # noqa: E402
from src import profiles  # noqa: E402

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
FIX = pre.load_fixture()
CASES = {k: v for k, v in FIX["cases"].items() if not k.endswith(".sample_keys")}
SAMPLES = {k: v for k, v in FIX["cases"].items() if k.endswith(".sample_keys")}
VARIANTS = FIX["meta"]["variants"]


def build(key: str, view):
    profile, scenario, seed, variant = key.rsplit(".", 3)
    mod = profiles.PROFILES[profile]
    count = getattr(mod, "MIN_COUNT", {}).get(scenario) or getattr(mod, "DEFAULT_COUNT", {}).get(scenario) or 12
    return mod.build_events(scenario, count, view=view, now=NOW, seed=int(seed[1:]), **VARIANTS[variant])


@pytest.mark.parametrize("key", sorted(CASES))
def test_seeded_output_through_the_cut_organization_is_what_the_old_profile_produced(key):
    view = pre.cut_view()
    expected = CASES[key]
    sha, paths, _ = pre.masked_digest(build(key, view), expected["masked"], view)
    assert sha == expected["sha256"], f"{key}: output differs from the pre-organization capture"
    assert paths == expected["paths"], f"{key}: the mask hit other JSON paths than in the capture"


def flat(node, prefix=""):
    out = []
    if isinstance(node, dict):
        for key, value in node.items():
            out += flat(value, f"{prefix}.{key}")
    elif isinstance(node, list):
        for value in node[:1]:
            out += flat(value, f"{prefix}[]")
        if not node:
            out.append(prefix + "=[]")
    else:
        out.append(prefix)
    return out


@pytest.mark.parametrize("key", sorted(SAMPLES))
def test_sample_event_keeps_the_pre_organization_field_shape(key):
    mod = profiles.PROFILES[key.split(".", 1)[0]]
    keys = sorted(set(flat(mod.sample_event(view=pre.cut_view(), now=NOW))))
    assert hashlib.sha256("\n".join(keys).encode()).hexdigest() == SAMPLES[key]["sha256"]


def test_the_fixture_covers_every_scenario_of_the_six_profiles():
    expected = {f"{p}.{s}" for p in ("okta", "proofpoint_tap", "google_workspace", "aws_cloudtrail", "gcp_audit", "azure_ad_audit")
                for s in profiles.PROFILES[p].SCENARIOS}
    assert {k.rsplit(".", 2)[0] for k in CASES} == expected
    assert len(CASES) == len(expected) * 4  # two seeds, plain and target


def test_masks_are_limited_to_what_the_old_code_drew_at_random():
    kinds = {k: tuple(v["masked"]) for k, v in CASES.items()}
    for key, masked in kinds.items():
        profile, scenario, _seed, variant = key.rsplit(".", 3)
        mod = profiles.PROFILES[profile]
        benign = scenario in getattr(mod, "BENIGN_SCENARIOS", ()) or scenario in ("benign_logins", "benign_mail", "benign_drive")
        if profile in ("okta", "proofpoint_tap", "google_workspace") or benign:
            assert masked == (), f"{key} must be compared unmasked"
        else:
            assert set(masked) <= {"aws_account", "gcp_project", "named_actor_home_ip"}
            assert ("named_actor_home_ip" in masked) == (variant == "target")


def test_the_equivalence_test_can_fail():
    # One changed Okta id, one changed home address and one changed account id in the organization must each change a hash.
    key = "okta.benign_logins.s1.plain"
    view = pre.cut_view()
    doc = view.doc

    def sha_with(edit):
        from runtime.organization_view import OrganizationView
        d = __import__("copy").deepcopy(doc)
        edit(d)
        v = OrganizationView(d)
        return pre.masked_digest(build(key, v), [], v)[0]

    assert sha_with(lambda d: None) == CASES[key]["sha256"]
    assert sha_with(lambda d: d["people"][0].update(okta_id="00u" + "x" * 17)) != CASES[key]["sha256"]
    assert sha_with(lambda d: d["people"][0].update(home_ip="144.86.80.99")) != CASES[key]["sha256"]
    assert sha_with(lambda d: d["people"][0].update(email="n.alharbi@lab.test")) != CASES[key]["sha256"]
    benign = "aws_cloudtrail.benign_activity.s1.plain"
    assert pre.masked_digest(build(benign, view), [], view)[0] == CASES[benign]["sha256"]
    d = __import__("copy").deepcopy(doc)
    d["cloud"]["aws"]["account_id"] = "123456789012"
    from runtime.organization_view import OrganizationView
    other = OrganizationView(d)
    assert pre.masked_digest(build(benign, other), [], other)[0] != CASES[benign]["sha256"]
