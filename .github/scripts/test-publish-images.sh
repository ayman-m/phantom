#!/usr/bin/env bash
# Tests for publish-images.sh, run against a stub `docker` and a scratch git repository so no registry is touched.
# The stub keeps one file per image reference (its digest) in $STUB_DIR and logs every write and every `docker run`.
# Needs only bash and git; works with bash 3.2 (macOS) and 5.x (the GitHub-hosted runner).
# ok/bad never fail, so `A && ok || bad` is a safe if-then-else here.
# shellcheck disable=SC2015,SC2016
set -u

# The workflow exports TAG, BASE_TAG and friends for the real run; the tests set their own.
unset TAG BASE_TAG REBUILD RETAG_LIST BUILT_LIST GITHUB_REPOSITORY GITHUB_REF GITHUB_SHA GITHUB_STEP_SUMMARY GITHUB_OUTPUT

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
SCRIPT="$HERE/publish-images.sh"
export SCRIPT REPO_ROOT RETRY_SLEEP=0

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"

cat > "$WORK/bin/docker" <<'STUB'
#!/usr/bin/env bash
# Stub for: docker buildx imagetools inspect REF --format ...,  docker buildx imagetools create -t DEST SRC,
# and docker run --rm --entrypoint python IMAGE -c CODE
key() { printf '%s' "$1" | tr '/:@' '___'; }
if [ "$1" = run ]; then
  [ "$2" = --rm ] && [ "$3" = --entrypoint ] && [ "$4" = python ] && [ "$6" = -c ] || { echo "stub: unexpected run: $*" >&2; exit 96; }
  printf 'run %s\n' "$5" >> "$STUB_DIR/runs.log"; printf '%s\n' "$7" >> "$STUB_DIR/run-code.log"
  [ -z "${STUB_SMOKE_FAIL:-}" ] || { echo "ModuleNotFoundError: No module named 'runtime.organization_reader'" >&2; exit 1; }
  exit 0
fi
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
    # Must be a carbon copy: --prefer-index=false, then -t DEST SRC (the default would wrap a bare manifest in an index)
    [ "$4" = --prefer-index=false ] && [ "$5" = -t ] && [ "$#" -eq 7 ] || { echo "stub: create must be exactly: --prefer-index=false -t DEST SRC (got: $*)" >&2; exit 98; }
    dest="$6"; src="$7"
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
RT=phantom-connector-runtime-oss
CONNECTOR_PKGS="phantom-connector-xlog-oss phantom-connector-xsiam-oss phantom-connector-caldera-oss phantom-connector-web-oss phantom-connector-cortex-docs-oss phantom-connector-cortex-content-oss phantom-connector-cortex-xdr-oss phantom-connector-http-sender-oss phantom-connector-wec-sender-oss"
PKGS="phantom-agent-oss phantom-xlog-oss phantom-caldera-oss phantom-updater-oss phantom-browser-oss $RT $CONNECTOR_PKGS"

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
  unset STUB_ERROR_REF STUB_MUTATE_DEST STUB_SMOKE_FAIL
  local p n=0
  for p in $PKGS; do
    n=$((n + 1))
    put "$R/$p:1.0.3" "sha256:base$n"
    put "$R/$p:latest" "sha256:latest$n"
    put "$R/$p:1.0"    "sha256:minor$n"
  done
  : > "$STUB_DIR/calls.log"; : > "$STUB_DIR/runs.log"; : > "$STUB_DIR/run-code.log"
}

run() { # run <subcommand> [args] with the standard environment
  TAG="${TAG-1.0.4}" BASE_TAG="${BASE_TAG-1.0.3}" GITHUB_REPOSITORY="${GITHUB_REPOSITORY-ayman-m/phantom}" \
  GITHUB_REF="${GITHUB_REF-refs/heads/main}" bash "$SCRIPT" "$@"
}
with() { # with VAR=value ... -- command   (scoped env override)
  local e=(); while [ "$1" != -- ]; do e+=("$1"); shift; done; shift; env "${e[@]}" "$@"
}

