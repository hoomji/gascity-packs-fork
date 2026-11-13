Prepare the authoritative worktree for one shared-drain item.

This step writes named beads besides its claimed step: the workflow root
(`gc.work_dir`, `gc.shared_work_base_branch`) and, inside a build's drain, the parent build
root's `gc.input_convoy_id` (below); nothing here conflicts with "update or close only your claimed bead".

This is infrastructure setup only. Read the claimed step's `gc.root_bead_id`,
read that workflow root bead, and require `gc.drain_member_id`, `gc.drain_index`,
`gc.drain_control_id`, and `gc.work_dir` on it. `gc.drain_member_id` is the
exact source anchor, the item index must be a non-negative integer, and
`gc.work_dir` must resolve to the launcher rig repository root. Do not infer the
source anchor from a dependency and do not use the synthetic input convoy.

If the workflow root has no `gc.work_dir`, record it rather than waiting for it.
That key is back-filled by a reconcile tick for some claimant sessions and
refused for others, so a run in a pooled or ephemeral session never receives it
and the machine check below has nothing to resolve the launcher from. Confirm
your own working directory is the launcher rig repository root — `pwd -P` must
equal the toplevel of the git checkout you are in — then set it with
`gc bd update <root-bead-id> --set-metadata gc.work_dir=<absolute rig root>`.
Record only a directory you verified this way; never a guess.

**Restore the parent's launch convoy (ci-p15n).** A build that decomposes points its workflow
root's `gc.input_convoy_id` at the implementation convoy so the drain can read its members. Once
the drain has saved its manifest it no longer reads that key, but `gc hook --claim` does: when
every member of that convoy is closed it retires the whole workflow, so the summary, review and
publish steps after the drain close `skipped` ("input convoy work already terminal"). Put the
parent back on its launch convoy now, while this item is still open:
- Read `gc.drain_control_id` from this item's workflow root. If it is missing, skip this block.
- Read that drain step bead (`gc bd show <drain-control-id> --json`, unwrap a one-element list)
  and take its `gc.root_bead_id`: that is the parent root. Read the parent root.
- Only when the parent has a non-empty `gc.var.convoy_id`, and its `gc.input_convoy_id` equals
  its `gc.build.implementation_convoy_id` and differs from `gc.var.convoy_id`, run
  `gc bd update <parent-root-id> --set-metadata gc.input_convoy_id=<parent gc.var.convoy_id>`.
  In every other case write nothing. A second item finds the key already restored and writes
  nothing.

The base branch is base_branch `{{base_branch}}`. When it is non-empty and the
workflow root has no `gc.shared_work_base_branch`, set it with
`gc bd update <root-bead-id> --set-metadata gc.shared_work_base_branch={{base_branch}}`.
The machine check then cuts a new shared worktree from `origin/{{base_branch}}`
instead of the remote default branch, and fails rather than falling back when
origin lacks it. When base_branch is empty, record nothing.

Do not read, edit, test, stage, or commit product source in this step. Its
machine check creates or reuses the one deterministic shared git worktree for
this drain, based on the freshly fetched remote default branch, verifies that it
belongs to the launcher repository and differs from the launcher checkout, and
persists `work_dir` on the current source anchor. Every later item in the drain
reuses that same worktree, so it is created once and never per item.

Close with `gc.outcome=pass` only after the metadata is unambiguous; the check
fails closed if setup or read-back verification does not succeed.

Do not invoke provider-native subagents. Gas City owns the shared-drain
lifecycle.
