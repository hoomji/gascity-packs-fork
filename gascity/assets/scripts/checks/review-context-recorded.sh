#!/usr/bin/env bash
set -euo pipefail

# Gate for the build-basic starter review setup step.
#
# The review lanes find the implementation worktree only through the context
# file the workflow root names in gc.build.code_review_context_path. A setup
# step that writes the file and closes pass without recording the path leaves
# every lane to fail hard, and the build publishes unreviewed. This gate
# reads $GC_BEAD_ID, resolves the workflow root via gc.root_bead_id, and
# passes only when the root names a context file that exists. Failures print
# one line on stderr as repair context for the next attempt. Never prompts.

KEY="gc.build.code_review_context_path"

fail() {
  echo "review-context-check: $*" >&2
  exit 1
}

BEAD_ID="${GC_BEAD_ID:-}"
[ -n "$BEAD_ID" ] || fail "GC_BEAD_ID is required"
command -v gc >/dev/null 2>&1 || fail "gc is required on PATH"
command -v python3 >/dev/null 2>&1 || fail "python3 is required on PATH"

metadata_value() {
  printf '%s' "$1" | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)
if isinstance(data, list):
    data = data[0] if data else {}
metadata = data.get("metadata") if isinstance(data, dict) else None
value = metadata.get(sys.argv[1], "") if isinstance(metadata, dict) else ""
print(value if isinstance(value, str) else "")
' "$2"
}

GC_ERR="$(mktemp)"
trap 'rm -f "$GC_ERR"' EXIT INT TERM HUP
SHOW_JSON="$(gc bd show "$BEAD_ID" --json 2>"$GC_ERR")" \
  || fail "gc bd show $BEAD_ID failed: $(tail -c 400 "$GC_ERR" | tr '\n' ' ')"
ROOT_ID="$(metadata_value "$SHOW_JSON" "gc.root_bead_id")"
[ -n "$ROOT_ID" ] || fail "step $BEAD_ID has no gc.root_bead_id"
ROOT_JSON="$(gc bd show "$ROOT_ID" --json 2>"$GC_ERR")" \
  || fail "gc bd show $ROOT_ID failed: $(tail -c 400 "$GC_ERR" | tr '\n' ' ')"

CONTEXT_PATH="$(metadata_value "$ROOT_JSON" "$KEY")"
[ -n "$CONTEXT_PATH" ] || fail "workflow root $ROOT_ID has no $KEY. Record the review context path on the root: gc bd update $ROOT_ID --set-metadata $KEY=<absolute path to code-review-context.md>, then read the root back."

case "$CONTEXT_PATH" in
  /*)
    [ -f "$CONTEXT_PATH" ] || fail "$KEY on $ROOT_ID names $CONTEXT_PATH, which does not exist"
    ;;
  *)
    FOUND=""
    TRIED=""
    for root in "${GC_RIG_ROOT:-}" "${GC_BEADS_SCOPE_ROOT:-}" "${GC_STORE_PATH:-}" "${GC_WORK_DIR:-}"; do
      [ -n "$root" ] || continue
      TRIED="${TRIED:+$TRIED, }$root/$CONTEXT_PATH"
      if [ -f "$root/$CONTEXT_PATH" ]; then
        FOUND="$root/$CONTEXT_PATH"
        break
      fi
    done
    [ -n "$FOUND" ] || fail "$KEY on $ROOT_ID names relative path $CONTEXT_PATH, which does not exist; tried ${TRIED:-no rig root in the environment}"
    CONTEXT_PATH="$FOUND"
    ;;
esac

echo "review context recorded: root=$ROOT_ID path=$CONTEXT_PATH"
