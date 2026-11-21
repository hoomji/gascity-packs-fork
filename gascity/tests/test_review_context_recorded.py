"""The starter review setup step cannot pass without the context path on the root.

On 2026-11-21 a build-basic setup step wrote ``code-review-context.md``, closed
``pass`` and never recorded ``gc.build.code_review_context_path`` on the
workflow root. Every review lane then failed hard in setup and the build
published with no in-lane review. These tests read the real formula and run the
real gate.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile
import tomllib
import unittest


GASCITY = pathlib.Path(__file__).resolve().parents[1]
FORMULA = GASCITY / "formulas/build-basic-review.formula.toml"
KEY = "gc.build.code_review_context_path"
SETUP_ID = "{target}.setup-build-basic-review"

FAKE_GC = (
    "#!/usr/bin/env bash\n"
    "set -euo pipefail\n"
    'while [ "${1:-}" != "bd" ]; do shift; done\n'
    "shift\n"
    'case "$1" in\n'
    '  show) cat "$BD_SHOW_DIR/$2.json" ;;\n'
    "  *) exit 2 ;;\n"
    "esac\n"
)


def setup_template() -> dict:
    formula = tomllib.loads(FORMULA.read_text(encoding="utf-8"))
    return next(t for t in formula["template"] if t["id"] == SETUP_ID)


class ReviewContextRecordedTests(unittest.TestCase):
    def _run_gate(self, root_metadata: dict, env_extra: dict | None = None):
        """Run the gate the formula names for the setup step against a fake gc."""
        check = setup_template().get("check", {}).get("check", {})
        self.assertEqual(check.get("mode"), "exec", "setup step has no exec check")
        script = (FORMULA.parent / check["path"]).resolve()
        beads = {
            "step": [{"id": "step", "metadata": {"gc.root_bead_id": "root"}}],
            "root": [{"id": "root", "metadata": root_metadata}],
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
            fake_gc.write_text(FAKE_GC, encoding="utf-8")
            fake_gc.chmod(0o755)
            env = {
                k: v for k, v in os.environ.items()
                if k not in {"GC_RIG_ROOT", "GC_BEADS_SCOPE_ROOT", "GC_STORE_PATH", "GC_WORK_DIR"}
            }
            env.update({
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "BD_SHOW_DIR": str(show_dir),
                "GC_BEAD_ID": "step",
                **(env_extra or {}),
            })
            return subprocess.run(
                [str(script)], env=env, text=True, capture_output=True, check=False
            )

    def test_setup_step_is_checked_with_bounded_attempts(self) -> None:
        check = setup_template().get("check", {})
        self.assertGreaterEqual(check.get("max_attempts", 0), 2)
        self.assertTrue(check.get("check", {}).get("path", "").endswith("review-context-recorded.sh"))

    def test_gate_fails_when_root_has_no_context_path(self) -> None:
        """The 2026-11-21 shape: the file exists, the root never names it."""
        with tempfile.TemporaryDirectory() as td:
            (pathlib.Path(td) / "code-review-context.md").write_text("# context\n", encoding="utf-8")
            result = self._run_gate({"gc.build.requirements_path": "/x/requirements.md"})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(KEY, result.stderr)

    def test_gate_fails_when_recorded_file_is_missing(self) -> None:
        result = self._run_gate({KEY: "/nonexistent/code-review-context.md"})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("does not exist", result.stderr)

    def test_gate_passes_for_absolute_and_rig_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            rig = pathlib.Path(td)
            context = rig / "_bmad-output/build/x/code-review-context.md"
            context.parent.mkdir(parents=True)
            context.write_text("# context\n", encoding="utf-8")
            absolute = self._run_gate({KEY: str(context)})
            relative = self._run_gate(
                {KEY: "_bmad-output/build/x/code-review-context.md"},
                {"GC_STORE_PATH": str(rig)},
            )
            unanchored = self._run_gate({KEY: "_bmad-output/build/x/code-review-context.md"})
        self.assertEqual(absolute.returncode, 0, absolute.stderr)
        self.assertEqual(relative.returncode, 0, relative.stderr)
        self.assertNotEqual(unanchored.returncode, 0, unanchored.stdout)


if __name__ == "__main__":
    unittest.main()
