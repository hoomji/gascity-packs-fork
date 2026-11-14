Run the build-basic starter factory review loop.

The child beads are three review lanes plus synthesis and fix application:
acceptance/correctness, test evidence, and simplicity/maintainability. These are
starter factory lanes: broad enough to demonstrate Gas City fanout/fanin, but
small enough for first-time factory users to understand.

The apply-review-findings lane owns `code_review.verdict=done|iterate` and
`code_review.report_path=<starter review summary path>`. The implementation
review check repeats this loop until the latest verdict is `done`.

A review lane that finds no review context on the workflow root closes
`gc.outcome=fail` with `gc.failure_class=hard`, which ends this loop in that
attempt: review setup runs before the loop, so another attempt cannot repair it.

Do not invoke provider-native subagents. Continue only through this Gas City
graph loop.

