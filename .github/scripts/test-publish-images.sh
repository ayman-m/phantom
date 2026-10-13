#!/usr/bin/env bash
# Tests for publish-images.sh, run against a stub `docker` so no registry is touched.
# The stub keeps one file per image reference (its digest) in $STUB_DIR and logs every write.
# Needs only bash; works with bash 3.2 (macOS) and 5.x (the GitHub-hosted runner).
# ok/bad never fail, so `A && ok || bad` is a safe if-then-else here.
# shellcheck disable=SC2015,SC2016
set -u

# The workflow exports TAG, BASE_TAG and friends for the real run; the tests set their own.
unset TAG BASE_TAG AGENT_DIGEST GITHUB_REPOSITORY GITHUB_REF GITHUB_SHA GITHUB_STEP_SUMMARY

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/publish-images.sh"
export SCRIPT RETRY_SLEEP=0

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"

cat > "$WORK/bin/docker" <<'STUB'
#!/usr/bin/env bash
# Stub for: docker buildx imagetools inspect REF --format ...   and   docker buildx imagetools create -t DEST SRC
key() { printf '%s' "$1" | tr '/:@' '___'; }
[ "$1" = buildx ] && [ "$2" = imagetools ] || { echo "stub: unexpected: $*" >&2; exit 99; }
case "$3" in
  inspect)
    ref="$4"
    if [ -n "${STUB_ERROR_REF:-}" ] && [ "$ref" = "$STUB_ERROR_REF" ]; then
      echo "ERROR: failed to authorize: unauthorized: authentication required" >&2; exit 1
    fi
    f="$STUB_DIR/$(key "$ref")"
    if [ -f "$f" ]; then cat "$f"; exit 0; fi
    echo "ERROR: $ref: not found" >&2; exit 1 ;;
  create)
    [ "$4" = -t ] && [ "$#" -eq 6 ] || { echo "stub: create must be exactly: -t DEST SRC (got: $*)" >&2; exit 98; }
    dest="$5"; src="$6"
    echo "create $dest <- $src" >> "$STUB_DIR/calls.log"
    f="$STUB_DIR/$(key "$src")"
    [ -f "$f" ] || { echo "ERROR: $src: not found" >&2; exit 1; }
    if [ -n "${STUB_MUTATE_DEST:-}" ] && [ "$dest" = "$STUB_MUTATE_DEST" ]; then
      echo "sha256:bad" > "$STUB_DIR/$(key "$dest")"
    else
      cp "$f" "$STUB_DIR/$(key "$dest")"
    fi
    exit 0 ;;
  *) echo "stub: unexpected: $*" >&2; exit 97 ;;
esac
STUB
chmod +x "$WORK/bin/docker"
export PATH="$WORK/bin:$PATH"

R=ghcr.io/ayman-m
PKGS="phantom-agent-oss phantom-xlog-oss phantom-caldera-oss phantom-updater-oss phantom-browser-oss phantom-connector-runtime-oss phantom-connector-xlog-oss phantom-connector-xsiam-oss phantom-connector-caldera-oss phantom-connector-web-oss phantom-connector-cortex-docs-oss phantom-connector-cortex-content-oss phantom-connector-cortex-xdr-oss phantom-connector-http-sender-oss phantom-connector-wec-sender-oss"

PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); }
bad()  { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }
expect_ok()   { local name="$1"; shift; if "$@" >"$WORK/out" 2>&1; then ok; else bad "$name (expected success)"; sed 's/^/    /' "$WORK/out"; fi; }
# A failure only counts when the guard itself raised it (its ::error:: marker), not a crash or a typo.
expect_fail() { local name="$1"; shift; if "$@" >"$WORK/out" 2>&1; then bad "$name (expected failure)"; elif grep -q '^::error::' "$WORK/out"; then ok; else bad "$name (failed, but not through a guard)"; sed 's/^/    /' "$WORK/out"; fi; }

key() { printf '%s' "$1" | tr '/:@' '___'; }
put() { printf '%s\n' "$2" > "$STUB_DIR/$(key "$1")"; }

# Fresh registry: every package has 1.0.3, latest and 1.0, each with its own digest; nothing else.
new_registry() {
  STUB_DIR="$WORK/reg$1"; rm -rf "$STUB_DIR"; mkdir -p "$STUB_DIR"; export STUB_DIR
  unset STUB_ERROR_REF STUB_MUTATE_DEST
  local p n=0
  for p in $PKGS; do
    n=$((n + 1))
    put "$R/$p:1.0.3" "sha256:base$n"
    put "$R/$p:latest" "sha256:latest$n"
    put "$R/$p:1.0"    "sha256:minor$n"
  done
  : > "$STUB_DIR/calls.log"
}

