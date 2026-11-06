
Resolve `<source-anchor-id>` from the workflow ROOT, which is the SINGLE SOURCE
OF TRUTH for every step of this lane: read the claimed step bead's
`gc.root_bead_id`, then read that root's `gc.source_anchor_id` metadata.
`prepare-worktree` resolved the anchor deterministically and stamped it there,
so DO NOT re-derive it — close EXACTLY that id, and use exactly that value as
`<source-anchor-id>` everywhere below (worktree resolution AND every
`gc bd show` / `gc bd update --set-metadata` that names the source anchor).

FALLBACK — only if the root has NO `gc.source_anchor_id` (a workflow started
before `prepare-worktree` stamped it, or a hand-run step where
`prepare-worktree` never ran): derive it exactly as `prepare-worktree` does —
read the root's `gc.input_convoy_id` (if it is missing too, fail this step
without closing any bead) and that convoy with `gc bd show <input-convoy-id>
--json`. If the convoy has `gc.synthetic_kind=drain-unit-convoy`
use its `gc.drain_member_id`; else if it has `gc.synthetic=true` use its single
tracked member from `gc convoy status <input-convoy-id> --json` (hard-fail
unless `.children` has exactly one entry); otherwise use the input convoy id
itself. For such an unstamped single-item run, a pre-stamp `prepare-worktree`
persisted `work_dir` on the `gc.synthetic=true` input convoy, so when the
member has no `work_dir`, read `work_dir` from that convoy — but still close the
member, never the convoy. Never infer the anchor from dependency ids such as
the `prepare-worktree` or implementation step bead.

Before closing anything, sanity-check the resolved id (stamped or derived) and
fail this step without closing any bead if it does not hold: the source anchor
must not have `gc.synthetic=true`, and when the root has `gc.drain_member_id`
the source anchor must equal it.

Read `work_dir` from the source anchor and verify the implementation commit is
present in that worktree. Then resolve the summary evidence, taking the FIRST
candidate that names an existing file (a relative path is tried against the
worktree, then against the launcher rig root `gc.work_dir` / `$GC_RIG_ROOT`):

1. `{{summary_path}}` when set.
2. The workflow root's `gc.implementation.summary_path` (implement records the
   absolute path there).
3. `gc.implementation.summary_path` on the implement ITERATION beads of this
   root, newest first: `gc bd list --all --json --metadata-field
   gc.root_bead_id=<root-bead-id> --metadata-field gc.ralph_step_id=implement
   --has-metadata-key gc.implementation.summary_path`. Your `needs` dependency
   is the `implement` control bead (kind `ralph`), which never carries the
   path; formula-spec-v2 "check" materialization puts the work on
   `implement.iteration.N` (gl-rzkx2y, 2026-11-05).
4. The old default `{{artifact_root}}/task-<source-anchor-id>-summary.md`.

The summary may live outside the worktree (for example under the rig root);
that is valid evidence once the file exists. Fail with
`gc.failure_class=missing_summary_evidence` only when no candidate exists, and
list every path you tried in `gc.failure_reason`.

When reading beads with `gc bd show --json`, handle both an object and a
one-element list before reading metadata. `gc.work_dir` is the launcher rig
root, not the implementation worktree. If the source anchor `work_dir` (or,
in the unstamped single-item case above, the input convoy's) is missing, equals the launcher root, or points at a worktree without the
implementation commit, fail this step instead of closing the source anchor.

Delivery: require_delivery is `{{require_delivery}}`. When it is `true` and the
root has no `gc.drain_control_id` (a drain item's delivery belongs to the
workflow that drained it), the lane's commit must have left the host before you
close the source anchor: `git -C <work_dir> fetch origin`, then the worktree
HEAD must be on an origin branch other than `{{base_branch}}` (the remote
default branch when empty) per `git -C <work_dir> branch -r --contains HEAD`,
or in an open or merged PR per `gh pr list --state all --search <HEAD sha>`.
If it is not, fail this step with `gc.failure_class=undelivered` and leave the
source anchor open. The exec check `do-work-delivered.sh` runs the same test
after you close this step and keeps the step from passing either way.

If the source anchor is already `status=closed` with `gc.outcome=pass` (a retry
of this step after the close landed), do not close it again; verify the
evidence and close this step.

Every path above that fails this step leaves the source anchor open. This step's
named writes are the source-anchor close on success and, on failure, one write
to the workflow root, so
nothing here conflicts with "update or close only your claimed bead".
Before you close this step failed, run that root write:
`gc bd update <root-bead-id> --set-metadata gc.work_outcome=blocked`. A drain
wires the item workflows of the anchors that depend on this one to this root,
and gc's readiness treats a closed blocker with `gc.work_outcome=blocked` as
unsatisfied, so those items stay out of `gc ready` instead of starting on an
anchor whose blocker never closed (gl-c2tps2, 2026-11-05: this root closed
`gc.outcome=fail` with its anchor gl-10egi9 open, which released the dependent
item for gl-thh95d). Never write it on success.

On success, close only `<source-anchor-id>` with `gc.outcome=pass`. Include the
verified commit and summary path in the source-anchor close reason. Read the
source anchor back with `gc bd show <source-anchor-id> --json` and verify
`status=closed` and `gc.outcome=pass`; if either check fails, fix the source
anchor before closing this step. Do not close this step with pass while the source anchor remains open. Then close this step. Do not close the drain-unit
convoy, parent convoy, or broader workflow root from this step.
