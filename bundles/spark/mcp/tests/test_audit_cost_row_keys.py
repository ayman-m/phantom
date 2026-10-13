"""The audit store's secret scrub must not rewrite the fields of a cost row.

`SqliteAuditLog._sanitize` replaces a STRING value with "***" when its key
contains a hint such as "token", "session" or "pin". A `chat_turn_cost` row
(written by mcp/agent/lib/cost-rows.ts) has string fields (provider, model_ref,
request_id, finish, ...) and numeric `*_tokens` fields; this pins that none of
the string-valued keys trips the scrub, so the row reads back whole. If a new
string-valued key is added to the cost row, add it here.
"""

from usecase.audit_log import SqliteAuditLog

COST_ROW = {
    "call_kind": "followup",
    "input_tokens": 3100,
    "cached_input_tokens": 1000,
    "output_tokens": 400,
    "uncached_input_tokens": 2100,
    "cache_write_tokens": 2000,
    "cache_write_1h_tokens": 500,
    "reasoning_tokens": 0,
    "priced": True,
    "cost_usd": 0.0123,
    "cost_components": {"cache_write_usd": 0.004},
    "long_context": False,
    "pricing_verified": "2026-10-13",
    "model": "claude-sonnet-5-5",
    "provider": "anthropic",
    "model_ref": "anthropic/claude-sonnet-5-5",
    "unpriced_reason": "unknown_model",
    "request_id": "req_011CUexampleRequestId",
    "finish": "tool_use",
}

CACHE_HIT_ROW = {
    "cached_tokens": 4000,
    "prompt_tokens": 5000,
    "full_price_input_tokens": 1000,
    "savings_tokens_est": 3800,
    "savings_usd_est": 0.0076,
    "model": "claude-sonnet-5-5",
    "provider": "anthropic",
    "model_ref": "anthropic/claude-sonnet-5-5",
}


def test_cost_row_survives_the_secret_scrub():
    assert SqliteAuditLog._sanitize(dict(COST_ROW)) == COST_ROW


def test_cache_hit_row_survives_the_secret_scrub():
    assert SqliteAuditLog._sanitize(dict(CACHE_HIT_ROW)) == CACHE_HIT_ROW
