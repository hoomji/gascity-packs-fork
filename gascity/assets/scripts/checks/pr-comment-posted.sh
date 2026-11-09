#!/usr/bin/env bash
# Exec check for github-pr-review's post-comment step (formula-spec-v2 section 3.1).
#
# The step is done when this run posted the sticky comment: the PR workflow root
# records gc.github.comment_posted_this_run=true with a comment id and url. A
# transient GitHub failure (a timed-out lookup, a 5xx, a 429) leaves those unset,
# so the check says not yet and gc reruns the step instead of closing the
# workflow fail on an approved review (2026-11-09: promotion #8618's approve
# review closed fail on "existing-comment lookup timed out; nothing posted").
# A refused public-comment gate closes the step with gc.failure_class=hard, which
# ends the loop without running this check.
#
# Exit 0: pass. Exit 1: not yet, reason on stderr (the dispatcher records it in
# gc.attempt_log for the next attempt). Exit 75: gc unreachable, no verdict.
set -uo pipefail

not_yet() {
  echo "pr-comment-posted: $*" >&2
  exit 1
}

BEAD_ID="${GC_BEAD_ID:-}"
[ -n "$BEAD_ID" ] || not_yet "GC_BEAD_ID is required"

# meta <json> <key>: metadata[<key>] as a string (gc stores comment_id as a number), or empty.
meta() {
  printf '%s' "$1" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
if isinstance(data, list):
    data = data[0] if data else {}
value = ((data.get("metadata") or {}) if isinstance(data, dict) else {}).get(sys.argv[1], "")
print(value if isinstance(value, str) else str(value).lower() if isinstance(value, bool) else str(value) if isinstance(value, (int, float)) else "")
' "$2"
}

STEP_JSON="$(gc bd show "$BEAD_ID" --json 2>/dev/null)" || exit 75
ROOT_ID="$(meta "$STEP_JSON" gc.root_bead_id)"
[ -n "$ROOT_ID" ] || not_yet "$BEAD_ID has no gc.root_bead_id"
ROOT_JSON="$(gc bd show "$ROOT_ID" --json 2>/dev/null)" || exit 75

POSTED="$(meta "$ROOT_JSON" gc.github.comment_posted_this_run)"
COMMENT_ID="$(meta "$ROOT_JSON" gc.github.comment_id)"
COMMENT_URL="$(meta "$ROOT_JSON" gc.github.comment_url)"
[ "$POSTED" = "true" ] || not_yet "workflow root $ROOT_ID has gc.github.comment_posted_this_run='$POSTED', not true"
[ -n "$COMMENT_ID" ] || not_yet "workflow root $ROOT_ID has no gc.github.comment_id"
[ -n "$COMMENT_URL" ] || not_yet "workflow root $ROOT_ID has no gc.github.comment_url"
echo "pr comment posted: $COMMENT_URL"
