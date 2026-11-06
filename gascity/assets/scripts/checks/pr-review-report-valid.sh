#!/usr/bin/env bash
# Exec check for github-pr-review's run-review step (formula-spec-v2 section 3.1).
#
# The step is done when the PR workflow root records the review report for this
# head and that report is a finished review:
#   - gc.github.review_report_path is set and lies under gc.github.review_dir
#     (the head-SHA directory snapshot recorded), so a stale head's report
#     cannot pass;
#   - github_reports.py review-outcome accepts the report;
#   - gc.github.review_outcome on the root equals the outcome the report gives.
#
# Exit 0: pass. Exit 1: not yet, reason on stderr (the dispatcher records it in
# gc.attempt_log for the next attempt). Exit 75: gc unreachable, no verdict.
set -uo pipefail

not_yet() {
  echo "pr-review-report: $*" >&2
  exit 1
}

BEAD_ID="${GC_BEAD_ID:-}"
[ -n "$BEAD_ID" ] || not_yet "GC_BEAD_ID is required"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# json_field <json> <expr>: metadata[<key>] for "m:<key>", else a top-level key.
json_field() {
  printf '%s' "$1" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
if isinstance(data, list):
    data = data[0] if data else {}
expr = sys.argv[1]
if expr.startswith("m:"):
    data = (data.get("metadata") or {}) if isinstance(data, dict) else {}
    expr = expr[2:]
value = data.get(expr, "") if isinstance(data, dict) else ""
print(value if isinstance(value, str) else "")
' "$2"
}

STEP_JSON="$(gc bd show "$BEAD_ID" --json 2>/dev/null)" || exit 75
ROOT_ID="$(json_field "$STEP_JSON" m:gc.root_bead_id)"
[ -n "$ROOT_ID" ] || not_yet "$BEAD_ID has no gc.root_bead_id"
ROOT_JSON="$(gc bd show "$ROOT_ID" --json 2>/dev/null)" || exit 75

REVIEW_DIR="$(json_field "$ROOT_JSON" m:gc.github.review_dir)"
REPORT="$(json_field "$ROOT_JSON" m:gc.github.review_report_path)"
RECORDED="$(json_field "$ROOT_JSON" m:gc.github.review_outcome)"
[ -n "$REVIEW_DIR" ] || not_yet "workflow root $ROOT_ID has no gc.github.review_dir"
[ -n "$REPORT" ] || not_yet "workflow root $ROOT_ID has no gc.github.review_report_path"
case "$REPORT" in
  "${REVIEW_DIR%/}"/*) ;;
  *) not_yet "report $REPORT is not under this head's review dir $REVIEW_DIR" ;;
esac

OUT="$(python3 "$SCRIPT_DIR/../github_reports.py" review-outcome "$REPORT" 2>&1)" \
  || not_yet "report $REPORT is not a finished review yet: $OUT"
OUTCOME="$(json_field "$OUT" outcome)"
[ "$RECORDED" = "$OUTCOME" ] \
  || not_yet "workflow root $ROOT_ID records gc.github.review_outcome='$RECORDED' but $REPORT gives '$OUTCOME'"
echo "pr review report valid: $REPORT outcome=$OUTCOME"
