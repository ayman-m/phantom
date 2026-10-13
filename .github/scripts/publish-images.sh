#!/usr/bin/env bash
# Release-guard logic for .github/workflows/publish-images.yml. Tested by test-publish-images.sh
# against a stub `docker`; the workflow runs that test before it touches the registry.
#
#   validate            check the inputs and that the run is on main of the public repo
#   preflight FILE      refuse to overwrite a released tag, require base_tag on all 15 packages,
#                       and record the digest of base_tag, latest and X.Y per package in FILE
#   retag               add TAG to the 14 unchanged packages, registry-side, from BASE_TAG
#   verify FILE         re-read everything: recorded tags unchanged, new tags correct; write the summary
#
# Inputs come from the environment (never interpolated into a shell line by the workflow):
#   TAG, BASE_TAG, AGENT_DIGEST (verify only: the digest the build step pushed)
#   GITHUB_REPOSITORY, GITHUB_REF (set by the runner), GITHUB_STEP_SUMMARY (optional)
#
# The only registry write in this file is `imagetools create -t <pkg>:$TAG`, and $TAG is
# validated to be X.Y.Z or X.Y.Z-rcN. `latest` and `X.Y` are never written.
set -euo pipefail

OWNER=ayman-m
REPO="$OWNER/phantom"
REGISTRY="ghcr.io/$OWNER"

# The fifteen packages. The agent is built from this checkout; the other fourteen keep the
# image of BASE_TAG and only gain a new tag. Keep in step with installer/CLAUDE.md and BUILDING.md.
AGENT_PKG=phantom-agent-oss
RETAG_PKGS=(
  phantom-xlog-oss
  phantom-caldera-oss
  phantom-updater-oss
  phantom-browser-oss
  phantom-connector-runtime-oss
  phantom-connector-xlog-oss
  phantom-connector-xsiam-oss
  phantom-connector-caldera-oss
  phantom-connector-web-oss
  phantom-connector-cortex-docs-oss
  phantom-connector-cortex-content-oss
  phantom-connector-cortex-xdr-oss
  phantom-connector-http-sender-oss
  phantom-connector-wec-sender-oss
)
ALL_PKGS=("$AGENT_PKG" "${RETAG_PKGS[@]}")

TAG_RE='^[0-9]+\.[0-9]+\.[0-9]+(-rc[0-9]+)?$'
BASE_RE='^[0-9]+\.[0-9]+\.[0-9]+$'
DIGEST_RE='^sha256:[[:alnum:]]+$'
NOT_FOUND_RE='not found|manifest unknown|name unknown|no such manifest'
DENIED_RE='denied|unauthorized|forbidden'

die() { echo "::error::$*" >&2; exit 1; }
img() { printf '%s/%s:%s' "$REGISTRY" "$1" "$2"; }
# 1.0.4 -> 1.0, 1.0.4-rc1 -> 1.0
minor_of() { local core="${1%%-*}"; printf '%s' "${core%.*}"; }

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

# The only write. Re-checks the tag so no future edit can reach latest or X.Y through here.
write_tag() {
  local dst="$1" src="$2" attempt out
  [[ "$TAG" =~ $TAG_RE ]] || die "refusing to write tag '$TAG'"
  [ "${dst##*:}" = "$TAG" ] || die "refusing to write $dst (only :$TAG may be written)"
  for attempt in 1 2 3; do
    if out="$(docker buildx imagetools create -t "$dst" "$src" 2>&1 </dev/null)"; then return 0; fi
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
      echo "::error::$p has no $BASE_TAG to retag from or compare against" >&2; errors=$((errors + 1)); continue
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

cmd_retag() {
  local p src dst s d
  cmd_validate
  for p in "${RETAG_PKGS[@]}"; do
    src="$(img "$p" "$BASE_TAG")"; dst="$(img "$p" "$TAG")"
    write_tag "$dst" "$src"
    s="$(ref_digest "$src")" || die "cannot read $src"
    d="$(ref_digest "$dst")" || die "cannot read $dst"
    { [ "$s" != ABSENT ] && [ "$s" = "$d" ]; } || die "$dst is $d but $src is $s: the retag changed the digest"
    echo "tagged $p:$TAG = $d"
  done
}

cmd_verify() {
  local before="${1:?usage: verify FILE}" p ref d now b problems=0 table=""
  [[ "${AGENT_DIGEST-}" =~ $DIGEST_RE ]] || die "AGENT_DIGEST must be the digest the build step pushed; got: '${AGENT_DIGEST-}'"
  cmd_validate

  # 1. Nothing that existed before may have moved: base_tag, latest, X.Y (absent stays absent).
  while IFS=$'\t' read -r p ref d; do
    if ! now="$(ref_digest "$ref")"; then problems=$((problems + 1)); continue; fi
    if [ "$now" != "$d" ]; then
      echo "::error::$ref changed during the run: $d -> $now" >&2; problems=$((problems + 1))
    fi
  done < "$before"

  # 2. The new tag is what it should be, on every package.
  for p in "${ALL_PKGS[@]}"; do
    ref="$(img "$p" "$TAG")"
    if ! now="$(ref_digest "$ref")"; then problems=$((problems + 1)); continue; fi
    if [ "$p" = "$AGENT_PKG" ]; then
      [ "$now" = "$AGENT_DIGEST" ] || { echo "::error::$ref is $now but the build pushed $AGENT_DIGEST" >&2; problems=$((problems + 1)); }
      table+="| \`$p\` | \`$REGISTRY/$p@$now\` | built from this checkout |"$'\n'
    else
      b="$(awk -F'\t' -v r="$(img "$p" "$BASE_TAG")" '$2 == r { print $3 }' "$before")"
      [ -n "$b" ] && [ "$now" = "$b" ] || { echo "::error::$ref is $now but $BASE_TAG was $b" >&2; problems=$((problems + 1)); }
      table+="| \`$p\` | \`$REGISTRY/$p@$now\` | retagged from $BASE_TAG |"$'\n'
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
  validate)  cmd_validate ;;
  preflight) shift; cmd_preflight "$@" ;;
  retag)     cmd_retag ;;
  verify)    shift; cmd_verify "$@" ;;
  *)         die "usage: $0 validate | preflight FILE | retag | verify FILE" ;;
esac
