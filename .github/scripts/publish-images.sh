#!/usr/bin/env bash
# Release logic for .github/workflows/publish-images.yml. Tested by test-publish-images.sh against
# a stub `docker` and a scratch git repository; the workflow runs that test before it touches the registry.
#
#   validate            check the inputs and that the run is on main of the public repo
#   preflight FILE      refuse to overwrite a released tag, require base_tag on all 16 packages,
#                       and record the digest of base_tag, latest and X.Y per package in FILE
#   plan                decide, per package, whether TAG is built from this checkout or added to base_tag's image;
#                       writes runtime=, matrix=, retag=, retag_rest= and built= to $GITHUB_OUTPUT (stdout when unset)
#   smoke PKG IMAGE     run PKG's import check inside a locally built IMAGE (before anything is pushed)
#   check-pushed PKG D  confirm the registry holds TAG for PKG at digest D, the one the build step pushed
#   retag               add TAG to the packages in $RETAG_LIST, registry-side, from BASE_TAG (digest must stay equal)
#   spec                print the BUILD_SPEC lines (the test script checks them against the Dockerfiles)
#   verify FILE         re-read everything: recorded tags unchanged, new tags correct; write the summary
#
# Inputs come from the environment (never interpolated into a shell line by the workflow):
#   TAG, BASE_TAG, REBUILD (plan: auto | all), RETAG_LIST (retag, verify), BUILT_LIST (verify)
#   GITHUB_REPOSITORY, GITHUB_REF (set by the runner), GITHUB_STEP_SUMMARY, GITHUB_OUTPUT (optional)
#
# The only registry writes are `imagetools create --prefer-index=false -t <pkg>:$TAG` (here) and the build steps' push of <pkg>:$TAG
# (in the workflow). $TAG is validated to be X.Y.Z or X.Y.Z-rcN. `latest` and `X.Y` are never written.
#
# Why some images are built and others are only re-tagged: an image that is re-tagged from an earlier release has
# that release's code. Every package whose build context changed since BASE_TAG is therefore built from this
# checkout, and only the unchanged ones keep BASE_TAG's digest. `auto` finds the changed ones by diffing the git
# tag v<BASE_TAG> against HEAD; if that tag is not in the checkout, or REBUILD=all, everything buildable is built.
set -euo pipefail

OWNER=ayman-m
REPO="$OWNER/phantom"
REGISTRY="ghcr.io/$OWNER"

# Packages built from this checkout, one per line: package|context|dockerfile|watched paths|check
#   watched paths   what a change to which means the image is stale (`always`: built on every run)
#   check           `-` none, `runtime` every runtime module imports, `connector:<id>` the connector module imports as the
#                   runtime entrypoint imports it (this is what fails on a connector built on an older runtime base)
# The runtime comes first: every connector image is built FROM it at TAG. Keep in step with BUILDING.md and
# installer/CLAUDE.md.
RUNTIME_PKG=phantom-connector-runtime-oss
RUNTIME_DIR=phantom-connector-runtime
CONNECTORS=(xlog xsiam caldera web cortex-docs cortex-content cortex-xdr http-sender wec-sender cie-sender)
BUILD_SPEC=(
  "phantom-agent-oss|.|mcp/agent/Dockerfile|always|-"
  "$RUNTIME_PKG|$RUNTIME_DIR|$RUNTIME_DIR/Dockerfile|$RUNTIME_DIR|runtime"
  "phantom-xlog-oss|xlog|xlog/Dockerfile|xlog|-"
  "phantom-updater-oss|updater|updater/Dockerfile|updater|-"
  "phantom-browser-oss|phantom-browser|phantom-browser/Dockerfile|phantom-browser|-"
)
for _c in "${CONNECTORS[@]}"; do
  BUILD_SPEC+=("phantom-connector-$_c-oss|.|bundles/spark/connectors/$_c/Dockerfile|bundles/spark/connectors/$_c $RUNTIME_DIR|connector:$_c")
done
# Never built here: Caldera needs the build-time overlay of the Phantom plugin and default.yml.
RETAG_ONLY_PKGS=(phantom-caldera-oss)

