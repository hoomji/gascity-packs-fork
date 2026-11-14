Write the canonical build implementation summary.

This build-base stage may be inherited by concrete build methodology packs.
Concrete build methodology packs may override this stage, but any override must
preserve the root implementation-summary artifact contract.

The implementation drain may write one or more per-item summaries from source
worktrees. This stage converts that implementation evidence into the root
workflow artifact recorded as `gc.build.implementation_summary_path`, normally
`implementation-summary.md` under the build artifact root.

Resolve the workflow root bead and artifact root from root metadata. If
`gc.build.implementation_summary_path` is empty, derive an absolute path under
`gc.var.artifact_root` or `gc.build.artifact_root` as
`implementation-summary.md`, then record it on the workflow root:

`gc bd update "<workflow-root-id>" --set-metadata "gc.build.implementation_summary_path=<absolute path>"`

Do not use `gc bd update --metadata 'key=value'`; `--metadata` only accepts a JSON
object.

Collect the closed implementation source anchors and drain child workflows from
the implementation convoy. Read their recorded implementation summary paths
from `gc.implementation.summary_path`, `gc.build.implementation_summary_path`,
or `gc.var.summary_path`. Include those summaries as upstream evidence. If an
item summary is missing coverage IDs that appear in the requirements artifact,
read the requirements, decomposition, review context, and verification evidence
before writing the canonical root summary. The canonical summary must cover all
accepted requirement IDs that the build finalized.

Write the artifact as Markdown with YAML front matter, not JSON. Use mapping objects for front matter; do not use scalar shortcuts such as
`workflow: build-basic`. The top-level YAML shape must be:

- `schema: gc.build.implementation-summary.v1`
- `workflow: {id: <workflow-root-id>, formula: <root-workflow-formula>}`
- `methodology: {pack: <pack-name>, name: <build-formula>}`
- `producer: {formula: <build-formula>, stage: summarize-implementation, attempt: <positive integer>}`
- `status: approved` or another schema-allowed status
- `trace: {upstream: [...], coverage: [...]}`

Trace front matter must use the validator shape exactly:

- `trace.upstream[]` entries must include `path` and `hash`; do not use
  `id`/`title`/`type` entries as the upstream shape.
- For upstream build artifacts or implementation summaries, use their recorded
  paths and scheme-qualified hashes such as `sha256:<digest>`. For convoy or
  bead inputs, use `path: beads/<bead-id>` and `hash: bead:<bead-id>`.
- If an upstream entry lists `ids`, every listed id must appear exactly once in
  `trace.coverage` and in the Markdown coverage table with the same status.
- Coverage statuses are not artifact statuses. Use `covered` for satisfied
  requirements; do not use `approved` in `trace.coverage[].status` or the
  Markdown coverage table.

Include a Markdown coverage table whose ID/status pairs exactly match
`trace.coverage`. The validator only recognizes a Markdown table with an `ID`
column and a `Status` column. Use this shape:

| ID | Status |
| --- | --- |
| REQ-001 | covered |

The body must include these schema-required sections:

- Summary
- Intended Behavior
- Changed Files
- Verification
- Remaining Risks

In those sections, include the implementation convoy id, source anchor ids,
per-item summary paths, changed files, first verification commands, final proof
commands, observed pass/fail results, and remaining risks. Keep the root
summary concise, but do not omit accepted requirement IDs.

**Source failure notice (gp-7zif9).** This stage runs once the drain has
closed, whether the drain passed or failed, and before `workflow-finalize`
retires the workflow root. It is therefore the pack's notice point for a build
that delivered nothing: a build whose items all failed, or that created no
item, must not leave its source silently open. Besides the root metadata and
your claimed step, this step makes one more named write: at most one comment
on each original source bead. Decide the build's result class first:

1. Find the implementation drain step: the closed step bead of this workflow
   root whose `gc.step_id` ends in `.implement` or `.implement-same-session`
   (read it with `gc bd show <drain-step-id> --json`, unwrapping a one-element
   list). Its `gc.drain_manifest.v1` rows list each item's `member_id`,
   `item_root_id`, `status`, `outcome` and `failure_reason`.