# A scratch checkout shaped like the repository's build contexts, tagged v1.0.3, for the plan tests.
SCRATCH="$WORK/repo"
mk_repo() {
  rm -rf "$SCRATCH"; mkdir -p "$SCRATCH"; ( cd "$SCRATCH" || exit 1
    git init -q . && git config user.email t@example.invalid && git config user.name t
    mkdir -p mcp/agent xlog updater phantom-browser phantom-connector-runtime
    for c in xlog xsiam caldera web cortex-docs cortex-content cortex-xdr http-sender wec-sender; do mkdir -p "bundles/spark/connectors/$c/src"; echo "$c" > "bundles/spark/connectors/$c/src/a.py"; done
    echo a > mcp/agent/a; echo a > xlog/a; echo a > updater/a; echo a > phantom-browser/a; echo a > phantom-connector-runtime/a
    git add -A && git commit -q -m base && git tag v1.0.3 )
}
change() { ( cd "$SCRATCH" || exit 1; echo changed >> "$1"; git add -A; git commit -q -m change ); }
plan() { # plan [VAR=value ...]: print the outputs of `plan` run inside the scratch repo
  ( cd "$SCRATCH" || exit 1; GITHUB_OUTPUT="$WORK/plan.out"; : > "$GITHUB_OUTPUT"; export GITHUB_OUTPUT
    env "$@" bash -c "$(declare -f run); run plan" > "$WORK/plan.log" 2>&1 ) && cat "$WORK/plan.out"
}
out_of() { sed -n "s/^$1=//p" "$WORK/plan.out"; }
words() { printf '%s' "$1" | wc -w | tr -d ' '; }

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

echo "== plan"
mk_repo
expect_ok "plan with nothing changed" plan
[ "$(out_of runtime)" = retag ] && ok || bad "unchanged runtime is retagged, got '$(out_of runtime)'"
[ "$(out_of built)" = phantom-agent-oss ] && ok || bad "only the agent is built when nothing changed, got '$(out_of built)'"
[ "$(words "$(out_of retag)")" = 14 ] && ok || bad "14 packages are retagged (everything but the agent), got $(words "$(out_of retag)")"
[ "$(words "$(out_of retag_rest)")" = 13 ] && ok || bad "13 are retagged by the last job (the runtime is retagged by its own), got $(words "$(out_of retag_rest)")"
out_of retag_rest | grep -q "$RT" && bad "retag_rest must not contain the runtime" || ok
out_of retag_rest | grep -q phantom-caldera-oss && ok || bad "Caldera is always retagged"
out_of retag_rest | grep -q phantom-agent-oss && bad "the agent is never retagged" || ok
python3 -c 'import json,sys; m=json.loads(sys.argv[1]); assert [x["pkg"] for x in m]==["phantom-agent-oss"], m; assert m[0]["file"]=="mcp/agent/Dockerfile" and m[0]["context"]=="." and m[0]["build_args"]==""' "$(out_of matrix)" && ok || bad "matrix holds the agent only: $(out_of matrix)"

mk_repo; change phantom-connector-runtime/a
expect_ok "plan after a runtime change" plan
[ "$(out_of runtime)" = build ] && ok || bad "a runtime change builds the runtime"
[ "$(words "$(out_of built)")" = 11 ] && ok || bad "runtime + 9 connectors + agent = 11 built, got $(words "$(out_of built)")"
python3 - "$(out_of matrix)" <<'PY' && ok || bad "a runtime change builds every connector against the new runtime"
import json, sys
m = json.loads(sys.argv[1])
pk = [x["pkg"] for x in m]
assert len(m) == 10 and "phantom-agent-oss" in pk and "phantom-connector-runtime-oss" not in pk, pk
for x in m:
    if x["pkg"].startswith("phantom-connector-"):
        assert x["build_args"] == "PHANTOM_RUNTIME_VERSION=1.0.4", x
        assert x["context"] == "." and x["file"] == "bundles/spark/connectors/" + x["pkg"][len("phantom-connector-"):-len("-oss")] + "/Dockerfile", x
    else:
        assert x["build_args"] == "", x
PY

