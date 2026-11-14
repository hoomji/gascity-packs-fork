Review the plan yourself, inside this step. Do not launch the `design-review` formula, sling a
bead, or start any other workflow: a nested review needs its own convoy and this step has none.

Run a plan review against the implementation plan. A required change is a blocker for
decomposition. Resolve every blocker in the plan: edit the plan artifact until the finding no
longer holds, then re-read the edited section. The decompose step refuses a plan that still
carries a blocker, so a finding you only write down stops the build there.

Include a lightweight implementation readiness pass before decomposition:

- requirements traceability: every major plan task maps to acceptance criteria
- task boundaries: each task can become a clear implementation bead
- test commands: the plan names the focused proof commands or test strategy
- risk: risky files, migrations, public interfaces, and rollback concerns are
  explicit enough for an implementer

If you write a plan-readiness note, record it on the workflow root as
`gc.build.plan_review_report_path=<path>`. Do not write or overwrite
`gc.build.review_report_path`; that key is reserved for the later
build-basic implementation review artifact.

Close with `gc.outcome=pass` only when no blocker remains in the plan:
`gc bd update "<claimed-step-id>" --set-metadata "gc.outcome=pass"`, then
`gc bd close "<claimed-step-id>" --reason "<concise reason>"`.

If a blocker cannot be resolved in the plan (it needs a decision or a fact this step cannot
get), do not pass. Set `gc.outcome=fail`, `gc.failure_class=hard` and
`gc.failure_reason=<the blocker, one line>` with `gc bd update "<claimed-step-id>"
--set-metadata ...`, then close with the same blocker as the reason.

Do not pass `--metadata` or `--set-metadata` to `gc bd close`.
