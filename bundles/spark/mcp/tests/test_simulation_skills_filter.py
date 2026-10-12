"""load_simulation_skills filtering: forgiving, never a silent zero.

Regression for the journey-pass finding: category=scenarios + attack_type=apt +
complexity=medium + keywords="web shell" returned 0 skills although
scenarios/web_app_to_webshell_to_exfil.md ships. Root cause: no shipped skill
declares `attack_type` or `complexity` in its frontmatter, but the filter
compared the empty value against the requested one and dropped every skill.

Runs against the real shipped skills directory so a new skill that breaks the
contract is caught too.
"""
from __future__ import annotations

import asyncio

import pytest

from usecase.builtin_components import simulation_skills as ss


def _run(**kwargs):
    kwargs.setdefault("include_content", False)
    return asyncio.run(ss.load_simulation_skills(**kwargs))


def _ids(result):
    return {s["skill_id"] for s in result["skills"]}


def test_journey_pass_query_finds_the_web_shell_scenario():
    result = _run(
        category="scenarios", attack_type="apt", complexity="medium", keywords="web shell"
    )
    assert "web_app_to_webshell_to_exfil" in _ids(result)
    assert result["summary"]["total_skills"] >= 1


def test_skills_without_the_metadata_are_not_excluded_by_it():
    # No shipped skill declares attack_type/complexity: absence is "no constraint".
    result = _run(category="scenarios", attack_type="apt", complexity="medium")
    assert "web_app_to_webshell_to_exfil" in _ids(result)
    assert result["filters_relaxed"] == []


def test_keywords_match_name_description_and_body(monkeypatch):
    # "webshell" is only a substring of the skill name (web_app_to_webshell_...).
    assert "web_app_to_webshell_to_exfil" in _ids(_run(keywords="webshell"))
    # A phrase present only in a skill body, never in its name or description.
    meta = {
        "plain": {"category": "workflows", "file_path": "workflows/plain.md",
                  "description": "nothing relevant", "keywords": []},
        "other": {"category": "workflows", "file_path": "workflows/other.md",
                  "description": "unrelated", "keywords": []},
    }
    bodies = {
        "workflows/plain.md": "# Plain\n\nStep 3: query the Mailbox audit log.",
        "workflows/other.md": "# Other\n\nNothing here.",
    }
    monkeypatch.setattr(ss, "get_skill_metadata", lambda: meta)
    monkeypatch.setattr(ss, "read_skill_file", lambda p: bodies.get(p))
    result = _run(keywords="mailbox audit")
    assert _ids(result) == {"plain"}
    assert result["filters_relaxed"] == []


def test_keyword_matching_ignores_case_and_separators():
    assert "dns_tunneling_c2" in _ids(_run(keywords="DNS Tunneling"))
    assert "dns_tunneling_c2" in _ids(_run(keywords=["dns-tunneling"]))


def test_keywords_as_comma_string_match_any():
    ids = _ids(_run(keywords="dns tunneling, web shell"))
    assert {"dns_tunneling_c2", "web_app_to_webshell_to_exfil"} <= ids


def test_declared_metadata_that_does_not_match_still_excludes(monkeypatch):
    meta = {
        "a": {"category": "scenarios", "attack_type": "ransomware", "complexity": "low",
              "file_path": "scenarios/a.md", "description": "", "keywords": []},
        "b": {"category": "scenarios", "attack_type": "apt", "complexity": "low",
              "file_path": "scenarios/b.md", "description": "", "keywords": []},
    }
    monkeypatch.setattr(ss, "get_skill_metadata", lambda: meta)
    result = _run(category="scenarios", attack_type="apt")
    assert _ids(result) == {"b"}
    assert result["filters_relaxed"] == []


def test_non_matching_metadata_filters_relax_with_a_note(monkeypatch):
    meta = {
        "a": {"category": "scenarios", "attack_type": "ransomware", "complexity": "low",
              "file_path": "scenarios/a.md", "description": "", "keywords": []},
    }
    monkeypatch.setattr(ss, "get_skill_metadata", lambda: meta)
    result = _run(category="scenarios", attack_type="apt", complexity="high")
    assert _ids(result) == {"a"}
    relaxed = {r["filter"]: r for r in result["filters_relaxed"]}
    assert set(relaxed) == {"attack_type", "complexity"}
    assert relaxed["attack_type"]["value"] == "apt"
    assert relaxed["complexity"]["value"] == "high"
    assert result["summary"]["total_skills"] == 1


def test_unknown_keywords_return_nothing_with_a_hint_not_the_catalog():
    # Keywords are never relaxed into "everything": the old behaviour returned
    # the whole catalog (72 bodies, ~1.1 MB) labelled "nearest skills".
    result = _run(category="scenarios", keywords="zzz-no-such-thing-zzz")
    assert result["skills"] == []
    assert result["summary"]["total_skills"] == 0
    assert result["filters_relaxed"] == []
    assert "zzz-no-such-thing-zzz" in result["hint"]
    assert "skills_read" in result["hint"]
    assert result["hint"] in result["usage_guidance"]