mk_repo; change bundles/spark/connectors/http-sender/src/a.py
expect_ok "plan after a single connector change" plan
[ "$(out_of runtime)" = retag ] && ok || bad "the runtime stays retagged"
python3 -c 'import json,sys; assert sorted(x["pkg"] for x in json.loads(sys.argv[1]))==["phantom-agent-oss","phantom-connector-http-sender-oss"]' "$(out_of matrix)" && ok || bad "only the agent and http-sender are built: $(out_of matrix)"

mk_repo; change xlog/a
expect_ok "plan after an xlog service change" plan
python3 -c 'import json,sys; assert sorted(x["pkg"] for x in json.loads(sys.argv[1]))==["phantom-agent-oss","phantom-xlog-oss"]' "$(out_of matrix)" && ok || bad "the xlog service, not the xlog connector, is built: $(out_of matrix)"

mk_repo; change updater/a; change phantom-browser/a
expect_ok "plan after updater and browser changes" plan
python3 -c 'import json,sys; assert sorted(x["pkg"] for x in json.loads(sys.argv[1]))==["phantom-agent-oss","phantom-browser-oss","phantom-updater-oss"]' "$(out_of matrix)" && ok || bad "updater and browser are built: $(out_of matrix)"

mk_repo; ( cd "$SCRATCH" && echo x > docs.md && git add -A && git commit -q -m docs )
expect_ok "plan after an unrelated change" plan
[ "$(out_of built)" = phantom-agent-oss ] && ok || bad "an unrelated change builds nothing but the agent"

mk_repo
expect_ok "plan rebuild=all" plan REBUILD=all
[ "$(out_of runtime)" = build ] && [ "$(words "$(out_of built)")" = 14 ] && [ "$(out_of retag)" = phantom-caldera-oss ] && ok || bad "rebuild=all builds all 14 buildable packages and retags only Caldera: built=$(out_of built) retag=$(out_of retag)"

expect_ok "plan without the base git tag builds everything" plan BASE_TAG=9.9.9
[ "$(words "$(out_of built)")" = 14 ] && ok || bad "no v9.9.9 to compare with: build all 14, got $(words "$(out_of built)")"
grep -q "^::notice::git tag v9.9.9 is not in this checkout" "$WORK/plan.log" && ok || bad "the missing tag is reported"

plan REBUILD=sometimes >/dev/null 2>&1 && bad "plan rejects an unknown REBUILD" || { grep -q '^::error::rebuild must be' "$WORK/plan.log" && ok || bad "plan rejects an unknown REBUILD with a guard message"; }
plan GITHUB_REF=refs/heads/feature >/dev/null 2>&1 && bad "plan validates the run context" || ok

echo "== build spec"
# A Dockerfile that copies something its package does not watch would let that file change without a rebuild.
bash "$SCRIPT" spec > "$WORK/spec.txt"
n=$(wc -l < "$WORK/spec.txt" | tr -d ' ')
[ "$n" = 14 ] && ok || bad "BUILD_SPEC should list the 14 buildable packages, got $n"
python3 - "$REPO_ROOT" "$WORK/spec.txt" > "$WORK/spec.problems" <<'PY'
import os, re, sys
root, spec = sys.argv[1:3]
for line in open(spec):
    pkg, ctx, file, watch, check = line.rstrip("\n").split("|")
    if not os.path.isfile(os.path.join(root, file)):
        print(f"{pkg}: Dockerfile {file} does not exist"); continue
    if check.startswith("connector:"):
        cid = check.split(":", 1)[1]
        if pkg != f"phantom-connector-{cid}-oss" or not os.path.isdir(os.path.join(root, "bundles/spark/connectors", cid, "src")):
            print(f"{pkg}: check '{check}' does not match an existing connector")
    elif check not in ("-", "runtime"):
        print(f"{pkg}: unknown check '{check}'")
    if watch == "always":
        continue
    watched = watch.split()
    for raw in open(os.path.join(root, file)):
        m = re.match(r"COPY\s+(--\S+\s+)?(.+)", raw.strip())
        if not m or (m.group(1) or "").startswith("--from"):
            continue
        parts = m.group(2).split()
        for src in parts[:-1]:
            full = os.path.normpath(os.path.join(ctx, src))
            if not any(full == w or full.startswith(w + "/") for w in watched):
                print(f"{pkg}: the Dockerfile copies '{full}', outside its watched paths ({watch})")
