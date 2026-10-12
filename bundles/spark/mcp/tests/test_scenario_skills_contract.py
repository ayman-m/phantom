"""Contract for the shipped scenario skills (bundles/spark/mcp/skills/scenarios).

Found in the journey pass: a live run of large_file_upload_exfil generated its SaaS
stage with a generic schema although no SaaS source was installed, and a DNS run
quoted a `dns_logs` dataset that no data source produces. The skills must
(1) carry an explicit, numbered class check with the sentence to say, and
(2) name only datasets a data source can actually produce.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SCENARIOS = Path(__file__).resolve().parents[1] / "skills" / "scenarios"
SKILLS = sorted(SCENARIOS.glob("*.md"))
INVENTED_DATASETS = re.compile(r"dataset\s*=\s*(dns|edr|vpn|firewall|waf|proxy|ndr)_logs\b")


def test_scenarios_exist():
    assert len(SKILLS) >= 9


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.stem)
def test_skill_has_an_explicit_class_check(path):
    text = path.read_text(encoding="utf-8")
    assert "Data classes used" in text, "scenario skills declare the data classes they need"
    assert "### Class check (MANDATORY" in text
    assert "`MISSING`" in text
    assert "I will not generate it with a generic schema" in text or "I cannot run the" in text


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.stem)
def test_skill_names_no_invented_datasets(path):
    assert not INVENTED_DATASETS.search(path.read_text(encoding="utf-8"))


def test_large_file_exfil_skips_the_saas_stage_when_no_saas_source():
    text = (SCENARIOS / "large_file_upload_exfil.md").read_text(encoding="utf-8")
    assert "Missing `saas`: skip Stage 3 entirely" in text
    assert "I am skipping Stage <N>" in text


def test_dns_skill_accepts_the_firewall_dns_subsystem_and_says_what_it_lacks():
    text = (SCENARIOS / "dns_tunneling_c2.md").read_text(encoding="utf-8")
    assert "FTNTFGTqname" in text and "dns-response" in text
    assert "no FortiGate field" in text