run() { # run <subcommand> [args] with the standard environment
  TAG="${TAG-1.0.4}" BASE_TAG="${BASE_TAG-1.0.3}" GITHUB_REPOSITORY="${GITHUB_REPOSITORY-ayman-m/phantom}" \
  GITHUB_REF="${GITHUB_REF-refs/heads/main}" bash "$SCRIPT" "$@"
}
with() { # with VAR=value ... -- command   (scoped env override)
  local e=(); while [ "$1" != -- ]; do e+=("$1"); shift; done; shift; env "${e[@]}" "$@"
}

echo "== validate"
expect_ok   "validate final tag"        with TAG=1.0.4 -- bash -c "$(declare -f run); run validate"
expect_ok   "validate rc tag"           with TAG=1.0.4-rc1 -- bash -c "$(declare -f run); run validate"
expect_ok   "validate rc10"             with TAG=12.34.56-rc10 -- bash -c "$(declare -f run); run validate"
for t in latest 1.0 v1.0.4 1.0.4-rc 1.0.4-beta1 1.0.4-rc1-x "1.0.4 " "1.0.4;id" '$(id)' "" 01.0 1.0.4.5 " 1.0.4"; do
  expect_fail "validate rejects tag '$t'" with "TAG=$t" -- bash -c "$(declare -f run); run validate"
done
for b in latest 1.0 1.0.3-rc1 v1.0.3 ""; do
  expect_fail "validate rejects base_tag '$b'" with "BASE_TAG=$b" -- bash -c "$(declare -f run); run validate"
done
expect_fail "validate rejects tag == base_tag"  with TAG=1.0.3 -- bash -c "$(declare -f run); run validate"
expect_fail "validate rejects other repository" with GITHUB_REPOSITORY=someone/phantom -- bash -c "$(declare -f run); run validate"
expect_fail "validate rejects non-main ref"     with GITHUB_REF=refs/heads/feature -- bash -c "$(declare -f run); run validate"
expect_fail "validate rejects tag ref"          with GITHUB_REF=refs/tags/v1.0.4 -- bash -c "$(declare -f run); run validate"

echo "== preflight"
new_registry 1
expect_ok "preflight clean registry" run preflight "$WORK/before1"
n=$(wc -l < "$WORK/before1" | tr -d ' ')
[ "$n" = 45 ] && ok || bad "snapshot should hold 15 packages x 3 refs (base, latest, X.Y) = 45 lines, got $n"
grep -q "^phantom-xlog-oss	$R/phantom-xlog-oss:latest	sha256:latest2$" "$WORK/before1" && ok || bad "snapshot records the latest digest"
[ ! -s "$STUB_DIR/calls.log" ] && ok || bad "preflight must not write"
TAG=1.1.0 run preflight "$WORK/before1b" >/dev/null 2>&1
n=$(wc -l < "$WORK/before1b" | tr -d ' ')
[ "$n" = 60 ] && ok || bad "when X.Y of tag differs from X.Y of base_tag, both are snapshotted (60 lines), got $n"

new_registry 2
put "$R/phantom-connector-web-oss:1.0.4" "sha256:existing"
expect_fail "preflight refuses an existing final tag on any package" run preflight "$WORK/before2"
grep -q "phantom-connector-web-oss" "$WORK/out" && ok || bad "refusal names the package"

new_registry 3; put "$R/phantom-connector-web-oss:1.0.4-rc1" "sha256:old"
expect_ok "preflight allows re-publishing an existing rc tag" with TAG=1.0.4-rc1 -- bash -c "$(declare -f run); run preflight $WORK/before3"

new_registry 4; rm "$STUB_DIR/$(key "$R/phantom-updater-oss:1.0.3")"
expect_fail "preflight refuses when base_tag is missing for a package" run preflight "$WORK/before4"

new_registry 5; rm "$STUB_DIR/$(key "$R/phantom-xlog-oss:latest")" "$STUB_DIR/$(key "$R/phantom-xlog-oss:1.0")"
expect_ok "preflight accepts packages without latest or X.Y" run preflight "$WORK/before5"
grep -q "^phantom-xlog-oss	$R/phantom-xlog-oss:latest	ABSENT$" "$WORK/before5" && ok || bad "absent latest recorded as ABSENT"

new_registry 6; export STUB_ERROR_REF="$R/phantom-xlog-oss:1.0.4"
expect_fail "preflight fails closed on a non-not-found registry error" run preflight "$WORK/before6"
new_registry 7; export STUB_ERROR_REF="$R/phantom-xlog-oss:latest"
expect_fail "snapshot fails closed on a registry error for latest" run preflight "$WORK/before7"
unset STUB_ERROR_REF

