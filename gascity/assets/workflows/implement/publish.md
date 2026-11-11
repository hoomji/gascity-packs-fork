
If push {{push}} or open_pr {{open_pr}} are explicit opt-ins, publish only
after the direct implementation summary has completed successfully. Resolve the
publish report from summary_path {{summary_path}} when set; otherwise read the
`gc.implementation.summary_path` value recorded by the summarize step in
workflow root metadata. Fail closed if no absolute summary report path is
available.

Direct implement does not run gap-analysis or review loops. Treat this as an
explicit caller authorization to publish the direct implementation result, and
use the same protected-branch, lease-safe push, sanitized PR title/body, and
collision checks as the pack publish helper. If neither push nor open_pr is an
explicit opt-in, close with `gc.outcome=pass` without mutating remotes.

PR base: when base_branch `{{base_branch}}` is set, every PR targets it and the
pushed branch must share history with `origin/<base_branch>`: `git merge-base HEAD
origin/<base_branch>` must be a commit of that base. A branch that is merely
behind the base tip is publishable as it is: the base moves while a build runs,
and the PR's merge brings it up to date. Never fail the publish, rebase, or
re-verify only because the base has newer commits. Refuse only when there is no
merge base, or when the branch was cut from a different branch. When base_branch
is empty, target the repository default branch. Never retarget an explicit
base_branch.
