#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE_DIR="${BUNDLE_DIR:-$ROOT_DIR/bundles/spark}"
DIST_DIR="${DIST_DIR:-$ROOT_DIR/dist}"
BUNDLE_NAME="${BUNDLE_NAME:-phantom-soc-simulation-0.1.0}"
OUTPUT_DIR="$DIST_DIR/$BUNDLE_NAME"
ARCHIVE_PATH="${ARCHIVE_PATH:-$DIST_DIR/$BUNDLE_NAME.tar.zst}"

if ! tar --help 2>/dev/null | grep -q -- '--zstd'; then
  echo "tar with --zstd support is required for Spark .tar.zst bundles" >&2
  exit 1
fi

cd "$ROOT_DIR"
python3 scripts/validate_spark_bundle.py "$BUNDLE_DIR"

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"
cp -R "$BUNDLE_DIR"/. "$OUTPUT_DIR"/

(
  cd "$OUTPUT_DIR"
  find . -type f -print0 | sort -z | xargs -0 shasum -a 256 > checksums.sha256
)

rm -f "$ARCHIVE_PATH"
tar --zstd -C "$DIST_DIR" -cf "$ARCHIVE_PATH" "$BUNDLE_NAME"

echo "Spark bundle directory: $OUTPUT_DIR"
echo "Spark bundle archive: $ARCHIVE_PATH"