def test_unknown_keywords_with_content_requested_stay_small():
    import json

    result = asyncio.run(ss.load_simulation_skills(keywords="zzqqxx nonexistent"))
    assert result["skills"] == []
    assert len(json.dumps(result)) < 5000


def test_a_filter_that_was_not_the_cause_is_not_reported_as_relaxed():
    # complexity alone matches skills, keywords match nothing: the keywords are
    # the problem and are never dropped, so nothing is relaxed and nothing is
    # returned. (Previously this reported complexity as relaxed.)
    result = _run(category="scenarios", complexity="high", keywords="zzqq")
    assert result["skills"] == []
    assert result["filters_relaxed"] == []
    ms, notes = ss.filter_skills_with_notes(
        category="scenarios", complexity="high", keywords=["zzqq"]
    )
    assert ms == [] and notes == []


def test_only_the_filters_whose_removal_produces_matches_are_reported(monkeypatch):
    meta = {
        "a": {"category": "scenarios", "attack_type": "apt", "complexity": "low",
              "file_path": "scenarios/a.md", "description": "web shell", "keywords": []},
        "b": {"category": "scenarios", "attack_type": "ransomware", "complexity": "high",
              "file_path": "scenarios/b.md", "description": "other", "keywords": []},
    }
    monkeypatch.setattr(ss, "get_skill_metadata", lambda: meta)
    # attack_type=apt is satisfiable on its own and the keyword matches a, so
    # only complexity=high (declared low on a) has to go.
    result = _run(attack_type="apt", complexity="high", keywords="web shell")
    assert _ids(result) == {"a"}
    assert [r["filter"] for r in result["filters_relaxed"]] == ["complexity"]


def test_relaxed_results_are_metadata_only_and_capped(monkeypatch):
    meta = {
        f"s{i:02d}": {"category": "workflows", "complexity": "low",
                      "file_path": f"workflows/s{i:02d}.md",
                      "description": "port scan", "keywords": []}
        for i in range(25)
    }
    monkeypatch.setattr(ss, "get_skill_metadata", lambda: meta)
    monkeypatch.setattr(ss, "read_skill_file", lambda p: "BODY " * 100)
    result = asyncio.run(
        ss.load_simulation_skills(complexity="high", keywords="port scan", include_content=True)
    )
    assert [r["filter"] for r in result["filters_relaxed"]] == ["complexity"]
    assert len(result["skills"]) == ss.RELAXED_RESULT_LIMIT == 10
    assert all("content" not in s for s in result["skills"])
    assert result["summary"]["total_matched"] == 25
    assert any("skills_read" in line for line in result["usage_guidance"])


def test_exact_matches_still_return_content_uncapped(monkeypatch):
    meta = {
        f"s{i:02d}": {"category": "workflows", "file_path": f"workflows/s{i:02d}.md",
                      "description": "port scan", "keywords": []}
        for i in range(12)
    }
    monkeypatch.setattr(ss, "get_skill_metadata", lambda: meta)
    monkeypatch.setattr(ss, "read_skill_file", lambda p: "BODY")
    result = asyncio.run(ss.load_simulation_skills(keywords="port scan"))
    assert len(result["skills"]) == 12
    assert all(s["content"] == "BODY" for s in result["skills"])
    assert result["filters_relaxed"] == []
    assert result["hint"] is None


def test_unknown_category_is_the_last_filter_relaxed():
    result = _run(category="no-such-category")
    assert result["summary"]["total_skills"] > 0
    assert [r["filter"] for r in result["filters_relaxed"]] == ["category"]


def test_caldera_filter_is_a_requirement_not_relaxed(monkeypatch):
    meta = {
        "a": {"category": "scenarios", "caldera_required": True,
              "file_path": "scenarios/a.md", "description": "", "keywords": []},
    }
    monkeypatch.setattr(ss, "get_skill_metadata", lambda: meta)
    result = _run(caldera_available=False)
    assert result["skills"] == []
    assert result["filters_relaxed"] == []


def test_keyword_hits_rank_name_matches_first():
    result = _run(keywords="dns tunneling")
    assert result["skills"][0]["skill_id"] == "dns_tunneling_c2"


def test_applied_filters_are_reported_with_keywords():
    result = _run(category="scenarios", keywords="web shell")
    assert result["summary"]["filters_applied"]["keywords"] == ["web shell"]


def test_usage_guidance_names_only_skills_that_exist():
    import re

    # skills_read (a tool) and include_content (a parameter) are named by the
    # relaxed/empty hints; they are not skills.
    names = set(ss.get_skill_metadata()) | {"skills_read", "include_content"}
    for category in (None, "foundation", "scenarios", "validation", "workflows"):
        for line in _run(category=category)["usage_guidance"]:
            for token in re.findall(r"\b[a-z]+(?:_[a-z0-9]+)+\b", line):
                assert token in names, f"guidance names a skill that does not exist: {token}"