ALL_PKGS=()
for _e in "${BUILD_SPEC[@]}"; do ALL_PKGS+=("${_e%%|*}"); done
ALL_PKGS+=("${RETAG_ONLY_PKGS[@]}")

TAG_RE='^[0-9]+\.[0-9]+\.[0-9]+(-rc[0-9]+)?$'
BASE_RE='^[0-9]+\.[0-9]+\.[0-9]+$'
DIGEST_RE='^sha256:[[:alnum:]]+$'
NOT_FOUND_RE='not found|manifest unknown|name unknown|no such manifest'
DENIED_RE='denied|unauthorized|forbidden'

die() { echo "::error::$*" >&2; exit 1; }
img() { printf '%s/%s:%s' "$REGISTRY" "$1" "$2"; }
# 1.0.4 -> 1.0, 1.0.4-rc1 -> 1.0
minor_of() { local core="${1%%-*}"; printf '%s' "${core%.*}"; }
# The BUILD_SPEC line of a package, or nothing.
spec_of() { local e; for e in "${BUILD_SPEC[@]}"; do [ "${e%%|*}" = "$1" ] && { printf '%s' "$e"; return 0; }; done; return 1; }
is_known() { local p; for p in "${ALL_PKGS[@]}"; do [ "$p" = "$1" ] && return 0; done; return 1; }
# Fails unless every word of the list is a known package; the lists come from earlier steps' outputs.
check_list() { local w; for w in $1; do is_known "$w" || die "'$w' is not one of the 16 packages"; done; }
# True (0) when $1 cannot be shown to be new since BASE_TAG -- i.e. it should already have a BASE_TAG image.
# False (1) only when its own watched paths provably did not exist at v$BASE_TAG (a connector added after that
# release): git history unreadable, no BUILD_SPEC entry (e.g. a retag-only package), or "always built" all count
# as "assume known" so this never masks a real problem, it only recognizes a genuinely brand-new package.
pkg_known_at_base() {
  local p="$1" e file watch base_ref="refs/tags/v${BASE_TAG-}"
  git rev-parse -q --verify "${base_ref}^{commit}" >/dev/null 2>&1 || return 0
  e="$(spec_of "$p")" || return 0
  IFS='|' read -r _ _ file watch _ <<< "$e"
  [ "$watch" = always ] && return 0
  # The package's own Dockerfile is unique to it (unlike its watched paths, which include shared dirs such as the
  # runtime base image that any connector's base_tag commit also has) -- its presence is what "existed" means here.
  git cat-file -e "${base_ref}:${file}" 2>/dev/null && return 0
  return 1
}

cmd_validate() {
  [[ "${TAG-}" =~ $TAG_RE ]] || die "tag must match $TAG_RE (X.Y.Z or X.Y.Z-rcN); got: '${TAG-}'"
  [[ "${BASE_TAG-}" =~ $BASE_RE ]] || die "base_tag must match $BASE_RE (X.Y.Z); got: '${BASE_TAG-}'"
  [ "$TAG" != "$BASE_TAG" ] || die "tag and base_tag are the same ($TAG)"
  [ "${GITHUB_REPOSITORY-}" = "$REPO" ] || die "images are published only from $REPO (this run: '${GITHUB_REPOSITORY-}')"
  [ "${GITHUB_REF-}" = "refs/heads/main" ] || die "images are published only from main (this run: '${GITHUB_REF-}')"
}

# Prints the manifest digest of a reference, or ABSENT when the registry says it does not exist.
# Any other failure (auth, rate limit, network) is an error: this must fail closed, never read as "absent".
ref_digest() {
  local ref="$1" out err
  err="$(mktemp)"
  if out="$(docker buildx imagetools inspect "$ref" --format '{{.Manifest.Digest}}' 2>"$err" </dev/null)"; then
    rm -f "$err"
    [[ "$out" =~ $DIGEST_RE ]] || { echo "unexpected inspect output for $ref: '$out'" >&2; return 1; }
    printf '%s' "$out"
    return 0
  fi
  if grep -q -i -E "$NOT_FOUND_RE" "$err" && ! grep -q -i -E "$DENIED_RE" "$err"; then
    rm -f "$err"
    printf 'ABSENT'
    return 0
  fi
  echo "cannot read $ref: $(tr '\n' ' ' < "$err" | cut -c1-300)" >&2
  rm -f "$err"
  return 1
}

