"""Golden snapshot of the 0.3.1 profiles: `okta` (its original four scenarios), `proofpoint_tap` and `google_workspace`.

0.4.0 added Cribl mode and new profiles but promised that these three produce exactly what they did before. The hashes
below were computed from the git HEAD copies of the profile modules at the 0.3.1 commit
(`git show HEAD:bundles/spark/connectors/http-sender/src/profiles/<file>`, loaded as a separate package), by
hashing the sorted-key JSON of `build_events(scenario, 12, domain="lab.test", now=NOW, **variant)` over three variants,
and the flattened key paths of `sample_event`. A change to any of those modules that alters a seeded event, a timestamp,
an address or a field shape fails here; if the change is intended, recompute the hashes and say why in the commit.

Run from the connector directory:  python3 -m pytest -x
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.profiles import google_workspace, okta, proofpoint_tap  # noqa: E402

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
VARIANTS = [dict(seed=1), dict(seed=7),
            dict(seed=99, spread_seconds=300, start_offset_minutes=10, target_user="khalid.alotaibi")]
MODULES = {"okta": okta, "proofpoint_tap": proofpoint_tap, "google_workspace": google_workspace}
ORIGINAL_OKTA = ("benign_logins", "failed_then_success", "password_spray", "mfa_fatigue")

GOLDEN = {
    "okta.benign_logins": "34f429f8fd72d9edbc0054c33b1d058d3e1f0d1304913c78730b8510217337a1",
    "okta.failed_then_success": "f39286d3e5730a8edcab609513cbd56e56639a296d518cbdd65e0e767e84cb61",
    "okta.password_spray": "0aebb51b05f284db8b1572adb82fd20a093f21b34abf5e717f396ed92bf8ee07",
    "okta.mfa_fatigue": "deb01eae95ed2b9e11d1cea91421c21158b247c116157300d5728d559dcd6531",
    "okta.sample_event_keys": "0beb662d1edec89f838e860ee27c8442254a673b831914c84b04aa8dc59e9f4e",
    "proofpoint_tap.benign_mail": "612156a70377a03a37b811a899163ed2052f775e165352e059d3ce7f7012d2a6",
    "proofpoint_tap.phishing_url": "7e9f0d6435239e051dbab59665bae2faf25579cc2f3d65563a7135e8a49201c3",
    "proofpoint_tap.malware_attachment": "401fd6bf065c2e712b11e49cc3bd1488434e6a01f7c3dce92f51a6f37273db38",
    "proofpoint_tap.credential_phishing": "656a4e21da0ca9942a2a51c96c05853ec7fcdbd27d90c695a032bb121d83920f",
    "proofpoint_tap.bec_impostor": "a3fddecee3efc4ecbcc3069a661300010247ca812f9a019a7401777e98477d55",
    "proofpoint_tap.click_chain": "aec4ee271c5bc484fdcc30a1e8c411d51a2ad8bb6a90343ebfa9edf10711cf9f",
    "proofpoint_tap.sample_event_keys": "c22bdbb7eebae997e62965044f9d7133e853afba8e08ebf79a5486a773213b04",
    "google_workspace.benign_drive": "98f5e6df77726b665424ca44bb8a1104ac1ba8fa7d1aecc8b979f812768724f7",
    "google_workspace.public_share": "fc8309c050d8baabedb6b65ae3d3bc040a5fe044b93133fdfb18a6377e1cf310",
    "google_workspace.sensitive_download": "b64407e1c7951a8ae3c86c4b2db86bb681cc8fd0ef0694adb82e7d3fd497cf0e",
    "google_workspace.impossible_travel_login": "334459572e429ae298bb68bc3587650b3192ca0cf2a761bd0eabd34c0e6599d4",
    "google_workspace.sample_event_keys": "018058d9c8631c7b615b61a573465a49abec1d3481869a2ae8bf7341c26ebb81",
}


def flat(node, prefix=""):
    """The key paths of a JSON value (the first element stands for a list), for comparing event SHAPES."""
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


def scenario_hash(module, scenario):
    digest = hashlib.sha256()
    for variant in VARIANTS:
        events = module.build_events(scenario, 12, domain="lab.test", now=NOW, **variant)
        digest.update(json.dumps(events, sort_keys=True).encode())
    return digest.hexdigest()


def sample_keys_hash(module):
    keys = sorted(set(flat(module.sample_event(domain="lab.test", now=NOW))))
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()


CASES = [(name, sc) for name, mod in MODULES.items() for sc in (ORIGINAL_OKTA if name == "okta" else mod.SCENARIOS)]


@pytest.mark.parametrize("name,scenario", CASES, ids=[f"{n}.{s}" for n, s in CASES])
def test_seeded_scenario_output_is_what_0_3_1_produced(name, scenario):
    assert scenario_hash(MODULES[name], scenario) == GOLDEN[f"{name}.{scenario}"]


@pytest.mark.parametrize("name", list(MODULES))
def test_sample_event_has_the_0_3_1_field_shape(name):
    assert sample_keys_hash(MODULES[name]) == GOLDEN[f"{name}.sample_event_keys"]


def test_every_golden_entry_is_used_and_the_scenario_lists_only_grew():
    assert set(GOLDEN) == {f"{n}.{s}" for n, s in CASES} | {f"{n}.sample_event_keys" for n in MODULES}
    assert set(ORIGINAL_OKTA) <= set(okta.SCENARIOS)
    assert proofpoint_tap.SCENARIOS == ("benign_mail", "phishing_url", "malware_attachment", "credential_phishing",
                                        "bec_impostor", "click_chain")


def test_the_golden_test_can_fail(monkeypatch):
    # A one-character change to a pool address must change a hash (the guard is not vacuous).
    before = scenario_hash(okta, "benign_logins")
    monkeypatch.setattr(okta.ippools, "home_for", lambda i: ("1.2.3.4", okta.ippools.HOME[0]))
    assert scenario_hash(okta, "benign_logins") != before