echo "== retag"
new_registry 8
run preflight "$WORK/before8" >/dev/null 2>&1
expect_ok "retag" run retag
c=$(wc -l < "$STUB_DIR/calls.log" | tr -d ' ')
[ "$c" = 14 ] && ok || bad "retag should make exactly 14 create calls, got $c"
grep -q "phantom-agent-oss" "$STUB_DIR/calls.log" && bad "retag must not touch the agent image" || ok
grep -E -q "(:latest|:1\.0) <-|<- .*(:latest|:1\.0)$" "$STUB_DIR/calls.log" && bad "retag wrote or read latest / X.Y" || ok
grep -q "create $R/phantom-xlog-oss:1.0.4 <- $R/phantom-xlog-oss:1.0.3" "$STUB_DIR/calls.log" && ok || bad "retag source/destination"
[ "$(cat "$STUB_DIR/$(key "$R/phantom-xlog-oss:1.0.4")")" = sha256:base2 ] && ok || bad "retagged digest equals the base digest"

new_registry 9
export STUB_MUTATE_DEST="$R/phantom-connector-cortex-xdr-oss:1.0.4"
expect_fail "retag fails when the new tag's digest differs from base_tag's" run retag
unset STUB_MUTATE_DEST

echo "== verify"
new_registry 10
run preflight "$WORK/before10" >/dev/null 2>&1
run retag >/dev/null 2>&1
put "$R/phantom-agent-oss:1.0.4" "sha256:newagent"   # what the build step pushed
SUM="$WORK/summary10"; : > "$SUM"
expect_ok "verify happy path" with AGENT_DIGEST=sha256:newagent "GITHUB_STEP_SUMMARY=$SUM" -- bash -c "$(declare -f run); run verify $WORK/before10"
rows=$(grep -c 'ghcr.io/ayman-m/phantom-.*-oss@sha256:' "$SUM" | tr -d ' ')
[ "$rows" = 15 ] && ok || bad "summary should list 15 digest rows, got $rows"
grep -q "sha256:newagent" "$SUM" && ok || bad "summary lists the agent digest"

put "$R/phantom-xlog-oss:latest" "sha256:MOVED"
expect_fail "verify detects a moved latest" with AGENT_DIGEST=sha256:newagent -- bash -c "$(declare -f run); run verify $WORK/before10"
grep -q "phantom-xlog-oss:latest" "$WORK/out" && ok || bad "verify names the moved ref"
put "$R/phantom-xlog-oss:latest" "sha256:latest2"

put "$R/phantom-xlog-oss:1.0" "sha256:MOVED"
expect_fail "verify detects a moved X.Y" with AGENT_DIGEST=sha256:newagent -- bash -c "$(declare -f run); run verify $WORK/before10"
put "$R/phantom-xlog-oss:1.0" "sha256:minor2"

put "$R/phantom-xlog-oss:1.0.3" "sha256:MOVED"
expect_fail "verify detects a moved base_tag" with AGENT_DIGEST=sha256:newagent -- bash -c "$(declare -f run); run verify $WORK/before10"
put "$R/phantom-xlog-oss:1.0.3" "sha256:base2"

expect_fail "verify detects an agent digest that differs from the build output" with AGENT_DIGEST=sha256:other -- bash -c "$(declare -f run); run verify $WORK/before10"
expect_fail "verify requires AGENT_DIGEST" with AGENT_DIGEST= -- bash -c "$(declare -f run); run verify $WORK/before10"

new_registry 11
run preflight "$WORK/before11" >/dev/null 2>&1
put "$R/phantom-agent-oss:1.0.4" "sha256:newagent"
run retag >/dev/null 2>&1
put "$R/phantom-xlog-oss:1.0.4" "sha256:tampered"
expect_fail "verify detects a retag that no longer equals base_tag" with AGENT_DIGEST=sha256:newagent -- bash -c "$(declare -f run); run verify $WORK/before11"

new_registry 12
run preflight "$WORK/before12" >/dev/null 2>&1
put "$R/phantom-agent-oss:1.0.4" "sha256:newagent"
run retag >/dev/null 2>&1
rm "$STUB_DIR/$(key "$R/phantom-xlog-oss:1.0")"
expect_fail "verify detects an X.Y tag that disappeared" with AGENT_DIGEST=sha256:newagent -- bash -c "$(declare -f run); run verify $WORK/before12"

echo "== unknown subcommand"
expect_fail "unknown subcommand" run frobnicate

echo
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ]
