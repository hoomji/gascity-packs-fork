
Read workflow root metadata and write final run metadata containing the source
bead id, body hash, triage report path, rendered comment path, GitHub comment
id/url, verdict, priority, recommended next action, launch input URL
{{github_issue_url}}, artifact root {{artifact_root}}, post mode {{post_mode}},
and whether this run reused prior body-hash output.

The workflow root's outcome must say whether the public comment landed in
this run. When the root does not carry `gc.github.comment_posted_this_run=true`
(post-comment hard-stopped, failed, or never ran; a comment id or url from an
earlier run or the reuse step does not count), write
`gc.github.final_comment_posted=false` plus a one-line `gc.github.final_note`
naming the cause, and close this step with `gc.outcome=fail`. Close only this
step: the workflow root's outcome follows from it, so do not close the root
yourself. Never record `gc.outcome=pass` while that key is missing; a gate of
`rejected` or `revision_requested` is also a fail, because no comment was
posted.
