This is the `build-from-review-base` publish stage.

Read push {{push}}, open_pr {{open_pr}}, and the finalized continuation outcome
from the workflow root metadata. If neither publishing action is explicitly
authorized, no-op and record `not_published`.

Publishing disabled or no-op status must never convert a blocked, failed, or
repairable finalization into a passing workflow outcome. Preserve
`gc.outcome=fail`, `gc.build.status=blocked`, `gc.failure_class`, and
`gc.restart.*` metadata when finalize recorded them.

If publishing is authorized, publish only after the continuation finalized
successfully and the review stage approved or explicitly allowed publication.
Record push status, PR status, or a blocked publish reason on the workflow root
and publish step before closing.

PR base: when base_branch `{{base_branch}}` is set, every PR targets it and the
pushed branch must share history with `origin/<base_branch>`: `git merge-base HEAD
origin/<base_branch>` must be a commit of that base. A branch that is merely
behind the base tip is publishable as it is: the base moves while a build runs,
and the PR's merge brings it up to date. Never fail the publish, rebase, or
re-verify only because the base has newer commits. Refuse only when there is no
merge base, or when the branch was cut from a different branch. When base_branch
is empty, target the repository default branch. Never retarget an explicit
base_branch.
