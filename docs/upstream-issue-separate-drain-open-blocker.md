# Draft upstream issue: a separate drain launches a member whose blocker is still open

Status: draft only. Do not file it. Filing upstream is the owner's decision
(source bead gp-7zif9, mayor ruling of 2026-11-14, point 4). The pack-side
mitigation is in this repository: see "Pack mitigation" below.

---

## Title

`drain` (context = separate): a member is launched while a `blocks`
dependency on another member is still open, and fails `missing_worktree`

## Summary

A graph.v2 `[steps.drain]` with `context = "separate"` scatters an input
convoy whose members carry a `blocks` edge between them (B blocked by A). The
drain projects that edge onto the item workflows: every bead of B's item
workflow blocks on A's item root (`ensureDrainRowDependencyProjection` /
`ensureDrainWorkflowBlocksOn` in `internal/dispatch/drain.go`). A's item root
closes when A's workflow settles, pass or fail. When A's item fails, its root
closes `fail` while member A stays open (the drain never closes members; only
a passing item's own close step does), so B's item workflow is released with its own `blocks` dependency on A still
open. B's first step then cannot prepare a worktree, every later step fails
`missing_worktree`, and cleanup force-closes the items. The build's source is
left open with no live root.

The mechanism above is read from the code at gc `1.5.1-upstream+dba20336e`.
The incident's item roots and step beads have since been purged by wisp GC, so
the exact release order was not re-read from the store; the observed facts are
listed below.

## Observed (gateway-llm rig store, 2026-11-12)

- Source `gl-xvy8nf` was built with `build-basic`, `drain_policy=separate`.
- Decomposition produced `gl-g8o7yz` and `gl-l6at4k`, with `gl-l6at4k`
  blocked by `gl-g8o7yz`.
- The do-work item root `gl-8ecj9p` for `gl-l6at4k` started while
  `gl-g8o7yz` was open.
- Step `gl-jnlv8b` "Prepare item worktree" failed:
  `gl-l6at4k blocked by gl-g8o7yz (open); no worktree created`.
- "Implement owned work" failed `missing_worktree` three times (`gl-1ko374`,
  `gl-hanrdr`, `gl-c9jx4j`); "Close owned source anchor" `gl-owcba5` failed.
- Workflow cleanup force-closed both items. `gl-xvy8nf` stayed open and
  undelivered with no live root (`gc convoy delete-source` preview:
  `matched_roots=0`).

## Reproduction

1. A city with a v2 formula whose step has
   `[steps.drain] context = "separate"`, `formula = "<item formula>"`, where
   the item formula's first step refuses to run while its member has an open
   `blocks` dependency (the gascity pack's `do-work` prepare-worktree step
   does this: `gc.failure_class=dependency_open`).
2. Create work beads A and B; `gc bd dep add B A` (B depends on A).
3. `gc convoy create repro A B --json`, then sling the drain formula at that
   convoy.
4. Make A's item fail (for example, an implement step that closes
   `gc.outcome=fail`).
5. Observe: A's item root closes `fail`, A stays open, B's item workflow
   becomes ready, B's prepare fails `dependency_open`, and the rest of B's
   workflow fails on the missing worktree.

## Expected core gate

A separate drain must not launch, or release, a member while any `blocks`
dependency of that member is open. Concretely, one of:

- release B only when its blocker member A is closed, not when A's item root
  closes; or
- when A's item root closes with a non-pass outcome and A stays open, close
  B's row `skipped` with a reason such as `blocker_failed:<A>` instead of
  releasing B into a guaranteed failure.

Either way the drain's failure record should name the blocked member and its
blocker, so the parent workflow can report it.

## Consequences today

- Wasted lane runs: the dependent item burns its retry budget on
  `missing_worktree`.
- Forced closes hide the cause: cleanup closes both items, so the convoy reads
  as finished.
- The source stays open with no root and no notice unless the pack writes one.

## Pack mitigation (gascity pack, this repository)

The gascity pack cannot change the drain. It removes the failing shape and
reports the result instead:

- `gascity/assets/workflows/build-basic/decompose.md`: with
  `drain_policy=separate`, decompose never creates a `blocks` edge between
  work items of the implementation convoy. Work that must follow other work is
  folded into one item with ordered tasks; independent items stay separate
  with no edge.
- `gascity/assets/workflows/build-base/summarize-implementation.md` (inherited
  by build-basic) and the fallback in
  `gascity/assets/workflows/build-basic/finalize.md`: when every
  implementation item failed or none was created, the build writes one
  comment, marked `gc-build-failure-notice:<workflow-root-id>`, on each
  original source bead (members of the root's launch convoy
  `gc.var.convoy_id`) naming the workflow root, the failed step and the
  artifact path. The source is left open and never marked delivered.
- Tests: `gascity/tests/test_separate_drain_safety.py`.

## Limits of the pack mitigation

- It prevents the shape only for builds that use these instructions. A convoy
  assembled by hand, or by another decomposer, can still hand a separate drain
  two members joined by a `blocks` edge; only the core gate covers that.
- The notice is written by agent steps that run before `workflow-finalize`
  (summarize-implementation, then finalize as fallback). If the root is
  retired before they run (for example `gc hook --claim` retiring a workflow
  whose input convoy is all closed, the ci-p15n case) or is closed by hand,
  no pack step runs and no notice is written. No pack-owned hook runs after
  root retirement in build-basic today; a `gc.scope_role = "teardown"` step
  could, but build-basic does not declare one.
- Deduplication is read-before-write on the marker. `gc bd comments add` has
  no conditional form, so two writers running at the same moment on the same
  root could each add one comment. Sequential retries and the finalize
  fallback do not duplicate.
