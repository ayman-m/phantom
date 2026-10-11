"""cortex-docs on GitBook: the tools against saved replies from the live site (no network).

The documentation moved from Fluid Topics (retired, every call failed) to GitBook. These tests pin what the connector
needs from the new site: the `?ask=` reply shape, the per-book sitemap, and the page Markdown with its boilerplate."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

import src.connector as c
import src.gitbook as g

FIX = Path(__file__).resolve().parent / "fixtures"
HOST = "https://cortex-docs.paloaltonetworks.com"


def fake_get(url: str, accept: str = "text/markdown", timeout: int = 30) -> str:
    if url.endswith("/sitemap-pages.xml"):
        return (FIX / "sitemap_xsiam.xml").read_text()
    if "?ask=" in url:
        return (FIX / "ask_cribl.md").read_text()
    if url.endswith(".md"):
        return (FIX / "page.md").read_text()
    raise g.DocsError("the docs site answered HTTP 404 for " + url)


@pytest.fixture(autouse=True)
def docs():
    g._SITEMAPS.clear()
    with mock.patch.object(g, "get", side_effect=fake_get) as m:
        yield m


def test_search_returns_the_answer_the_sources_and_the_follow_ups(docs) -> None:
    out = c.cortex_search("How do I send logs to Cortex XSIAM from Cribl?")
    assert out["ok"] and out["product"] == "xsiam" and out["book"] == "cortex-xsiam"
    assert "Save & generate token" in out["answer"] and "Suggested Follow-up" not in out["answer"] and "# Sources" not in out["answer"]
    assert out["follow_ups"][0] == "What sources need separate Cribl collectors?"
    assert [h["title"] for h in out["hits"]] == ["Ingest data from Cribl", "Collect Windows Event Logs for Cortex XSIAM via Cribl"]
    assert all(h["reader_url"].startswith(HOST) and not h["reader_url"].endswith(".md") for h in out["hits"])
    assert out["total_hits"] == 2
    asked = [call.args[0] for call in docs.call_args_list if "?ask=" in call.args[0]][0]
    assert asked.startswith(HOST + "/cortex-xsiam/learn-about-cortex-xsiam/get-started-cortex-xsiam.md?ask=")  # a content page, not the book root


def test_the_product_comes_from_the_question_or_the_argument() -> None:
    assert g.product_key(None, "How does Cortex XDR isolate an endpoint?") == "xdr"
    assert g.product_key(None, "what is an AgentiX playbook") == "agentix"
    assert g.product_key("xsoar", "anything") == "xsoar"
    assert g.product_key("nonsense", "no product named") == "xsiam"


def test_per_page_caps_the_hits() -> None:
    assert len(c.cortex_search("cribl", per_page=1)["hits"]) == 1


def test_a_docs_outage_is_a_returned_error_not_an_exception(docs) -> None:
    docs.side_effect = g.DocsError("could not reach the docs site (timed out)")
    out = c.cortex_search("anything")
    assert out == {"ok": False, "error": "could not reach the docs site (timed out)"}
    assert c.cortex_fetch_topic(HOST + "/x")["ok"] is False and c.cortex_fetch_toc("xsiam")["ok"] is False


def test_fetch_topic_cleans_the_page_and_only_reads_the_docs_host() -> None:
    page = c.cortex_fetch_topic(HOST + "/cortex-xsiam/some/page.md")
    assert page["ok"] and page["title"] == "Ingest data from Cribl" and page["reader_url"] == HOST + "/cortex-xsiam/some/page"
    assert "For the complete documentation index" not in page["content"] and "{%" not in page["content"]
    assert "published with GitBook" not in page["content"]
    assert f"]({HOST}/cortex-xsiam/configure-cortex-xsiam/cribl)" in page["content"]  # root-relative links made absolute
    assert c.cortex_fetch_topic("/cortex-xsiam/some/page")["ok"]  # a bare path is the same host
    for evil in ("https://evil.example/x", "http://cortex-docs.paloaltonetworks.com/x", "https://cortex-docs.paloaltonetworks.com.evil.example/x"):
        refused = c.cortex_fetch_topic(evil)
        assert refused["ok"] is False and "only pages on" in refused["error"]


def test_fetch_topic_truncates_and_says_so() -> None:
    page = c.cortex_fetch_topic(HOST + "/cortex-xsiam/p", max_chars=500)
    assert page["truncated"] is False  # the fixture page is short
    long_md = "# T\n\n" + "word " * 1000
    with mock.patch.object(g, "get", return_value=long_md):
        cut = c.cortex_fetch_topic(HOST + "/cortex-xsiam/p", max_chars=600)
    assert cut["truncated"] is True and len(cut["content"]) == 600 and cut["total_chars"] > 600


def test_fetch_toc_lists_the_book_with_depth() -> None:
    toc = c.cortex_fetch_toc("xsiam")
    assert toc["ok"] and toc["book"] == "cortex-xsiam" and toc["total_pages"] == 4 and toc["truncated"] is False
    assert toc["items"][0] == {"title": "Cortex xsiam", "reader_url": HOST + "/cortex-xsiam", "depth": 0}
    assert max(i["depth"] for i in toc["items"]) >= 5
    assert c.cortex_fetch_toc(HOST + "/cortex-xsiam/learn-about-cortex-xsiam", max_items=2)["truncated"] is True


def test_suggest_matches_every_typed_word_against_the_page_address() -> None:
    out = c.cortex_suggest("ingest cribl")
    assert out["ok"] and out["suggestions"] == ["Ingest data from cribl"]
    assert c.cortex_suggest("zzzz")["suggestions"] == [] and c.cortex_suggest("")["suggestions"] == []


def test_xql_lookup_cleans_the_term_and_returns_the_docs_answer(docs) -> None:
    out = c.cortex_xql_lookup("XQL stage dedup")
    assert out["ok"] and out["found"] and out["term"] == "dedup" and out["publication"] == "cortex-xsiam"
    assert out["summary_content"] and out["reader_url"].startswith(HOST)
    asked = [call.args[0] for call in docs.call_args_list if "?ask=" in call.args[0]][0]
    assert "dedup" in asked and "goal=write+a+correct+XQL+query" in asked
    assert c.cortex_xql_lookup("   ")["ok"] is False


def test_deep_research_follows_the_suggested_questions_and_collects_citations() -> None:
    out = c.cortex_deep_research("How XSIAM ingests data from Cribl")  # default is 3 questions
    brief = out["brief"]
    assert out["ok"] and brief["coverage"] == {"sections": 3, "answered": 3}
    assert brief["sections"][0]["question"] == "How XSIAM ingests data from Cribl"
    assert brief["sections"][1]["question"] == "What sources need separate Cribl collectors?"
    assert len(brief["citations"]) == 2 and brief["stats"]["requests"] == 3


def test_deep_research_keeps_what_it_has_when_the_site_fails_midway(docs) -> None:
    calls = {"n": 0}

    def flaky(url: str, accept: str = "text/markdown", timeout: int = 30) -> str:
        if "?ask=" in url:
            calls["n"] += 1
            if calls["n"] > 1:
                raise g.DocsError("the docs site answered HTTP 503 for " + url)
        return fake_get(url, accept, timeout)

    docs.side_effect = flaky
    out = c.cortex_deep_research("topic", max_sections=4)
    assert out["ok"] and out["partial"] and len(out["brief"]["sections"]) == 1 and "503" in out["warning"]


def test_questions_are_sanitised_before_they_reach_the_site(docs) -> None:
    """A question with backticks and parentheses got an instant 403 from the site's edge; it is sent without them."""
    g.ask("What does the stage `dedup` (XQL) do?", "xql")
    asked = [call.args[0] for call in docs.call_args_list if "?ask=" in call.args[0]][-1]
    assert "%60" not in asked and "%28" not in asked and "dedup" in asked
    assert g._plain("a" * 500) == "a" * 300 and g._plain("x  \n y") == "x y"


def test_a_question_gets_the_long_timeout_and_a_page_the_short_one(docs) -> None:
    g.ask("anything", "xsiam")
    g.fetch(HOST + "/cortex-xsiam/p")
    timeouts = [(("?ask=" in call.args[0]), call.kwargs.get("timeout")) for call in docs.call_args_list if call.args[0].endswith(".md") or "?ask=" in call.args[0]]
    assert (True, g.ASK_TIMEOUT) in timeouts


def test_unresolved_links_are_removed_from_answers() -> None:
    md = "See [Broken mention](broken://spaces/AEIj/pages/Yr) and the [Broken mention](broken://spaces/AEIj/pages/8Q) for details."
    assert g.clean(md) == "See and the for details."


def test_deep_research_stops_starting_questions_after_its_time_budget() -> None:
    with mock.patch.object(c, "RESEARCH_BUDGET_SECONDS", -1):
        out = c.cortex_deep_research("topic", max_sections=5)
    assert out["ok"] and out["partial"] and len(out["brief"]["sections"]) == 1 and "time budget" in out["warning"]


def test_the_answer_does_not_repeat_the_question_as_a_heading() -> None:
    assert not c.cortex_search("anything")["answer"].startswith("#")
