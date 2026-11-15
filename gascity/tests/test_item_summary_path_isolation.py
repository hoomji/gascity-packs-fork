"""An item summary never shares a path with the canonical build summary.

In a one-item build-basic run the item worker wrote its summary to
``<artifact_root>/implementation-summary.md``, the file the root records as
``gc.build.implementation_summary_path``. ``summarize-implementation`` then
found the canonical path occupied and the build died before review and publish.

These tests pin the path contract between the two summaries. They read the real
formulas, the real step prompts and the real ``build-artifact-valid.sh`` gate;
nothing here restates the contract from memory.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import tempfile
import tomllib
import unittest


GASCITY = pathlib.Path(__file__).resolve().parents[1]
REPO = GASCITY.parent

CANONICAL_KEY = "gc.build.implementation_summary_path"
ITEM_KEY = "gc.implementation.summary_path"
VAR_KEY = "gc.var.summary_path"
SCHEMA = "gc.build.implementation-summary.v1"
ITEM_PATH_TEMPLATE = "items/<member_id>/implementation-summary.md"

# (formula file, step id, prompt file) for every formula whose step produces
# an item-level implementation summary and is gated on SCHEMA.
GASCITY_ITEM_STEPS = [
    ("gascity/formulas/do-work-item.formula.toml", "implement-item",
     "gascity/assets/workflows/do-work-item/implement-item.md"),
    ("gascity/formulas/implementation-item-base.formula.toml", "implement-item",
     "gascity/assets/workflows/implementation-item-base/implement-item.md"),
    ("gascity/formulas/do-work.formula.toml", "implement",
     "gascity/assets/workflows/do-work/implement.md"),
    ("gascity/formulas/implementation-base.formula.toml", "implement",
     "gascity/assets/workflows/implementation-base/implement.md"),
]
DERIVED_ITEM_STEPS = [
    ("superpowers/formulas/superpowers-development.formula.toml", "implement",
     "superpowers/assets/workflows/superpowers-development/implement.md"),
    ("superpowers/formulas/superpowers-development-item.formula.toml", "implement-item",
     "superpowers/assets/workflows/superpowers-development/implement-item.md"),
    ("compound-engineering/formulas/compound-work.formula.toml", "implement",
     "compound-engineering/assets/workflows/compound-work/implement.md"),
    ("compound-engineering/formulas/compound-work-item.formula.toml", "implement-item",
     "compound-engineering/assets/workflows/compound-work-item/implement-item.md"),
    ("gstack/formulas/gstack-work.formula.toml", "implement",
     "gstack/assets/workflows/gstack-work/implement.md"),
    ("gstack/formulas/gstack-work-item.formula.toml", "implement-item",
     "gstack/assets/workflows/gstack-work-item/implement-item.md"),
]
ALL_ITEM_STEPS = GASCITY_ITEM_STEPS + DERIVED_ITEM_STEPS

SUMMARIZE_PROMPT = "gascity/assets/workflows/build-base/summarize-implementation.md"


def squash(text: str) -> str:
    """Collapse whitespace so a Markdown line wrap cannot split a fragment."""
    return " ".join(text.split())


class Problems:
    """Collect assertion failures across cases so one test reports them all.

    ``unittest`` subtests report a failing case under a passing parent in some
    runners; collecting makes the test itself fail.
    """

    def __init__(self, test: unittest.TestCase) -> None:
        self.test = test
        self.messages: list[str] = []

    def case(self, label: str):
        problems = self

        class _Case:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                if exc_type is not None and issubclass(exc_type, AssertionError):
                    problems.messages.append(f"[{label}] {str(exc)[:300]}")
                    return True
                return False

        return _Case()

    def assert_none(self) -> None:
        self.test.assertEqual(self.messages, [], "\n".join(self.messages))


def step_metadata(formula_path: str, step_id: str) -> dict:
    data = tomllib.loads((REPO / formula_path).read_text(encoding="utf-8"))
    for step in data.get("steps") or []:
        if step.get("id") == step_id:
            return step["metadata"]
    raise AssertionError(f"{formula_path} has no step {step_id!r}")


def item_path_keys(formula_path: str, step_id: str) -> list[str]:
    raw = step_metadata(formula_path, step_id)["gc.build.artifact_path_keys"]
    return [key.strip() for key in raw.split(",") if key.strip()]


def valid_summary(workflow_id: str, stage: str) -> str:
    sections = "\n\n".join(
        f"## {name}\n\n{name} content."
        for name in ("Summary", "Intended Behavior", "Changed Files", "Verification", "Remaining Risks")
    )
    return (
        "---\n"
        f"schema: {SCHEMA}\n"
        f"workflow: {{id: {workflow_id}, formula: build-basic}}\n"
        "methodology: {pack: gascity, name: build-basic}\n"
        f"producer: {{formula: do-work, stage: {stage}, attempt: 1}}\n"
        "status: approved\n"
        "trace:\n"
        "  upstream:\n"
        "    - path: beads/item-1\n"
        "      hash: bead:item-1\n"
        "  coverage:\n"
        "    - {id: REQ-001, status: covered}\n"
        "---\n\n"
        f"{sections}\n\n| ID | Status |\n| --- | --- |\n| REQ-001 | covered |\n"
    )


class ItemSummaryPathIsolationTest(unittest.TestCase):
    def test_item_gates_never_list_the_canonical_key(self) -> None:
        """REQ-001, REQ-004: no item gate can resolve to the canonical file."""
        problems = Problems(self)
        for formula_path, step_id, _ in ALL_ITEM_STEPS:
            with problems.case(formula_path):
                keys = item_path_keys(formula_path, step_id)
                self.assertNotIn(CANONICAL_KEY, keys)
                self.assertEqual(keys[0], ITEM_KEY)
        problems.assert_none()

    def _run_gate(
        self,
        formula_path: str,
        step_id: str,
        *,
        step_extra: dict[str, str],
        canonical: pathlib.Path,
    ) -> subprocess.CompletedProcess:
        """Run the real gate for the one-item shape against a fake ``gc``.

        The root carries the canonical key; the item step carries the formula's
        real ``artifact_path_keys`` string. The fake ``gc`` prints a one-element
        list for ``show <id> --json``, like the real tool.
        """
        meta = step_metadata(formula_path, step_id)
        step_meta = {
            "gc.root_bead_id": "root",
            "gc.build.artifact_schema": meta["gc.build.artifact_schema"],
            "gc.build.artifact_path_keys": meta["gc.build.artifact_path_keys"],
            **step_extra,
        }
        beads = {
            "step": [{"id": "step", "metadata": step_meta}],
            "root": [{"id": "root", "metadata": {CANONICAL_KEY: str(canonical)}}],
        }
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            show_dir = tmp / "show"
            show_dir.mkdir()
            for bead_id, payload in beads.items():
                (show_dir / f"{bead_id}.json").write_text(json.dumps(payload), encoding="utf-8")
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            fake_gc = bin_dir / "gc"
            fake_gc.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'while [ "${1:-}" != "bd" ]; do shift; done\n'
                "shift\n"
                'case "$1" in\n'
                "  version) exit 0 ;;\n"
                '  show) cat "$BD_SHOW_DIR/$2.json" ;;\n'
                "  *) exit 2 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            fake_gc.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "BD_SHOW_DIR": str(show_dir),
                "GC_BEAD_ID": "step",
            }
            return subprocess.run(
                [str(GASCITY / "assets/scripts/checks/build-artifact-valid.sh")],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_item_gate_does_not_resolve_to_canonical_file(self) -> None:
        """REQ-001, REQ-004 on the one-item shape, for every item formula."""
        problems = Problems(self)
        for formula_path, step_id, _ in ALL_ITEM_STEPS:
            with problems.case(formula_path), tempfile.TemporaryDirectory() as td:
                tmp = pathlib.Path(td)
                canonical = tmp / "implementation-summary.md"
                # An invalid body, so a gate that resolves here is visible.
                canonical.write_text("canonical file is not a valid summary\n", encoding="utf-8")
                item = tmp / "items" / "item-1" / "implementation-summary.md"
                item.parent.mkdir(parents=True)
                item.write_text(valid_summary("item-root", "implement"), encoding="utf-8")

                # (a) the per-item path is recorded: the gate validates it.
                with_path = self._run_gate(
                    formula_path, step_id,
                    step_extra={ITEM_KEY: str(item)},
                    canonical=canonical,
                )
                self.assertEqual(with_path.returncode, 0, with_path.stdout + with_path.stderr)
                self.assertIn(str(item), with_path.stdout)
                self.assertNotIn(str(canonical), with_path.stdout + with_path.stderr)

                # (b) no per-item path: the gate fails clearly and never
                # validates the canonical file.
                without = self._run_gate(
                    formula_path, step_id,
                    step_extra={}, canonical=canonical,
                )
                self.assertNotEqual(without.returncode, 0, without.stdout)
                self.assertIn("no artifact path recorded", without.stderr)
                self.assertNotIn(str(canonical), without.stdout + without.stderr)
        problems.assert_none()

    def test_item_prompts_name_a_per_item_path(self) -> None:
        """REQ-001: the item worker is told where to write, and where not to."""
        problems = Problems(self)
        for _, _, prompt in GASCITY_ITEM_STEPS:
            with problems.case(prompt):
                text = squash((REPO / prompt).read_text(encoding="utf-8"))
                self.assertIn(ITEM_PATH_TEMPLATE, text)
                self.assertIn(
                    f"Never write the canonical path (`{CANONICAL_KEY}`)", text
                )
                self.assertNotIn(f"fallbacks `{CANONICAL_KEY}`", text)
                self.assertNotIn(f"fallback `{CANONICAL_KEY}`", text)
        problems.assert_none()

    def test_derived_item_prompts_do_not_offer_the_canonical_fallback(self) -> None:
        """The derived-pack prompts match their formulas' two-key gate."""
        problems = Problems(self)
        for _, _, prompt in DERIVED_ITEM_STEPS:
            with problems.case(prompt):
                text = squash((REPO / prompt).read_text(encoding="utf-8"))
                self.assertNotIn(CANONICAL_KEY, text)
        problems.assert_none()

    def test_canonical_step_states_the_occupied_path_rule(self) -> None:
        """REQ-005: a file already at the canonical path is handled by rule."""
        text = squash((REPO / SUMMARIZE_PROMPT).read_text(encoding="utf-8"))
        problems = Problems(self)
        for fragment in (
            "Occupied canonical path",
            "`producer.stage` is `implement` or `implement-item`",
            "legacy-<hash8>",
            "`producer.stage` is `summarize-implementation`",
            "repair it in place",
            "canonical_summary_path_occupied",
            "do not touch the file",
            "`gc.attempt` greater than 1",
        ):
            with problems.case(fragment):
                self.assertIn(fragment, text)
        problems.assert_none()

    def test_canonical_step_reads_item_paths_without_the_canonical_key(self) -> None:
        """REQ-001: the canonical step does not read its own output as an item summary."""
        text = squash((REPO / SUMMARIZE_PROMPT).read_text(encoding="utf-8"))
        match = re.search(
            r"Read their recorded implementation summary paths from (.*?) Include those summaries",
            text,
        )
        self.assertIsNotNone(match, "item-path read sentence not found")
        self.assertEqual(match.group(1), f"`{ITEM_KEY}`, then `{VAR_KEY}`.")

    def test_multi_item_paths_are_distinct(self) -> None:
        """REQ-003: the documented convention gives each item its own path."""
        text = squash((REPO / GASCITY_ITEM_STEPS[0][2]).read_text(encoding="utf-8"))
        self.assertIn(ITEM_PATH_TEMPLATE, text, "per-item path convention is not documented")
        artifact_root = "/rig/_bmad-output/build/gp-0001"
        canonical = f"{artifact_root}/implementation-summary.md"
        members = ["gp-a1", "gp-b2", "gp-c3", "gp-d4"]
        paths = [
            f"{artifact_root}/{ITEM_PATH_TEMPLATE.replace('<member_id>', member)}"
            for member in members
        ]
        self.assertEqual(len(set(paths)), len(members))
        self.assertNotIn(canonical, paths)


if __name__ == "__main__":
    unittest.main()
