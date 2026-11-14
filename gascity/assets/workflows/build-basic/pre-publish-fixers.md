Run the rig's mechanical fixers in every implementation worktree after the build finalized and before the publish step pushes or opens a PR. Command: `{{pre_publish_command}}` (rig policy, set as a rig default; this step only exists when it is non-empty).

If push is not `true` and open_pr is not `true`, run nothing: record `gc.pre_publish_outcome=noop` and close with reason `NOOP pre-publish fixers disabled (push=false open_pr=false)`. Fixers exist to make the push clean; with no push and no PR there is nothing to fix.

Otherwise resolve the implementation worktrees from the implementation convoy (the same members `prepare-shared-worktree` stamped):

1. Read `gc.root_bead_id` from your claimed step bead; read that workflow root. If `gc bd show --json` returns a one-element list, unwrap the first element before reading metadata.
2. Resolve the implementation convoy id from root metadata: `gc.build.implementation_convoy_id` when it is present and non-empty, else `gc.input_convoy_id` only when that key is absent or empty (a separate drain restores `gc.input_convoy_id` to the launch convoy, ci-p15n); hard-fail when neither is set, and never fall through to `gc.input_convoy_id` when `gc.build.implementation_convoy_id` is set. Read its members from `gc convoy status <convoy-id> --json` `.children`; hard-fail when there are none. Members are the source anchors. Never treat the convoy itself, or a synthetic wrapper convoy, as a source anchor. Every hard-fail here names both values: `no implementation worktree resolvable from gc.build.implementation_convoy_id <id|missing> / gc.input_convoy_id <id|missing>`; a lookup hard-fail records `gc.pre_publish_outcome=failed` and `gc.pre_publish_error` and closes `gc.outcome=fail`.
3. Read each member with `gc bd show <member-id> --json` and collect `work_dir` metadata; drop empties, dedupe, sort. Every surviving path must be an existing git worktree (`git -C <path> rev-parse --is-inside-work-tree`). Hard-fail on a missing or non-worktree path instead of skipping it: a silent skip would publish unfixed code.
4. Set the base the fixers compare against: base_branch `{{base_branch}}` when it is set, else each worktree's remote default branch (do not hardcode `main`):

```bash
BASE_BRANCH="{{base_branch}}"
if [ -z "$BASE_BRANCH" ]; then
  BASE_BRANCH=$(git -C "$WORKTREE" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
fi
[ -n "$BASE_BRANCH" ] || { echo "pre-publish: no base branch"; exit 1; }
BASE_REF="origin/$BASE_BRANCH"
export BASE_BRANCH BASE_REF
```

Never fall back to the launcher's local `HEAD`, which may be behind `origin`.

In each worktree in sorted order, with the worktree as the working directory and `BASE_BRANCH`/`BASE_REF` exported, run the rig command and capture its output:

```bash
{{pre_publish_command}}
```

- On the FIRST nonzero exit, stop: do not run the remaining worktrees and do not commit anywhere. Record `gc.pre_publish_outcome=failed` and `gc.pre_publish_error=<worktree: last 5 output lines>` on your claimed bead, comment the full output on the workflow root, and close with `gc.outcome=fail`. The publish step needs this step, so a failed close blocks the push and the PR. Never invent a fix for the rig command; the output names it.
- After a clean run in a worktree, when `git status --porcelain` is non-empty there, add exactly ONE follow-up commit for everything the fixers changed in that worktree:

```bash
git add -A
git commit -m "pre-publish fixers" -m "Mechanical fixers on the lane diff before publish (pre_publish_command)."
git show --stat --oneline HEAD
```

Comment the stat on the workflow root. Never amend an implementation commit: fixer commits stay separate so review sees what the build wrote and what the fixers changed.

When every worktree ran clean, record `gc.pre_publish_outcome=fixed` (any worktree changed) or `clean` (none changed) plus `gc.pre_publish_worktrees=<sorted paths, space-separated>` on your claimed bead, and close with `gc.outcome=pass` and reason `PRE-PUBLISH fixed|clean over <N> worktrees`.

Never run `git push` here; the publish step pushes.