PY
if [ -s "$WORK/spec.problems" ]; then while IFS= read -r l; do bad "$l"; done < "$WORK/spec.problems"; else ok; fi

echo "== smoke"
new_registry 20
expect_ok "smoke runtime" run smoke "$RT" "$R/$RT:1.0.4"
grep -q "pkgutil.iter_modules(runtime.__path__)" "$STUB_DIR/run-code.log" && ok || bad "the runtime check imports every runtime module"
expect_ok "smoke http-sender" run smoke phantom-connector-http-sender-oss "$R/phantom-connector-http-sender-oss:1.0.4"
tail -n 1 "$STUB_DIR/run-code.log" | grep -q "connectors.http-sender.src.connector" && ok || bad "a connector check imports the connector the way the entrypoint does"
: > "$STUB_DIR/runs.log"
expect_ok "smoke agent has no check" run smoke phantom-agent-oss "$R/phantom-agent-oss:1.0.4"
[ ! -s "$STUB_DIR/runs.log" ] && ok || bad "no container is run for a package without a check"
export STUB_SMOKE_FAIL=1
expect_fail "smoke fails the run when the import fails" run smoke phantom-connector-wec-sender-oss "$R/phantom-connector-wec-sender-oss:1.0.4"
grep -q "not pushing it" "$WORK/out" && ok || bad "the failure says the image is not pushed"
unset STUB_SMOKE_FAIL
expect_fail "smoke rejects a package that is not built here" run smoke phantom-caldera-oss "$R/phantom-caldera-oss:1.0.4"

echo "== check-pushed"
new_registry 21
put "$R/phantom-agent-oss:1.0.4" "sha256:pushed"
expect_ok   "check-pushed matches"            run check-pushed phantom-agent-oss sha256:pushed
expect_fail "check-pushed detects a mismatch" run check-pushed phantom-agent-oss sha256:other
expect_fail "check-pushed detects an absent tag" run check-pushed phantom-xlog-oss sha256:pushed
expect_fail "check-pushed rejects an unknown package" run check-pushed phantom-other-oss sha256:pushed
expect_fail "check-pushed rejects a malformed digest" run check-pushed phantom-agent-oss "pushed;id"

echo "== retag"
new_registry 8
mk_repo
plan >/dev/null; LIST_REST="$(out_of retag_rest)"; LIST_ALL="$(out_of retag)"; LIST_BUILT="$(out_of built)"
run preflight "$WORK/before8" >/dev/null 2>&1
expect_ok "retag" with "RETAG_LIST=$LIST_REST" -- bash -c "$(declare -f run); run retag"
c=$(wc -l < "$STUB_DIR/calls.log" | tr -d ' ')
[ "$c" = 13 ] && ok || bad "retag should make exactly 13 create calls, got $c"
grep -q "phantom-agent-oss" "$STUB_DIR/calls.log" && bad "retag must not touch the agent image" || ok
grep -q "$RT" "$STUB_DIR/calls.log" && bad "retag must not touch the runtime when it is not in the list" || ok
grep -E -q "(:latest|:1\.0) <-|<- .*(:latest|:1\.0)$" "$STUB_DIR/calls.log" && bad "retag wrote or read latest / X.Y" || ok
grep -q "create $R/phantom-xlog-oss:1.0.4 <- $R/phantom-xlog-oss:1.0.3" "$STUB_DIR/calls.log" && ok || bad "retag source/destination"
[ "$(cat "$STUB_DIR/$(key "$R/phantom-xlog-oss:1.0.4")")" = sha256:base2 ] && ok || bad "retagged digest equals the base digest"
expect_fail "retag rejects a package that is not one of the 15" with "RETAG_LIST=phantom-xlog-oss phantom-other-oss" -- bash -c "$(declare -f run); run retag"
expect_ok   "retag with an empty list does nothing" with "RETAG_LIST=" -- bash -c "$(declare -f run); run retag"

new_registry 9
export STUB_MUTATE_DEST="$R/phantom-connector-cortex-xdr-oss:1.0.4"
expect_fail "retag fails when the new tag's digest differs from base_tag's" with "RETAG_LIST=$LIST_REST" -- bash -c "$(declare -f run); run retag"
unset STUB_MUTATE_DEST

