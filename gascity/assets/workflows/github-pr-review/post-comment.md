
Read `gc.github.public_comment_gate`, `gc.github.comment_path`,
`gc.github.head_sha`, and any existing comment metadata from workflow root
metadata. Hard-stop with `gc.outcome=fail` and `gc.failure_class=hard` unless
`gc.github.public_comment_gate` is `approved` or `not_required`; never post when
the gate is `rejected`, `revision_requested`, or missing.

When the gate is `approved`, re-render the comment with the human-approved flag
before posting so the public comment records the approval state. Pass
`--artifact-ref` only for a reference a PR reader can open, never a local
filesystem path. Then create or
update exactly one normal PR comment for this head SHA through
`{{pack_root}}/assets/scripts/github_api.py comment-create "{{github_pr_url}}" --body-file <gc.github.comment_path>` or
`{{pack_root}}/assets/scripts/github_api.py comment-update`. After the create or update succeeds, record on the workflow root
`gc.github.comment_id=<id>`, `gc.github.comment_url=<url>` and
`gc.github.comment_posted_this_run=true`, then close this step with
`gc.outcome=pass`. When `github_api.py` fails transiently (a timeout, a 5xx, a 429),
including the existing-comment lookup, post nothing: a failed lookup never means
"no comment yet", so creating one could post a duplicate. Close this step with
`gc.outcome=fail` and `gc.failure_class=transient`; the step's exec check
(`pr-comment-posted.sh`) then reruns it. Only this step writes `comment_posted_this_run`; a comment
id or url left by an earlier run or by the reuse step does not count. Do not submit formal GitHub
review events in v0.
