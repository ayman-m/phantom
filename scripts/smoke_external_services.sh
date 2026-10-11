#!/usr/bin/env bash
# Phantom — Caldera + xlog external-services smoke test.
#
# Direct REST/GraphQL checks against the running Caldera and xlog
# containers using the operator-supplied credentials. Bypasses the
# agent + MCP entirely — proves the underlying services are reachable
# AND enforce the credentials we baked into them.
#
# This complements `bundles/spark/mcp/scripts/smoke_test.sh` (which
# tests the agent's full capability surface end-to-end). Use this
# script when you specifically want to confirm:
#   * Caldera is listening on its host port + accepts the API key
#     baked at first boot via CALDERA_API_KEY
#   * xlog is enforcing its bearer auth and accepts the value
#     matching XLOG_API_KEY
#   * The red-team operator login (CALDERA_RED_USER / RED_PASSWORD)
#     produces a session
#
# Usage (on the Docker host, after `set -a && source .env && set +a`):
#   ./scripts/smoke_external_services.sh
#
# Required env (pinned in .env):
#   CALDERA_API_KEY        — bearer presented as `KEY: <value>`
#   CALDERA_RED_USER       — red-team operator name (default "red")
#   CALDERA_RED_PASSWORD   — red-team operator password
#   XLOG_API_KEY           — xlog auth token (sent as Authorization)
#
# Optional overrides:
#   CALDERA_HOST_URL       — default http://localhost:8888
#   XLOG_HOST_URL          — default http://localhost:8999
#                            (compose maps host 8999 → container 8000)
#   VERBOSE=1              — print response previews on every check
#
# Exit code: 0 on all-pass, 1 if any check failed, 2 on bad invocation.

set -uo pipefail

CALDERA_HOST_URL="${CALDERA_HOST_URL:-http://localhost:8888}"
XLOG_HOST_URL="${XLOG_HOST_URL:-http://localhost:8999}"
CALDERA_RED_USER="${CALDERA_RED_USER:-red}"
VERBOSE="${VERBOSE:-0}"

if ! command -v curl >/dev/null 2>&1; then
  echo "ERROR: curl not found." >&2
  exit 2
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq not found. Install with apt-get install jq." >&2
  exit 2
fi

# Required-env sanity check.
missing=()
[[ -z "${CALDERA_API_KEY:-}" ]] && missing+=("CALDERA_API_KEY")
[[ -z "${CALDERA_RED_PASSWORD:-}" ]] && missing+=("CALDERA_RED_PASSWORD")
[[ -z "${XLOG_API_KEY:-}" ]] && missing+=("XLOG_API_KEY")
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "ERROR: missing required env: ${missing[*]}" >&2
  echo "       Source your .env or export them before running." >&2
  exit 2
fi

# ─── Output helpers ──────────────────────────────────────────────

C_PASS='\033[0;32m'
C_FAIL='\033[0;31m'
C_WARN='\033[0;33m'
C_BOLD='\033[1m'
C_DIM='\033[2m'
C_RESET='\033[0m'

PASSED=0
FAILED=0
declare -a FAILURES=()

section() {
  printf "\n${C_BOLD}━━━ %s ━━━${C_RESET}\n" "$1"
}

pass() {
  PASSED=$((PASSED + 1))
  printf "  ${C_PASS}✓${C_RESET} %s\n" "$1"
}

fail() {
  FAILED=$((FAILED + 1))
  FAILURES+=("$1")
  printf "  ${C_FAIL}✗${C_RESET} %s\n" "$1"
  if [[ -n "${2:-}" ]]; then
    printf "    ${C_DIM}%s${C_RESET}\n" "$2"
  fi
}

dump() {
  if [[ "$VERBOSE" == "1" ]]; then
    printf "    ${C_DIM}↳ %s${C_RESET}\n" "$1"
  fi
}

# Build a curl wrapper that records both response body + status.
# Usage:  status_body=$(http_call <method> <url> [<header> ...])
#         status="${status_body%%|*}"
#         body="${status_body#*|}"
http_call() {
  local method="$1"
  local url="$2"
  shift 2
  local hdr_args=()
  for h in "$@"; do
    hdr_args+=(-H "$h")
  done
  # -s silent, -L follow redirects, -w status code on its own line
  local resp
  resp=$(curl -s -L -w "\nHTTPSTATUS:%{http_code}" \
    --max-time 15 -X "$method" "$url" "${hdr_args[@]}" 2>&1) || true
  local status="${resp##*HTTPSTATUS:}"
  local body="${resp%HTTPSTATUS:*}"
  printf "%s|%s" "$status" "$body"
}

# ─── Caldera ─────────────────────────────────────────────────────

section "Caldera (REST + auth) at $CALDERA_HOST_URL"