echo "== verify"
verify() { with "BUILT_LIST=${BUILT_OVERRIDE-$LIST_BUILT}" "RETAG_LIST=${RETAG_OVERRIDE-$LIST_ALL}" "$@" -- bash -c "$(declare -f run); run verify $VERIFY_FILE"; }
# A finished run: the agent was built and pushed, the runtime and the other 13 retagged.
finished_run() {
  new_registry "$1"; VERIFY_FILE="$WORK/before$1"
  run preflight "$VERIFY_FILE" >/dev/null 2>&1
  put "$R/phantom-agent-oss:1.0.4" "sha256:newagent"
  RETAG_LIST="$LIST_REST" run retag >/dev/null 2>&1
  RETAG_LIST="$RT" run retag >/dev/null 2>&1
}
finished_run 10
SUM="$WORK/summary10"; : > "$SUM"
expect_ok "verify happy path" verify "GITHUB_STEP_SUMMARY=$SUM"
rows=$(grep -c 'ghcr.io/ayman-m/phantom-.*-oss@sha256:' "$SUM" | tr -d ' ')
[ "$rows" = 15 ] && ok || bad "summary should list 15 digest rows, got $rows"
grep -q "sha256:newagent" "$SUM" && ok || bad "summary lists the agent digest"
grep -c "built from this checkout" "$SUM" | grep -q '^1$' && ok || bad "summary marks the built image"
grep -c "unchanged since 1.0.3, retagged" "$SUM" | grep -q '^14$' && ok || bad "summary marks the 14 retagged images"

put "$R/phantom-xlog-oss:latest" "sha256:MOVED"
expect_fail "verify detects a moved latest" verify
grep -q "phantom-xlog-oss:latest" "$WORK/out" && ok || bad "verify names the moved ref"
put "$R/phantom-xlog-oss:latest" "sha256:latest2"

put "$R/phantom-xlog-oss:1.0" "sha256:MOVED"
expect_fail "verify detects a moved X.Y" verify
put "$R/phantom-xlog-oss:1.0" "sha256:minor2"

put "$R/phantom-xlog-oss:1.0.3" "sha256:MOVED"
expect_fail "verify detects a moved base_tag" verify
put "$R/phantom-xlog-oss:1.0.3" "sha256:base2"

rm "$STUB_DIR/$(key "$R/phantom-agent-oss:1.0.4")"
expect_fail "verify detects a built image that is not in the registry" verify
put "$R/phantom-agent-oss:1.0.4" "sha256:newagent"

BUILT_OVERRIDE="" expect_fail "verify rejects a package that is in neither list" verify
RETAG_OVERRIDE="phantom-other-oss" expect_fail "verify rejects an unknown package name" verify

finished_run 11
put "$R/phantom-xlog-oss:1.0.4" "sha256:tampered"
expect_fail "verify detects a retag that no longer equals base_tag" verify

finished_run 12
rm "$STUB_DIR/$(key "$R/phantom-xlog-oss:1.0")"
expect_fail "verify detects an X.Y tag that disappeared" verify

# A run that rebuilt the runtime and one connector: those two are built, not retagged.
new_registry 13; VERIFY_FILE="$WORK/before13"
run preflight "$VERIFY_FILE" >/dev/null 2>&1
mk_repo; change phantom-connector-runtime/a; plan >/dev/null
B2="$(out_of built)"; L2="$(out_of retag)"; L2R="$(out_of retag_rest)"
n=0; for p in $B2; do n=$((n + 1)); put "$R/$p:1.0.4" "sha256:built$n"; done
RETAG_LIST="$L2R" run retag >/dev/null 2>&1
SUM="$WORK/summary13"; : > "$SUM"
expect_ok "verify after a runtime rebuild" with "BUILT_LIST=$B2" "RETAG_LIST=$L2" "GITHUB_STEP_SUMMARY=$SUM" -- bash -c "$(declare -f run); run verify $VERIFY_FILE"
grep -c "built from this checkout" "$SUM" | grep -q '^11$' && ok || bad "11 built rows after a runtime change"

echo "== unknown subcommand"
expect_fail "unknown subcommand" run frobnicate

echo
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ]