# The only write made by this file. Re-checks the tag so no future edit can reach latest or X.Y through here.
write_tag() {
  local dst="$1" src="$2" attempt out
  [[ "$TAG" =~ $TAG_RE ]] || die "refusing to write tag '$TAG'"
  [ "${dst##*:}" = "$TAG" ] || die "refusing to write $dst (only :$TAG may be written)"
  for attempt in 1 2 3; do
    # --prefer-index=false: a byte-for-byte copy. Without it, a source that is a bare image manifest (what buildx pushes
    # with provenance off) is wrapped in a new index, which has a different digest and so recreates the container.
    if out="$(docker buildx imagetools create --prefer-index=false -t "$dst" "$src" 2>&1 </dev/null)"; then return 0; fi
    echo "attempt $attempt to create $dst failed: $(printf '%s' "$out" | tail -n 2 | tr '\n' ' ' | cut -c1-300)" >&2
    if printf '%s' "$out" | grep -q -i -E "$DENIED_RE"; then
      die "registry refused the write to $dst (package Actions access?); not retrying"
    fi
    sleep "${RETRY_SLEEP:-10}"
  done
  die "could not create $dst after 3 attempts"
}

# Record base_tag, latest and X.Y (of tag, and of base_tag when different) for every package.
snapshot() {
  local out="$1" p ref d refs
  : > "$out"
  for p in "${ALL_PKGS[@]}"; do
    refs=("$(img "$p" "$BASE_TAG")" "$(img "$p" latest)" "$(img "$p" "$(minor_of "$TAG")")")
    if [ "$(minor_of "$BASE_TAG")" != "$(minor_of "$TAG")" ]; then
      refs+=("$(img "$p" "$(minor_of "$BASE_TAG")")")
    fi
    for ref in "${refs[@]}"; do
      d="$(ref_digest "$ref")" || die "cannot snapshot $ref"
      printf '%s\t%s\t%s\n' "$p" "$ref" "$d" >> "$out"
    done
  done
}

cmd_preflight() {
  local out="${1:?usage: preflight FILE}" p b t errors=0
  cmd_validate
  for p in "${ALL_PKGS[@]}"; do
    if ! b="$(ref_digest "$(img "$p" "$BASE_TAG")")"; then errors=$((errors + 1)); continue; fi
    if [ "$b" = ABSENT ]; then
      if pkg_known_at_base "$p"; then
        echo "::error::$p has no $BASE_TAG to retag from or compare against" >&2; errors=$((errors + 1)); continue
      fi
      echo "::notice::$p did not exist at $BASE_TAG: new package, nothing to retag from or compare against"
    fi
    if ! t="$(ref_digest "$(img "$p" "$TAG")")"; then errors=$((errors + 1)); continue; fi
    if [ "$t" != ABSENT ]; then
      if [[ "$TAG" == *-rc* ]]; then
        echo "::notice::$p:$TAG exists ($t) and will be replaced: release candidates may be re-published"
      else
        echo "::error::$p:$TAG already exists ($t); released versions are never overwritten" >&2; errors=$((errors + 1))
      fi
    fi
  done
  [ "$errors" -eq 0 ] || die "preflight failed with $errors problem(s); nothing was written"
  snapshot "$out"
  echo "preflight ok: $(wc -l < "$out" | tr -d ' ') reference digests recorded in $out"
}