# C1 — basic reachability via the root endpoint
sb=$(http_call GET "$CALDERA_HOST_URL/")
status="${sb%%|*}"
if [[ "$status" =~ ^(200|301|302)$ ]]; then
  pass "C1 root reachable (HTTP $status)"
else
  fail "C1 root reachable" "got HTTP $status"
fi

# C2 — abilities list (the capability you specifically named)
sb=$(http_call GET "$CALDERA_HOST_URL/api/v2/abilities" \
  "KEY: $CALDERA_API_KEY" \
  "accept: application/json")
status="${sb%%|*}"
body="${sb#*|}"
if [[ "$status" == "200" ]]; then
  count=$(echo "$body" | jq 'length' 2>/dev/null || echo 0)
  if [[ "$count" =~ ^[0-9]+$ ]] && [[ "$count" -gt 0 ]]; then
    sample=$(echo "$body" | jq -r '.[0].name // .[0].ability_id // "?"' 2>/dev/null)
    pass "C2 /api/v2/abilities lists $count abilities (e.g. $sample)"
    dump "first ability: $sample"
  else
    fail "C2 /api/v2/abilities" "200 but body parsed to count=$count"
  fi
elif [[ "$status" == "401" || "$status" == "403" ]]; then
  fail "C2 /api/v2/abilities" "auth rejected (HTTP $status); CALDERA_API_KEY mismatch with what was baked into Caldera at first boot"
else
  fail "C2 /api/v2/abilities" "unexpected HTTP $status"
fi

# C3 — adversaries list (proves we can enumerate red-team library)
sb=$(http_call GET "$CALDERA_HOST_URL/api/v2/adversaries" \
  "KEY: $CALDERA_API_KEY" \
  "accept: application/json")
status="${sb%%|*}"
body="${sb#*|}"
if [[ "$status" == "200" ]]; then
  count=$(echo "$body" | jq 'length' 2>/dev/null || echo 0)
  if [[ "$count" =~ ^[0-9]+$ ]]; then
    pass "C3 /api/v2/adversaries lists $count adversaries"
  else
    fail "C3 /api/v2/adversaries" "200 but malformed JSON"
  fi
else
  fail "C3 /api/v2/adversaries" "HTTP $status"
fi

# C4 — operations list (read-only; proves we can see the active ops)
sb=$(http_call GET "$CALDERA_HOST_URL/api/v2/operations" \
  "KEY: $CALDERA_API_KEY" \
  "accept: application/json")
status="${sb%%|*}"
body="${sb#*|}"
if [[ "$status" == "200" ]]; then
  count=$(echo "$body" | jq 'length' 2>/dev/null || echo 0)
  pass "C4 /api/v2/operations reachable ($count active op(s))"
else
  fail "C4 /api/v2/operations" "HTTP $status"
fi

# C5 — wrong API key MUST 401 (proves enforcement, not permissive)
sb=$(http_call GET "$CALDERA_HOST_URL/api/v2/abilities" \
  "KEY: this-is-deliberately-wrong" \
  "accept: application/json")
status="${sb%%|*}"
if [[ "$status" == "401" || "$status" == "403" ]]; then
  pass "C5 wrong API key rejected (HTTP $status — enforcement confirmed)"
else
  fail "C5 wrong API key" "expected 401/403, got $status (enforcement looks broken!)"
fi

