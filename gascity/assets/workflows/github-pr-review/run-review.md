Read the current step bead metadata, get `gc.root_bead_id`, then read workflow
root metadata with `gc bd show <root-bead-id> --json`. Required workflow root
metadata keys are `gc.github.source_bead_id`, `gc.github.repo`,
`gc.github.number`, `gc.github.url`, `gc.github.head_sha`,
`gc.github.snapshot_path`, and `gc.github.review_dir`.

This step has an exec check
(`{{pack_root}}/assets/scripts/checks/pr-review-report-valid.sh`). Closing
this step does not finish it: the check passes only when the workflow root
records `gc.github.review_report_path` under `gc.github.review_dir`, that
report validates through `github_reports.py review-outcome`, and the root's
`gc.github.review_outcome` matches it. Otherwise the check spends an attempt.

If workflow root metadata has `gc.github.reused_current_output=true`, do not
launch the generic `review` formula. Instead validate the reused
`gc.github.review_report_path` with
`{{pack_root}}/assets/scripts/github_reports.py review-outcome`, verify it
lives under `gc.github.review_dir`, refresh `gc.github.review_outcome` from the
validator result, close this step with `gc.outcome=pass`, and leave the reused
artifacts untouched. This is the no-op path that makes current-head reuse
effective even though the formula graph still schedules this step.

Create the deterministic generic-review handoff artifacts for this head SHA:

- `SUBJECT_PATH=<gc.github.review_dir>/subject.md`
- `REPORT_PATH=<gc.github.review_dir>/review-report.md`

Write `SUBJECT_PATH` as a Markdown review subject that includes the PR URL
{{github_pr_url}}, repo, PR number, head SHA, snapshot JSON path, and explicit
instructions to review the PR diff/head for correctness, tests, security,
maintainability, and release risk. Keep large payloads in artifact files; the
subject may point to the snapshot instead of embedding it. Record both paths on
the workflow root before launching:
`gc bd update <root-bead-id> --set-metadata gc.github.review_subject_path="$SUBJECT_PATH" --set-metadata gc.github.review_report_path="$REPORT_PATH"`.

Launch the selected targetless code-review methodology formula onto the
workflow root, with explicit paths. The default is `review`; toolkit adapters
may override `code_review_formula` without changing GitHub snapshot, comment,
or finalize behavior. Compatibility with the requested modes was validated at
the snapshot gate. Pass review_mode {{review_mode}} and interaction_mode
{{interaction_mode}} through when the selected formula accepts them; the PR
adapter itself never mutates code regardless of review mode.

```bash
gc sling gc.run-operator <root-bead-id> --on {{code_review_formula}} --json \
  --var context_path="{{context_path}}" \
  --var subject_path="$SUBJECT_PATH" \
  --var report_path="$REPORT_PATH" \
  --var interaction_mode="{{interaction_mode}}" \
  --var review_mode="{{review_mode}}"
```

If the selected formula does not declare the mode vars, omit the two mode
`--var` arguments rather than failing the launch.

The launch is attached to this PR workflow's root, which is one PR head, and gc
keeps at most one live workflow per source bead:

- Exit 0: the JSON `workflow_id` is the review workflow root. Record it with
  `gc bd update <root-bead-id> --set-metadata gc.github.review_root_id=<workflow_id>`.
- Exit 3 with `source bead <root-bead-id> already has live workflow(s): <ids>`
  on stderr: this head's review is already running (an earlier visit to this
  step launched it). Record that id as `gc.github.review_root_id` and wait on
  it. Never pass `--force`: it replaces the running review.
- Any other failure: close this step with `gc.outcome=fail` and the gc error in
  `gc.failure_reason`.

Wait until the review workflow root (`gc.github.review_root_id`) is closed,
checking it with `gc bd show <review-root-id> --json`. Do not close this step
while it is open: the check would find no report and spend an attempt.

When the review root has closed and `REPORT_PATH` validates through
`{{pack_root}}/assets/scripts/github_reports.py review-outcome "$REPORT_PATH"`,
record the outcome with
`gc bd update <root-bead-id> --set-metadata gc.github.review_outcome=<approve|comment|request_changes|block>`
and close this step with `gc.outcome=pass`. When the review root closed without
a valid report, close this step with `gc.outcome=fail` and
`gc.failure_class=transient`; the check then decides whether another attempt
launches a fresh review.

The adapter does not check out a mutation worktree, push commits, amend
contributor branches, submit formal GitHub review events, or create follow-up
PRs.