# Decide build or retag for every package. Needs the git history of the checkout (fetch-depth 0, tags).
cmd_plan() {
  local -a paths
  local rebuild="${REBUILD:-auto}" base_ref="refs/tags/v${BASE_TAG-}" have_base=0 e pkg ctx file watch check why paths
  local matrix="" retag=() rest=() runtime=retag built=() sep="" args out="${GITHUB_OUTPUT:-/dev/stdout}"
  cmd_validate
  [ "$rebuild" = auto ] || [ "$rebuild" = all ] || die "rebuild must be 'auto' or 'all'; got: '$rebuild'"
  if git rev-parse -q --verify "$base_ref^{commit}" >/dev/null 2>&1; then
    have_base=1
  elif [ "$rebuild" = auto ]; then
    echo "::notice::git tag v$BASE_TAG is not in this checkout, so nothing can be compared: building every buildable package"
  fi
  for e in "${BUILD_SPEC[@]}"; do
    IFS='|' read -r pkg ctx file watch check <<< "$e"
    read -r -a paths <<< "$watch"
    if [ "$watch" = always ]; then why="always built"
    elif [ "$rebuild" = all ]; then why="rebuild=all"
    elif [ "$have_base" = 0 ]; then why="no v$BASE_TAG to compare with"
    elif ! git diff --quiet "$base_ref" HEAD -- "${paths[@]}"; then why="changed since v$BASE_TAG"
    else why=""
    fi
    if [ -z "$why" ]; then
      echo "retag  $pkg: unchanged since v$BASE_TAG"
      retag+=("$pkg")
      if [ "$pkg" != "$RUNTIME_PKG" ]; then rest+=("$pkg"); fi
      continue
    fi
    echo "build  $pkg: $why"
    built+=("$pkg")
    if [ "$pkg" = "$RUNTIME_PKG" ]; then runtime=build; continue; fi
    args=""; [[ "$check" == connector:* ]] && args="PHANTOM_RUNTIME_VERSION=$TAG"
    matrix+="$sep{\"pkg\":\"$pkg\",\"context\":\"$ctx\",\"file\":\"$file\",\"build_args\":\"$args\"}"
    sep=","
  done
  retag+=("${RETAG_ONLY_PKGS[@]}"); rest+=("${RETAG_ONLY_PKGS[@]}")
  {
    echo "runtime=$runtime"          # the runtime job builds it, or retags it when unchanged
    echo "matrix=[$matrix]"          # every other package to build
    echo "retag=${retag[*]}"         # every package that keeps base_tag's digest (verify reads this)
    echo "retag_rest=${rest[*]}"     # the same without the runtime, which the runtime job retags itself
    echo "built=${built[*]}"
  } >> "$out"
}

# Run a package's import check inside a locally built image, before anything is pushed.
cmd_smoke() {
  local pkg="${1:?usage: smoke PKG IMAGE}" image="${2:?usage: smoke PKG IMAGE}" e check code id
  e="$(spec_of "$pkg")" || die "smoke: '$pkg' is not built from this checkout"
  check="${e##*|}"
  case "$check" in
    -) echo "no import check for $pkg"; return 0 ;;
    # Every module of the runtime package imports, so a module that needs something the image lacks fails here.
    runtime) code="import importlib, pkgutil, runtime; [importlib.import_module('runtime.' + m.name) for m in pkgutil.iter_modules(runtime.__path__)]" ;;
    connector:*)
      id="${check#connector:}"
      # What runtime.entrypoint does at boot. A connector whose source needs a runtime module that the image's runtime
      # lacks (it was built on an older runtime) fails on this import.
      code="import importlib; importlib.import_module('connectors.${id}.src.connector')" ;;
    *) die "smoke: unknown check '$check' for $pkg" ;;
  esac
  docker run --rm --entrypoint python "$image" -c "$code" || die "$pkg: the import check failed inside $image; not pushing it"
  echo "import check passed for $pkg"
}

cmd_check_pushed() {
  local pkg="${1:?usage: check-pushed PKG DIGEST}" want="${2:?usage: check-pushed PKG DIGEST}" now
  cmd_validate
  is_known "$pkg" || die "'$pkg' is not one of the 16 packages"
  [[ "$want" =~ $DIGEST_RE ]] || die "digest must be sha256:...; got: '$want'"
  now="$(ref_digest "$(img "$pkg" "$TAG")")" || die "cannot read $pkg:$TAG"
  [ "$now" = "$want" ] || die "$pkg:$TAG is $now but the build pushed $want"
  echo "$pkg:$TAG = $now"
}

