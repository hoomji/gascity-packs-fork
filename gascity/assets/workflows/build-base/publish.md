This is the `build-base` publish stage. Treat it as a virtual contract that concrete formulas may override.

If `push` or `open_pr` is enabled, publish the finalized build result according to the workflow metadata. If publishing is disabled, record the exact reason and leave the artifacts ready for a later publisher.

Write a publish result artifact under the workflow artifact root when one is
available. Record the same publish outcome on the workflow root bead and this
publish step before closing.

Required workflow root metadata:

- `gc.build.publish_status=published|noop|failed`
- `gc.build.publish_action=push|pr|push_pr|noop|failed`
- `gc.build.publish_recorded_at=<UTC timestamp>`
- `gc.build.publish_artifact_path=<publish result artifact path>`
- `gc.build.publish_reason=<short machine-readable reason>`

For disabled publishing, use `gc.build.publish_status=noop`,
`gc.build.publish_action=noop`, and a reason such as
`push=false_open_pr=false`. Also record whether remotes were present with
`gc.build.publish_remote_status`.

Close this step only after the publish action or explicit no-op is recorded on
both the workflow root and the publish step.

PR base: when base_branch `{{base_branch}}` is set, every PR targets it and the
pushed branch must share history with `origin/<base_branch>`: `git merge-base HEAD
origin/<base_branch>` must be a commit of that base. A branch that is merely
behind the base tip is publishable as it is: the base moves while a build runs,
and the PR's merge brings it up to date. Never fail the publish, rebase, or
re-verify only because the base has newer commits. Refuse only when there is no
merge base, or when the branch was cut from a different branch. When base_branch
is empty, target the repository default branch. Never retarget an explicit
base_branch.
