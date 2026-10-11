"""time_now: the model has no clock, so it gets one it cannot get wrong."""

from __future__ import annotations

import time

from usecase.builtin_components import cognitive_tools
from usecase.connector_loader import _BUILTIN_LEGACY_TOOLS


def test_time_now_returns_utc_fields_close_to_the_real_clock() -> None:
    out = cognitive_tools.time_now()
    assert abs(out["epoch_ms"] - int(time.time() * 1000)) < 5000
    assert out["epoch_s"] == out["epoch_ms"] // 1000 or abs(out["epoch_s"] - out["epoch_ms"] // 1000) <= 1
    assert out["iso"].endswith("Z") and out["iso"][:10] == out["date"]
    assert out["timezone"] == "UTC" and out["weekday"]


def test_time_now_is_registered_as_a_builtin_tool() -> None:
    assert "time_now" in dict(_BUILTIN_LEGACY_TOOLS)


def test_a_model_sending_an_empty_dict_for_keywords_is_not_an_error() -> None:
    from usecase.builtin_components.simulation_skills import _as_keyword_list
    assert _as_keyword_list({}) is None and _as_keyword_list(None) is None and _as_keyword_list([]) is None
    assert _as_keyword_list("okta") == ["okta"] and _as_keyword_list(["a", 1]) == ["a", "1"]
