
Read workflow root metadata from `gc bd show <root-bead-id> --json`. Validate the
generic review verdict report at `gc.github.review_report_path` and map it with
`{{pack_root}}/assets/scripts/github_reports.py review-outcome`:
`pass/none -> approve`, `fail/minor -> comment`, `fail/major -> request_changes`,
and `fail/blocker -> block`.

If workflow root metadata has `gc.github.reused_current_output=true`, validate
that `gc.github.comment_path` points to an existing `comment.md` under
`gc.github.review_dir`, verify the review report still maps to the stored
`gc.github.review_outcome`, close this step with `gc.outcome=pass`, and do not
rewrite the rendered comment. Exception: decide it with
`{{pack_root}}/assets/scripts/github_reports.py review-comment-current <review-report.md> <comment.md>`,
which prints `{"current": true|false, "reason": ...}`. When `current` is false
(no `### Findings` section although the report has findings, a `- artifact:`
line with a local filesystem path, or any other drift from the report), the
comment came from an older renderer; re-render it as below and close with
`gc.outcome=pass`. A stale stored comment is never a reason to fail this step.
When `current` is true, leave it alone. This keeps the reused current-head
artifact as a real no-op path.

Render the normal PR comment to `<gc.github.review_dir>/comment.md` with
`{{pack_root}}/assets/scripts/github_reports.py render-review-comment`, passing
the mapped outcome and `gc.github.head_sha`; it renders the report's findings
into the comment. Pass `--artifact-ref` only for a reference a PR reader can
open (never a local filesystem path). Update workflow root metadata with
`gc.github.comment_path=<absolute comment.md path>` and
`gc.github.review_outcome=<approve|comment|request_changes|block>`.
The source PR URL is {{github_pr_url}}.
