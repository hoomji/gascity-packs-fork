This is the `implement` shared-worktree step.

Cut the one shared worktree a same-session drain runs in. This is
infrastructure setup only. Do not edit source files in the launcher checkout.

A shared drain runs every convoy member, one at a time, in a single lane. Each
item reads its worktree from its source anchor's `work_dir` and refuses to run
without one (see `do-work-item`), and core shared drain creates no worktree. This
step creates that worktree once for the whole convoy and records it on every
member, so items build on each other's changes in drain order.

1. Read current step bead metadata and get `gc.root_bead_id`; hard-fail if it is
   missing. Read that workflow root with `gc bd show <root-bead-id> --json`. If
   `gc bd show --json` returns a one-element list, unwrap the first element
   before reading metadata.
2. Read the implementation convoy id from root metadata `gc.input_convoy_id`;
   hard-fail if it is missing. Earlier steps record it there before any drain
   runs, so do not search repo, plan, report, or session files for convoy ids.
   Read its members from `gc convoy status <convoy-id> --json` `.children`;
   hard-fail if there are none. Members are the source anchors. Never treat the
   convoy itself, or a synthetic wrapper convoy, as a source anchor.
3. Set `WORKTREE=$(pwd)/worktrees/<convoy-id>`.
   - If the root already has `gc.shared_work_dir` (a retry), it must equal
     `$WORKTREE` and the path must be a worktree of this repository; reuse it
     and go to step 4. Hard-fail on a mismatch instead of overwriting it.
   - If anything else already exists at that path, fail closed.
   - Otherwise resolve the base branch: base_branch `{{base_branch}}` when it
     is set, else the remote default branch (do not hardcode `main`). For the
     default, read the local ref first, and only touch the network if it is
     missing:

     ```sh
     BASE_BRANCH="{{base_branch}}"
     if [ -z "$BASE_BRANCH" ]; then
       DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
       if [ -z "$DEFAULT_BRANCH" ]; then
         git remote set-head origin --auto >/dev/null 2>&1 || true
         DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
       fi
       BASE_BRANCH=$DEFAULT_BRANCH
     fi
     ```

     If `BASE_BRANCH` is still empty, fail closed.
     Never fall back to the launcher's local `HEAD`, which may be behind `origin`.
   - Fetch it so the base is current: `git fetch --prune origin "$BASE_BRANCH"`.
     If base_branch was set and origin has no such branch, fail closed; never
     substitute the remote default branch for an explicit base.
   - Create the worktree detached at the freshly fetched tip:
     `git worktree add "$WORKTREE" --detach "origin/$BASE_BRANCH"`.
4. Record the worktree and its base on the root:
   `gc bd update <root-bead-id> --set-metadata gc.shared_work_dir=$WORKTREE --set-metadata gc.shared_work_base=<base commit sha> --set-metadata gc.shared_work_base_branch=$BASE_BRANCH`.
5. On every member, persist the absolute path:
   `gc bd update <member-id> --set-metadata work_dir=$WORKTREE`.
   If a member already records a different `work_dir` that still exists, fail
   closed and name it rather than moving that member's work. Never write
   `work_dir` on a convoy.
6. Read the beads back. Verify the root has `gc.shared_work_dir` and every
   member has `work_dir=$WORKTREE` before closing this step with
   `gc.outcome=pass`.
