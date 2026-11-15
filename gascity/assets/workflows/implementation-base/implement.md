This is the `implementation-base` methodology contract implementation step.

Concrete methodology packs override this step to apply their native
implementation discipline. Work only inside the prepared worktree and preserve
the source anchor for the close step.

Default fallback behavior must still enforce the worktree contract: resolve the
source anchor from workflow metadata, read `work_dir` from that source anchor,
and `cd "$WORKTREE"` before source reads, edits, tests, hashes, or commits.
`gc.work_dir` is the launcher rig root, not the implementation worktree. When
reading beads with `gc bd show --json`, handle both an object and a one-element
list before reading metadata.

Item summary path. Write this item summary at
`<artifact_root>/items/<member_id>/implementation-summary.md`, never at the
build's canonical summary. `member_id` is the source anchor id
(`gc.drain_member_id` on the workflow root when set). `<artifact_root>` is
`gc.var.artifact_root` read from the workflow root, resolved against the
launcher rig root when it is relative; when the root has none, use the directory
of the build root's `gc.build.implementation_summary_path`, and when that is not
resolvable either, `<launcher rig root>/_bmad-output/build`. Create the
directory before writing. A non-empty `summary_path` launch input
(`gc.var.summary_path`) replaces this default unless it equals the canonical
path. Never write the canonical path (`gc.build.implementation_summary_path`),
normally `<artifact_root>/implementation-summary.md`: the `summarize-implementation`
stage owns that file, and an item summary sitting there makes that stage fail
with `canonical_summary_path_occupied`. The path you write is the value you
record as `gc.implementation.summary_path`.

Write the per-item implementation summary as a `gc.build.implementation-summary.v1`
artifact and record its absolute path on the workflow root bead as
`gc.implementation.summary_path` before closing.

The summary body must contain these exact schema-required `##` headings in this
order:

- `## Summary`
- `## Intended Behavior`
- `## Changed Files`
- `## Verification`
- `## Remaining Risks`

Artifact validation: this step is gated by the pack-owned `build-artifact-valid.sh` check, which validates the summary recorded at `gc.implementation.summary_path` (fallback `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. Before closing this step, read the launcher rig root from the workflow root bead's `gc.work_dir` (when the root has none, use `$GC_RIG_ROOT`, which every rig agent session exports; never fail for a missing root `gc.work_dir` alone), then run the same validator locally from that rig root. The validator is the script recorded as `gc.check_path` on the validation loop control bead (the dependent of this step bead whose `gc.kind` is `ralph`); Gas City resolves it to this pack's own `build-artifact-valid.sh` asset, so nothing has to be copied into the rig. Run `GC_BEAD_ID=<claimed-step-id> GC_RIG_ROOT=<launcher-rig-root> "<gc.check_path>"`; fix every reported validation error before setting `gc.outcome=pass`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