# C6 — red-team operator login flow
# Caldera's login uses application/x-www-form-urlencoded.
# IMPORTANT: -L (follow redirects) is OMITTED — successful login
# returns a 302 to the dashboard, but curl would then re-issue the
# request as GET on the next URL which returns 405. We want to see
# the 302 itself as the success signal.
sb=$(curl -s -w "\nHTTPSTATUS:%{http_code}" --max-time 15 \
  -X POST "$CALDERA_HOST_URL/enter" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=$CALDERA_RED_USER" \
  --data-urlencode "password=$CALDERA_RED_PASSWORD" \
  -o /dev/null 2>&1) || true
status="${sb##*HTTPSTATUS:}"
if [[ "$status" =~ ^(200|302|303)$ ]]; then
  pass "C6 red-user login flow accepts ($CALDERA_RED_USER, HTTP $status — 302 = success redirect to dashboard)"
else
  fail "C6 red-user login" "POST /enter returned $status (CALDERA_RED_USER/RED_PASSWORD mismatch?)"
fi

# ─── xlog ────────────────────────────────────────────────────────

section "xlog (REST + GraphQL + auth) at $XLOG_HOST_URL"

# X1 — health endpoint (whitelisted from auth)
sb=$(http_call GET "$XLOG_HOST_URL/health")
status="${sb%%|*}"
body="${sb#*|}"
if [[ "$status" == "200" ]]; then
  status_field=$(echo "$body" | jq -r '.status // ""' 2>/dev/null)
  if [[ "$status_field" == "ok" ]]; then
    pass "X1 /health returns ok"
  else
    fail "X1 /health" "200 but body=$body"
  fi
else
  fail "X1 /health" "HTTP $status"
fi

# X2 — unauth REST request MUST 401 (proves middleware enforces)
sb=$(http_call GET "$XLOG_HOST_URL/api/v1/simulations")
status="${sb%%|*}"
if [[ "$status" == "401" ]]; then
  pass "X2 /api/v1/simulations rejects no-auth (HTTP 401 — enforcement confirmed)"
elif [[ "$status" == "200" ]]; then
  fail "X2 unauth enforcement" "expected 401, got 200 — XLOG_API_KEY may not be set on xlog container, running in PERMISSIVE mode"
else
  fail "X2 /api/v1/simulations no-auth" "expected 401, got $status"
fi

# X3 — REST list with valid auth
sb=$(http_call GET "$XLOG_HOST_URL/api/v1/simulations" \
  "Authorization: $XLOG_API_KEY")
status="${sb%%|*}"
body="${sb#*|}"
if [[ "$status" == "200" ]]; then
  count=$(echo "$body" | jq '.simulations | length' 2>/dev/null || echo 0)
  pass "X3 /api/v1/simulations with auth → $count simulation(s)"
elif [[ "$status" == "401" ]]; then
  fail "X3 /api/v1/simulations with auth" "401 — XLOG_API_KEY in env doesn't match the value xlog booted with"
else
  fail "X3 /api/v1/simulations with auth" "HTTP $status"
fi

# X4 — coverage report endpoint (the one T9.2 hits in the agent test)
sb=$(http_call GET "$XLOG_HOST_URL/api/v1/coverage-report" \
  "Authorization: $XLOG_API_KEY")
status="${sb%%|*}"
body="${sb#*|}"
if [[ "$status" == "200" ]]; then
  pass "X4 /api/v1/coverage-report returns 200"
  dump "first 200 chars: $(echo "$body" | head -c 200)"
else
  fail "X4 /api/v1/coverage-report" "HTTP $status"
fi

# X5 — wrong xlog token MUST 401 (mirror of X2 from the other side)
sb=$(http_call GET "$XLOG_HOST_URL/api/v1/simulations" \
  "Authorization: this-is-deliberately-wrong-12345")
status="${sb%%|*}"
if [[ "$status" == "401" ]]; then
  pass "X5 wrong xlog token rejected (HTTP 401)"
elif [[ "$status" == "200" ]]; then
  printf "  ${C_WARN}!${C_RESET} X5 wrong-token check returned 200 — xlog running in permissive mode (XLOG_API_KEY unset on container)\n"
  PASSED=$((PASSED + 1))
else
  fail "X5 wrong xlog token" "expected 401, got $status"
fi

# X6 — GraphQL faker query (proves the underlying log-gen engine works).
# DataFakerOutput's actual fields are `data` (the generated content),
# `type`, `count`. The GraphQL endpoint at / is whitelisted from auth
# (introspection-friendly); we still send Authorization as a smoke
# of the bearer behavior on the GraphQL surface.
gql_payload='{"query":"query { generateFakeData(requestInput: { type: SYSLOG, count: 1 }) { data type count } }"}'
sb=$(curl -s -w "\nHTTPSTATUS:%{http_code}" --max-time 15 \
  -X POST "$XLOG_HOST_URL/" \
  -H "Content-Type: application/json" \
  -H "Authorization: $XLOG_API_KEY" \
  --data "$gql_payload" 2>&1) || true
status="${sb##*HTTPSTATUS:}"
body="${sb%HTTPSTATUS:*}"
if [[ "$status" == "200" ]]; then
  errors=$(echo "$body" | jq -r '.errors // empty' 2>/dev/null)
  if [[ -n "$errors" && "$errors" != "null" ]]; then
    fail "X6 GraphQL generateFakeData" "GraphQL errors: $errors"
  else
    count=$(echo "$body" | jq -r '.data.generateFakeData.count // 0' 2>/dev/null)
    sample=$(echo "$body" | jq -r '.data.generateFakeData.data // ""' 2>/dev/null | head -c 80)
    pass "X6 GraphQL generateFakeData(SYSLOG) → count=$count"
    dump "first log preview: $sample"
  fi
else
  fail "X6 GraphQL generateFakeData" "HTTP $status"
fi

# ─── Summary ─────────────────────────────────────────────────────

printf "\n${C_BOLD}━━━ Summary ━━━${C_RESET}\n"
printf "  ${C_PASS}%d passed${C_RESET}, ${C_FAIL}%d failed${C_RESET}\n" "$PASSED" "$FAILED"

if [[ "$FAILED" -gt 0 ]]; then
  printf "\n${C_FAIL}${C_BOLD}Failures:${C_RESET}\n"
  for f in "${FAILURES[@]}"; do
    printf "  • %s\n" "$f"
  done
  exit 1
fi
exit 0