cmd_retag() {
  local p src dst s d
  cmd_validate
  check_list "${RETAG_LIST-}"
  for p in ${RETAG_LIST-}; do
    src="$(img "$p" "$BASE_TAG")"; dst="$(img "$p" "$TAG")"
    write_tag "$dst" "$src"
    s="$(ref_digest "$src")" || die "cannot read $src"
    d="$(ref_digest "$dst")" || die "cannot read $dst"
    { [ "$s" != ABSENT ] && [ "$s" = "$d" ]; } || die "$dst is $d but $src is $s: the retag changed the digest"
    echo "tagged $p:$TAG = $d"
  done
}

cmd_verify() {
  local before="${1:?usage: verify FILE}" p ref d now b problems=0 table="" built_s=" ${BUILT_LIST-} " retagged_s=" ${RETAG_LIST-} "
  cmd_validate
  check_list "${BUILT_LIST-}"; check_list "${RETAG_LIST-}"

  # 1. Nothing that existed before may have moved: base_tag, latest, X.Y (absent stays absent).
  while IFS=$'\t' read -r p ref d; do
    if ! now="$(ref_digest "$ref")"; then problems=$((problems + 1)); continue; fi
    if [ "$now" != "$d" ]; then
      echo "::error::$ref changed during the run: $d -> $now" >&2; problems=$((problems + 1))
    fi
  done < "$before"

  # 2. The new tag is on every package and is what it should be: a built package is present (its own job already compared
  #    the digest it pushed), a re-tagged one equals base_tag's.
  for p in "${ALL_PKGS[@]}"; do
    ref="$(img "$p" "$TAG")"
    if ! now="$(ref_digest "$ref")"; then problems=$((problems + 1)); continue; fi
    if [[ "$built_s" == *" $p "* ]]; then
      [ "$now" != ABSENT ] || { echo "::error::$ref was built but is not in the registry" >&2; problems=$((problems + 1)); }
      table+="| \`$p\` | \`$REGISTRY/$p@$now\` | built from this checkout |"$'\n'
    elif [[ "$retagged_s" == *" $p "* ]]; then
      b="$(awk -F'\t' -v r="$(img "$p" "$BASE_TAG")" '$2 == r { print $3 }' "$before")"
      [ -n "$b" ] && [ "$now" = "$b" ] || { echo "::error::$ref is $now but $BASE_TAG was $b" >&2; problems=$((problems + 1)); }
      table+="| \`$p\` | \`$REGISTRY/$p@$now\` | unchanged since $BASE_TAG, retagged |"$'\n'
    else
      echo "::error::$p is in neither the built nor the retagged list" >&2; problems=$((problems + 1))
    fi
  done

  {
    echo "## Images published as \`$TAG\`"
    echo
    echo "Commit \`${GITHUB_SHA:-unknown}\`. Digests of \`$BASE_TAG\`, \`latest\` and \`$(minor_of "$TAG")\` re-read after the run: $([ "$problems" -eq 0 ] && echo 'unchanged' || echo 'CHECK FAILED, see the job log')."
    echo
    echo "| Package | Digest | How |"
    echo "|---|---|---|"
    printf '%s' "$table"
  } | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"

  [ "$problems" -eq 0 ] || die "verification found $problems problem(s)"
}

case "${1-}" in
  validate)     cmd_validate ;;
  preflight)    shift; cmd_preflight "$@" ;;
  plan)         cmd_plan ;;
  smoke)        shift; cmd_smoke "$@" ;;
  spec)         printf '%s\n' "${BUILD_SPEC[@]}" ;;
  check-pushed) shift; cmd_check_pushed "$@" ;;
  retag)        cmd_retag ;;
  verify)       shift; cmd_verify "$@" ;;
  *)            die "usage: $0 validate | preflight FILE | plan | spec | smoke PKG IMAGE | check-pushed PKG DIGEST | retag | verify FILE" ;;
esac
