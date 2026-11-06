
Read workflow root metadata and write final run metadata containing source bead
id, head SHA, review subject path, review report path, rendered comment path,
GitHub comment id/url, mapped outcome, launch input URL {{github_pr_url}},
artifact root {{artifact_root}}, context path {{context_path}}, post mode
{{post_mode}}, and whether this run reused prior head-SHA output.

The workflow root's outcome must say whether the public comment landed.
When no GitHub comment id and url were recorded on the root (post-comment
hard-stopped, failed, or never ran), write
`gc.github.final_comment_posted=false` plus a one-line
`gc.github.final_note` naming the cause, and close this step and the workflow
root with `gc.outcome=fail`. Never record `gc.outcome=pass` on the root unless
a comment id and url are recorded; a gate of `rejected` or
`revision_requested` is also a fail, because no comment was posted.
