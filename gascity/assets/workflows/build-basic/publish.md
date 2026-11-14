Use the built-in Gas City publish flow.

Publishing is enabled when push `{{push}}` or open_pr `{{open_pr}}` is `true`; you publish the finalized build-basic result yourself, with `git` and `gh`, in this step. If both are `false`, publishing is disabled: record a no-op publish outcome with the final artifact paths.

`push=true` and `open_pr=true` are the caller's standing authorization to publish.

Resolving the publish inputs: `push`, `open_pr` and `base_branch` are declared by
build-base, and the step's "Formula Variables" block may not list them (it lists
only the variables build-basic declares itself). When a value above is still a
literal `{{...}}` placeholder or is missing from that block, read it from the
workflow root's metadata (`gc.var.push`, `gc.var.open_pr`, `gc.var.base_branch`;
the root is this bead's `gc.root_bead_id`):
`gc bd show <root> --json | jq -r '.[0].metadata["gc.var.push"]'`. A missing key
there means the build-base default (`false`). Never fail the publish because the
block omitted these values. Read the final report and artifact paths the same
way, from the root's `gc.build.*_path` and `gc.artifact_root` metadata.
Never wait for, ask for, or record a human "approve publish" in any interaction
mode, and never close this step unpublished because a final report lists a human
approval as the next action or because no publish script exists under
`assets/scripts`: there is none, and this prompt is the publish procedure.

Publish procedure when publishing is enabled:

1. Read `gc.root_bead_id` from your claimed step bead, then the workflow root.
   Read the implementation convoy id from root metadata `gc.input_convoy_id`,
   its members from `gc convoy status <convoy-id> --json` `.children`, and each
   member's `work_dir` metadata. Drop empties and dedupe: these are the
   implementation worktrees. Hard-fail when there are none.
2. In every worktree, commit what the build left uncommitted before anything
   else. Review-fix edits and fixer output are approved work, not a reason to
   stop:

```bash
git -C "$WORKTREE" add -A
git -C "$WORKTREE" diff --cached --quiet || git -C "$WORKTREE" commit -m "<what the uncommitted edits did>"
```

3. One worktree: its branch is the publish branch. Several worktrees (an
   unstacked decomposition leaves one per task): assemble them onto ONE publish
   branch. Create a branch from the merge base the task branches share with
   `origin/<base branch>`, then cherry-pick each task branch's commits past that
   base (`git cherry-pick <base>..<task-branch>`) in convoy member order. When a
   pick conflicts, resolve it so both tasks' approved behaviour survives; when
   that is not possible, abort that pick and fail the publish naming both tasks.
   Run the proof commands the final report records on the assembled branch; a
   red result fails the publish with the command and its output.
4. With `push=true`, push the publish branch to `origin` (never to a protected
   or base branch, never with `--force`), then confirm
   `git ls-remote origin <branch>` equals the local head.
5. With `open_pr=true`, open one PR for the publish branch against the base
   named under "PR base" below (`gh pr create --base <base> --head <branch>`),
   with a title and body drawn from the final report. If a PR for that head
   already exists, reuse it.
6. Record `gc.publish_outcome=published`, `gc.publish_branch=<branch>`,
   `gc.publish_head=<full sha>` and, when a PR exists, `gc.pr=<PR url>` on both
   your claimed step bead and the workflow root, then close with
   `gc.outcome=pass`.

When any numbered step cannot complete, record `gc.publish_outcome=failed` and
`gc.publish_error=<one line: the command and what it printed>` on your claimed
step bead and the workflow root, and close with `gc.outcome=fail`. A build whose
approved work is not on the remote is never closed `pass`.

For build-basic, a finalized result can be an approved source anchor/worktree.
Do not mark publish failed or downgrade the workflow merely because the launcher
rig root was not mutated. When publishing is disabled, record a `noop` publish
result while preserving the approved build outcome.

`gc.outcome` is the workflow step outcome, not the publish mode. Never set
`gc.outcome=noop`. A disabled/no-op publish is a successful publish step:

```bash
gc bd update "$CLAIMED_BEAD_ID" \
  --set-metadata 'gc.outcome=pass' \
  --set-metadata 'gc.publish_outcome=noop' \
  --set-metadata 'gc.publish_mode=disabled' \
  --set-metadata 'gc.build_outcome=pass' \
  --set-metadata 'gc.final_report=<final report path>' \
  --set-metadata 'gc.artifact_root=<artifact root>'
gc bd close "$CLAIMED_BEAD_ID" --reason 'Publishing disabled; build-basic result approved.'
```

Close only after the push, PR creation, or no-op publish result is recorded.

PR base: when base_branch `{{base_branch}}` is set, every PR targets it and the
pushed branch must share history with `origin/<base_branch>`: `git merge-base HEAD
origin/<base_branch>` must be a commit of that base. A branch that is merely
behind the base tip is publishable as it is: the base moves while a build runs,
and the PR's merge brings it up to date. Never fail the publish, rebase, or
re-verify only because the base has newer commits. Refuse only when there is no
merge base, or when the branch was cut from a different branch. When base_branch
is empty, target the repository default branch. Never retarget an explicit
base_branch.
