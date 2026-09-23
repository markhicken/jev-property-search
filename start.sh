#!/usr/bin/env bash
# Startup script for Hearth (Jev Ultrafast).
# Handles README steps 3 (agent Chrome), 4 (server) and 5 (open UI).
# Generates a random Chrome profile each run and cleans up prior profiles
# created by this script that are no longer in use.

set -euo pipefail

cd "$(dirname "$0")"

PROFILE_ROOT="${TMPDIR:-/tmp}"
PROFILE_PREFIX="hearth-chrome."
MARKER=".hearth_startup_profile"
DEBUG_PORT="${HEARTH_CHROME_PORT:-47913}"
APP_PORT="${TYPESAFE_DEMO_PORT:-48766}"
APP_URL="http://127.0.0.1:${APP_PORT}"
CDP_URL="http://127.0.0.1:${DEBUG_PORT}"
export TYPESAFE_DEMO_PORT="$APP_PORT"

# --- Cleanup prior profiles created by this script ---
echo "Cleaning up prior Hearth Chrome profiles..."
shopt -s nullglob
for dir in "$PROFILE_ROOT"/${PROFILE_PREFIX}*; do
  [ -d "$dir" ] || continue
  if [ ! -f "$dir/$MARKER" ]; then
    continue
  fi
  if pgrep -f "user-data-dir=$dir" >/dev/null 2>&1; then
    echo "  skip (in use): $dir"
    continue
  fi
  echo "  remove: $dir"
  rm -rf "$dir"
done
shopt -u nullglob

# --- Generate a new random profile dir ---
RAND_ID="$(python3 -c 'import secrets; print(secrets.token_hex(6))')"
PROFILE_DIR="$(mktemp -d "${PROFILE_ROOT}/${PROFILE_PREFIX}${RAND_ID}.XXXXXX")"
touch "$PROFILE_DIR/$MARKER"
echo "New Chrome profile: $PROFILE_DIR"

# --- Step 3: launch agent Chrome with remote debugging ---
echo "Launching agent Chrome on port ${DEBUG_PORT}..."
open -na 'Google Chrome' --args \
  --remote-debugging-port="$DEBUG_PORT" \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run \
  --no-default-browser-check \
  about:blank

# Wait for CDP endpoint
echo "Waiting for CDP endpoint..."
for _ in $(seq 1 50); do
  if curl -sf "${CDP_URL}/json/version" >/dev/null 2>&1; then
    echo "  ready."
    break
  fi
  sleep 0.2
done

cleanup() {
  echo ""
  echo "Shutting down..."
  pkill -f "user-data-dir=$PROFILE_DIR" 2>/dev/null || true
  sleep 0.5
  if [ -d "$PROFILE_DIR" ]; then
    rm -rf "$PROFILE_DIR" || true
  fi
}
trap cleanup EXIT INT TERM

# --- Step 5 (kicked off early): open the UI as a new tab in the agent Chrome ---
# instance we just launched (via its CDP endpoint), not whatever the OS default
# browser happens to be — `open` would launch a separate Chrome under the normal
# default profile instead of the debug-enabled one Jev is driving.
(
  for _ in $(seq 1 100); do
    if curl -sf "$APP_URL" >/dev/null 2>&1; then
      curl -sf -X PUT "${CDP_URL}/json/new?${APP_URL}" >/dev/null 2>&1 || open "$APP_URL"
      exit 0
    fi
    sleep 0.3
  done
) &

# --- Step 4: run Hearth ---
echo "Starting Hearth..."
BU_CDP_URL="$CDP_URL" exec uv run jev
