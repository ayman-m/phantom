"""Bench cost comes from the chat route's `turn_cost` SSE event.

The runner used to read `cost_usd` off the `meta` event, which carries only the
run and session ids, so every bench case scored $0. These pin the parse of the
`turn_cost` event the agent sends, including the unpriced shapes (null cost).
"""

from usecase.benchmark_runner import turn_cost_usd


def test_a_priced_turn_reports_its_cost():
    event = {"cost_usd": 0.0123, "priced": True, "unpriced_calls": 0,
             "provider": "anthropic", "model_ref": "anthropic/claude-sonnet-5-5"}
    assert turn_cost_usd(event) == 0.0123


def test_a_turn_with_no_priced_call_is_unpriced_not_zero():
    # cost_usd is null when every call of the turn was on an unpriced model.
    event = {"cost_usd": None, "priced": False, "unpriced_calls": 2}
    assert turn_cost_usd(event) is None


def test_a_priced_zero_is_a_real_zero():
    assert turn_cost_usd({"cost_usd": 0, "priced": True}) == 0.0
    assert turn_cost_usd({"cost_usd": 0.0}) == 0.0


def test_a_partly_priced_turn_reports_the_priced_part():
    event = {"cost_usd": 0.004, "priced": False, "unpriced_calls": 1}
    assert turn_cost_usd(event) == 0.004


def test_malformed_payloads_are_unpriced():
    for bad in (None, "x", [], {}, {"cost_usd": "0.5"}, {"cost_usd": True},
                {"cost_usd": -1}, {"cost_usd": float("nan")}):
        assert turn_cost_usd(bad) is None


def test_the_meta_event_is_not_a_cost_source():
    import inspect
    from usecase import benchmark_runner

    src = inspect.getsource(benchmark_runner._dispatch_case)
    assert 'event_type == "turn_cost"' in src
    assert 'event_type == "meta"' not in src


# ─── Unpriced cases stay unpriced through the score and the summary ───────────

import json
from datetime import datetime, timezone

from usecase.benchmark import BenchCase, BenchManifest, score_case, summarize


def _case(cid):
    return BenchCase(id=cid, prompt="p", expected_tool_calls=[])


def _score(cid, cost):
    return score_case(_case(cid), "ok", [], cost, 1.0)


def _summary(scores):
    manifest = BenchManifest(id="m", cases=[_case(s.case_id) for s in scores])
    now = datetime.now(timezone.utc).isoformat()
    return summarize("run", manifest, scores, now, now)


def test_an_unpriced_case_scores_null_cost_in_the_json():
    s = _score("a", None)
    assert s.cost_usd is None
    assert s.to_dict()["cost_usd"] is None
    assert json.loads(json.dumps(s.to_dict()))["cost_usd"] is None


def test_a_run_with_no_priced_case_has_null_cost_percentiles():
    summary = _summary([_score("a", None), _score("b", None)])
    assert summary.cost_p50 is None and summary.cost_p95 is None
    d = summary.to_dict()
    assert d["cost_p50"] is None and d["cost_p95"] is None


def test_unpriced_cases_do_not_drag_the_percentiles_toward_zero():
    summary = _summary([_score("a", 0.10), _score("b", None), _score("c", 0.30)])
    assert summary.cost_p50 == 0.20
    assert summary.cost_p95 == 0.29


def test_the_runner_keeps_an_unpriced_turn_unpriced_end_to_end():
    import inspect
    from usecase import benchmark_runner

    src = inspect.getsource(benchmark_runner._dispatch_case)
    assert "cost_usd: float | None = None" in src
    assert "cost_usd = 0.0" not in src