2. **Zero items created:** the root has no `gc.build.implementation_convoy_id`,
   that convoy has no members, the manifest has no rows, or the drain closed
   with `gc.failure_reason=predecessor_failed`. The failed step is the drain's
   `gc.failure_subject` when set (normally the decompose step), otherwise the
   decompose step bead of this root. The artifact path is
   `gc.build.decomposition_path` (fallback `gc.var.decomposition_path`), or the
   plan path when decomposition never wrote one. This case needs no item and
   no convoy.
3. **All items failed:** the manifest has one or more rows and no row has
   `outcome` `pass`. A closed item root or a closed source anchor is not a
   success: workflow cleanup force-closes failed items, so only a row whose
   `outcome` is `pass` counts. For each failed row, the failed step is the
   first step bead under its `item_root_id` that closed `gc.outcome=fail`
   (its id, title and `gc.failure_class` or close reason). The artifact path is
   the item's per-item summary path or the source anchor's `work_dir`, and the
   canonical summary path written above.
4. **Any item passed:** write no source notice.

In either failure case, resolve the original source from the workflow root's
launch convoy `gc.var.convoy_id`: its members
(`gc convoy status <launch-convoy-id> --json`, `.children`) are the original
source beads. Never use the members of `gc.build.implementation_convoy_id`;
those are the build's own work items. Do not read the source from
`gc.input_convoy_id`, which decompose may have pointed at the implementation
convoy. If `gc.var.convoy_id` is empty, write no comment and record
`no original source resolved` under Remaining Risks.

For each original source bead, write the notice at most once per workflow:

- Read its comments first: `gc bd comments <source-id> --json`. If any comment
  text contains the marker `gc-build-failure-notice:<workflow-root-id>`, write
  nothing: a retry of this step or the finalize step already wrote it.
- Otherwise put the notice in a file and add it with
  `gc bd comments add <source-id> -f <notice-file>`. Its first line is the
  marker `gc-build-failure-notice:<workflow-root-id>`; then name the workflow
  root id, the result class (`all <N> implementation items failed` or
  `no implementation item was created`), the failed step bead id, title and
  failure class or reason, the artifact path, the canonical implementation
  summary path, and the line `Source left open and not delivered.`
- Leave the source open and undelivered: never close it, never set
  `gc.outcome` or any delivery metadata or label on it, and never mark it
  delivered. Workflow finalize leaves the source open on a failed root, and
  this step must not change that.
- Set this summary's `status` to `blocked`, not `approved`, and name the
  comment marker (written, or already present) under Remaining Risks.

The comment on the source is the durable record: it stays readable after the
root closes or is purged. The read-then-write check is not atomic, because
`gc bd comments add` has no conditional form. It removes duplicates across
sequential retries of this step and the finalize fallback, but two writers
running at the same moment on the same root could each add one.

Before closing this step, read the launcher rig root from the workflow root bead's `gc.work_dir` (when the root has none, use `$GC_RIG_ROOT`, which every rig agent session exports; never fail for a missing root `gc.work_dir` alone), then run the same validator locally from that launcher rig root. The validator is the script recorded as `gc.check_path` on the validation loop control bead (the dependent of this step bead whose `gc.kind` is `ralph`); Gas City resolves it to this pack's own `build-artifact-valid.sh` asset, so nothing has to be copied into the rig:

`GC_BEAD_ID=<claimed-step-id> GC_RIG_ROOT=<launcher-rig-root> "<gc.check_path>"`

fix every reported validation error before setting `gc.outcome=pass`. Then set
the claimed step outcome with
`gc bd update "<claimed-step-id>" --set-metadata "gc.outcome=pass"`, and close
with `gc bd close "<claimed-step-id>" --reason "<concise reason>"`. Do not pass
`--metadata` or `--set-metadata` to `gc bd close`.

Artifact validation: this stage is gated by the pack-owned `build-artifact-valid.sh` check, which validates the artifact recorded at `gc.build.implementation_summary_path` against schema `gc.build.implementation-summary.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the artifact.
