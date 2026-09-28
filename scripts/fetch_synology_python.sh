#!/usr/bin/env bash
# Fetch and verify the pinned python-build-standalone interpreters for SPK builds.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="${SYNOLOGY_PYTHON_CACHE_DIR:-$REPO/synology/cache}"
BASE_URL="${SYNOLOGY_PYTHON_RELEASE_BASE_URL:-https://github.com/astral-sh/python-build-standalone/releases/download/20260901}"
CURL_OPTS=(--connect-timeout 30 --max-time 900 --retry 3 --retry-all-errors)
mkdir -p "$CACHE"

for ARCH in aarch64 x86_64; do
  NAME="cpython-3.12.14+20260901-${ARCH}-unknown-linux-gnu-install_only_stripped.tar.gz"
  ARCHIVE="$CACHE/$NAME"
  CHECKSUM="$CACHE/$NAME.sha256"
  TARGET="$CACHE/python-$ARCH-base"

  verify_checksum() {
    local expected
    expected="$(awk 'NR == 1 {print $1}' "$CHECKSUM")"
    if [[ ! "$expected" =~ ^[a-fA-F0-9]{64}$ ]]; then
      echo "[fetch] invalid checksum file for $NAME" >&2
      return 1
    fi
    printf '%s  %s\n' "$expected" "$ARCHIVE" | sha256sum -c --status
  }

  if [[ -d "$TARGET" && -f "$ARCHIVE" && -f "$CHECKSUM" ]] && verify_checksum; then
    echo "[fetch] verified cache: $ARCH"
    continue
  fi

  # An unverified directory must never be consumed by the build after a failed fetch.
  rm -rf "$TARGET" "$ARCHIVE" "$CHECKSUM"
  TMP="$(mktemp -d "$CACHE/.fetch-${ARCH}.XXXXXX")"
  trap 'rm -rf "$TMP"' EXIT
  curl -fsSL "${CURL_OPTS[@]}" "$BASE_URL/$NAME" -o "$TMP/$NAME"
  curl -fsSL "${CURL_OPTS[@]}" "$BASE_URL/SHA256SUMS" -o "$TMP/SHA256SUMS"
  if ! awk -v target="$NAME" '$2 == target {print $1 "  " target; count++} END {if (count != 1) exit 1}' \
      "$TMP/SHA256SUMS" > "$TMP/$NAME.sha256"; then
    echo "[fetch] official checksum missing or duplicate for $NAME" >&2
    exit 1
  fi
  mv "$TMP/$NAME" "$ARCHIVE"
  mv "$TMP/$NAME.sha256" "$CHECKSUM"
  if ! verify_checksum; then
    echo "[fetch] checksum mismatch for $NAME" >&2
    rm -f "$ARCHIVE" "$CHECKSUM"
    exit 1
  fi
  tar -xzf "$ARCHIVE" -C "$TMP"
  if [[ ! -f "$TMP/python/bin/python3.12" ]]; then
    echo "[fetch] archive missing python/bin/python3.12: $NAME" >&2
    exit 1
  fi
  mv "$TMP/python" "$TARGET"
  rm -rf "$TMP"
  trap - EXIT
  echo "[fetch] ready: $ARCH"
done
