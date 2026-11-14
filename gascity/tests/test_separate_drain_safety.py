"""gp-7zif9: a build-basic separate drain started a decomposed item while its blocker was open.

Evidence (gateway-llm store, 2026-11-12): source gl-xvy8nf decomposed into gl-g8o7yz and
gl-l6at4k, with gl-l6at4k blocked by gl-g8o7yz. The separate drain started both item roots at
once; gl-l6at4k's prepare step failed dependency_open, implement failed missing_worktree three
times, cleanup force-closed both items, and the source was left open with no root and no notice.
Builds gp-fnnvl (zero items: decompose failed plan_not_ready) and gcg-970753 (its one item
failed) then ended the same way: the source stayed open with no comment saying why.

The drain gate itself is gc core and out of scope (docs/upstream-issue-separate-drain-open-blocker.md).
These tests pin the pack-owned mitigation: decompose never hands a separate drain two items joined
by a blocks edge, and a build that delivered nothing leaves one deduplicated comment on its source.
"""

from __future__ import annotations

import pathlib
import tomllib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
DECOMPOSE = "assets/workflows/build-basic/decompose.md"
SUMMARIZE = "assets/workflows/build-base/summarize-implementation.md"
FINALIZE = "assets/workflows/build-basic/finalize.md"
MARKER = "gc-build-failure-notice:<workflow-root-id>"


def flat(rel: str) -> str:
    """Prompt text with whitespace collapsed, so assertions do not depend on line wrapping."""
    return " ".join((ROOT / rel).read_text(encoding="utf-8").split())


def steps_by_id(formula: str) -> dict[str, dict]:
    data = tomllib.loads((ROOT / "formulas" / f"{formula}.formula.toml").read_text(encoding="utf-8"))
    return {step["id"]: step for step in data.get("steps", [])}


class SeparateDrainDecomposeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = flat(DECOMPOSE)

    def test_forbids_blocks_edges_between_separate_drain_items(self) -> None:
        self.assertIn("`gc.var.drain_policy` is `separate`", self.text)
        self.assertIn("Never create a `blocks` edge between two work items of this implementation convoy", self.text)
        # Every way the decomposer could mint such an edge is named, so none reads as allowed.
        for command in ("`gc bd dep add`", "`gc bd dep <id> --blocks <id>`", "`--deps`"):
            with self.subTest(command=command):
                self.assertIn(command, self.text)

    def test_no_longer_presents_dependent_items_as_normal(self) -> None:
        # The old text told the decomposer how failure propagates to dependent items, which
        # presented inter-item blocks edges as an ordinary part of a separate-drain decomposition.
        self.assertNotIn("blocks every item that depends on it", self.text)

    def test_folds_ordered_work_into_one_item_and_keeps_independent_items_separate(self) -> None:
        self.assertIn("Fold work that must follow other work in this build into ONE work item", self.text)
        self.assertIn("numbered list in execution order (the evidence first, then the fix)", self.text)
        self.assertIn("never encode their order as bead edges", self.text)
        self.assertIn("Independent tasks", self.text)
        self.assertIn("may stay separate work items, with no edge between them", self.text)

    def test_verifies_and_records_no_edges_before_the_convoy(self) -> None:
        check = self.text.index("Before creating the convoy, read each new work item")
        self.assertIn("`dependency_type=blocks`", self.text[check:])
        self.assertIn("`gc bd dep remove <work-item-id> <other-work-item-id>`", self.text)
        self.assertIn("`Dependency edges among members: none.`", self.text)
        # The check sits before the create-items-then-convoy protocol, which is unchanged.
        convoy_flow = self.text.index("Use the convoy creation flow exactly")
        self.assertLess(check, convoy_flow)
        self.assertIn("Create work-item beads first, then create a new implementation convoy", self.text)
        self.assertIn("`gc convoy create <name> <work-item-id...> --json`", self.text)

    def test_keeps_the_commit_per_item_rule(self) -> None:
        self.assertIn("Every work item must end in a commit", self.text)
        self.assertIn("is never its own work item", self.text)


class SourceFailureNoticeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = flat(SUMMARIZE)

    def test_notice_point_is_reached_after_a_failed_drain(self) -> None:
        # The notice lives in summarize-implementation because build-basic inherits that step from
        # build-base and it needs both drain variants unconditionally: graph.v2 needs edges are
        # blocks edges, so a drain that closed fail still releases it (observed: gcg-970767 ran
        # after drain gcg-970765 failed; gp-fnnvl's summary ran after its drain closed
        # predecessor_failed).
        self.assertNotIn("summarize-implementation", steps_by_id("build-basic"))
        step = steps_by_id("build-base")["summarize-implementation"]
        self.assertEqual(set(step["needs"]), {"implement", "implement-same-session"})
        self.assertNotIn("condition", step)
        self.assertEqual(step["description_file"], "../assets/workflows/build-base/summarize-implementation.md")
        self.assertEqual(steps_by_id("build-basic")["finalize"]["needs"], ["review"])

    def test_covers_zero_items_without_an_item_or_convoy(self) -> None:
        zero = self.text[self.text.index("**Zero items created:**"):self.text.index("**All items failed:**")]
        self.assertIn("no `gc.build.implementation_convoy_id`", zero)
        self.assertIn("the manifest has no rows", zero)
        self.assertIn("`gc.failure_reason=predecessor_failed`", zero)
        self.assertIn("`gc.failure_subject`", zero)
        self.assertIn("`gc.build.decomposition_path`", zero)
        self.assertIn("This case needs no item and no convoy.", zero)

    def test_covers_all_items_failed_and_never_counts_a_closed_item_as_success(self) -> None:
        failed = self.text[self.text.index("**All items failed:**"):self.text.index("**Any item passed:**")]
        self.assertIn("`gc.drain_manifest.v1`", self.text)
        self.assertIn("no row has `outcome` `pass`", failed)
        self.assertIn("A closed item root or a closed source anchor is not a success", failed)
        self.assertIn("closed `gc.outcome=fail`", failed)
        self.assertIn("**Any item passed:** write no source notice.", self.text)

    def test_source_is_the_launch_convoy_member_not_an_implementation_item(self) -> None:
        self.assertIn("launch convoy `gc.var.convoy_id`", self.text)
        self.assertIn("`gc convoy status <launch-convoy-id> --json`", self.text)
        self.assertIn("Never use the members of `gc.build.implementation_convoy_id`", self.text)
        self.assertIn("Do not read the source from `gc.input_convoy_id`", self.text)

    def test_reads_before_writing_one_marked_comment(self) -> None:
        read = self.text.index("`gc bd comments <source-id> --json`")
        write = self.text.index("`gc bd comments add <source-id> -f <notice-file>`")
        self.assertLess(read, write, "the marker check must come before the write")
        self.assertIn(f"contains the marker `{MARKER}`, write nothing", self.text)
        self.assertIn(f"Its first line is the marker `{MARKER}`", self.text)
        self.assertIn("at most one comment on each original source bead", self.text)

    def test_notice_carries_root_step_and_artifact(self) -> None:
        body = self.text[self.text.index("Otherwise put the notice in a file"):]
        for field in ("workflow root id", "failed step bead id", "the artifact path",
                      "canonical implementation summary path", "`Source left open and not delivered.`"):
            with self.subTest(field=field):
                self.assertIn(field, body)

    def test_source_stays_open_and_undelivered(self) -> None:
        self.assertIn("Leave the source open and undelivered: never close it", self.text)
        self.assertIn("never mark it delivered", self.text)
        self.assertIn("Set this summary's `status` to `blocked`, not `approved`", self.text)

    def test_discloses_durability_and_the_non_atomic_dedup(self) -> None:
        self.assertIn("stays readable after the root closes or is purged", self.text)
        self.assertIn("The read-then-write check is not atomic", self.text)
        self.assertIn("could each add one", self.text)


class FinalizeFallbackNoticeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = flat(FINALIZE)

    def test_finalize_rechecks_with_the_same_marker(self) -> None:
        # Dedup across the two paths only works if both look for the identical marker.
        self.assertIn(f"contains `{MARKER}`, write nothing", self.text)
        self.assertIn(f"first line the marker `{MARKER}`", self.text)
        self.assertIn(MARKER, flat(SUMMARIZE))
        read = self.text.index("`gc bd comments <source-id> --json`")
        write = self.text.index("`gc bd comments add <source-id> -f <notice-file>`")
        self.assertLess(read, write)

    def test_finalize_covers_both_cases_and_leaves_the_source_open(self) -> None:
        self.assertIn("zero items created", self.text)
        self.assertIn("all items failed", self.text)
        self.assertIn("a closed item is not a success", self.text)
        self.assertIn("launch convoy `gc.var.convoy_id`", self.text)
        self.assertIn("never from the implementation convoy", self.text)
        self.assertIn("Leave the source open and undelivered: never close it", self.text)
        self.assertIn("Use a status other than `approved` for the final report", self.text)
        # The fallback runs before the final report is written, while the root is open.
        self.assertLess(self.text.index("Source failure notice fallback"),
                        self.text.index("Record the final report path on the workflow root bead"))


if __name__ == "__main__":
    unittest.main()
