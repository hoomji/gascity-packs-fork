"""do-work's close step: summary evidence, a blocked root, and delivery.

2026-11-05 native-sling trial:
- gl-rzkx2y (also gl-61ezxn, gl-l9n4xz, gl-t7jcbh, gl-8rox7n): implement
  recorded gc.implementation.summary_path on its iteration bead only;
  close-source-anchor's `needs` bead is the `implement` ralph control bead, which
  never carries it, so the close fell back to task-<id>-summary.md and failed
  missing_summary_evidence with a validated summary on disk.
- gl-c2tps2: the build-basic drain gl-wdquwt wired the item workflow of
  gl-thh95d to gl-mfskxp, the item root of its blocker gl-10egi9. gl-mfskxp
  closed gc.outcome=fail with gl-10egi9 still open, and a closed blocker
  satisfies a `blocks` edge, so gl-thh95d's item started. gc's readiness holds
  a dependent back when the closed blocker carries gc.work_outcome=blocked
  (beads.DependencySatisfied), so a failed close stamps the root that way.
- Lanes closed pass with their commit only in a local worktree. The close step
  now carries an exec check, do-work-delivered.sh, run here against real git
  repositories with a fake gc and gh.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "gascity"
DW = ROOT / "assets" / "workflows" / "do-work"
CHECK = ROOT / "assets" / "scripts" / "checks" / "do-work-delivered.sh"


def read(name):
    return (DW / name).read_text()


def test_implement_records_the_absolute_summary_path_on_the_root():
    text = read("implement.md")
    assert re.search(r"gc bd update <root-bead-id> --set-metadata gc\.implementation\.summary_path=", text)
    assert "ABSOLUTE path" in text
    assert "Update only the claimed bead" not in text


def test_close_reads_root_then_iteration_beads_then_default_in_order():
    text = read("close-source-anchor.md")
    root = text.index("The workflow root's `gc.implementation.summary_path`")
    iters = text.index("--metadata-field gc.ralph_step_id=implement")
    default = text.index("task-<source-anchor-id>-summary.md")
    assert root < iters < default
    assert "gc.root_bead_id=<root-bead-id>" in text
    # A summary outside the worktree is still evidence.
    assert "outside the worktree" in text


def test_a_failed_close_stamps_the_root_blocked_and_success_never_does():
    text = read("close-source-anchor.md")
    assert "gc bd update <root-bead-id> --set-metadata gc.work_outcome=blocked" in text
    assert "Never write it on success." in text
    # The prepare step no longer second-guesses readiness in prose.
    assert "dependency_open" not in read("prepare-worktree.md")


def test_close_step_runs_the_delivery_check_off_by_default():
    f = tomllib.loads((ROOT / "formulas" / "do-work.formula.toml").read_text())
    assert f["vars"]["require_delivery"]["default"] == "false"
    step = {s["id"]: s for s in f["steps"]}["close-source-anchor"]
    assert step["check"]["check"]["mode"] == "exec"
    assert step["check"]["check"]["path"] == "../assets/scripts/checks/do-work-delivered.sh"
    assert step["check"]["max_attempts"] >= 1


FAKE_GC = """#!/bin/sh
# gc bd show <id> --json -> $BEADS/<id>.json
[ -n "${GC_DOWN:-}" ] && { echo "dolt unreachable" >&2; exit 1; }
[ "$1" = bd ] && [ "$2" = show ] || exit 2
cat "$BEADS/$3.json"
"""

FAKE_GH = """#!/bin/sh
case "$1 $2" in
  "auth token") [ -n "${GH_NOAUTH:-}" ] && exit 1; echo tok ;;
  "pr list") [ -n "${GH_DOWN:-}" ] && exit 1; printf '%s' "${GH_PRS:-[]}" ;;
  *) exit 2 ;;
esac
"""


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class DeliveredCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        remote = self.tmp / "remote.git"
        git("init", "-q", "--bare", "-b", "trunk", str(remote), cwd=self.tmp)
        self.wt = self.tmp / "wt"
        git("clone", "-q", str(remote), str(self.wt), cwd=self.tmp)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            git("config", k, v, cwd=self.wt)
        git("checkout", "-q", "-b", "trunk", cwd=self.wt)
        git("commit", "-q", "--allow-empty", "-m", "base", cwd=self.wt)
        git("push", "-q", "origin", "trunk", cwd=self.wt)
        git("remote", "set-head", "origin", "--auto", cwd=self.wt)
        bindir = self.tmp / "bin"
        bindir.mkdir()
        for name, body in (("gc", FAKE_GC), ("gh", FAKE_GH)):
            (bindir / name).write_text(body)
            (bindir / name).chmod(0o755)
        self.beads = self.tmp / "beads"
        self.beads.mkdir()
        self.env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "BEADS": str(self.beads),
                    "GC_BEAD_ID": "st-1"}
        self.write_beads()

    def write_beads(self, root_meta=None, anchor_meta=None):
        root = {"gc.source_anchor_id": "an-1", "gc.var.require_delivery": "true", "gc.var.base_branch": "trunk"}
        root.update(root_meta or {})
        root = {k: v for k, v in root.items() if v is not None}
        beads = {"st-1": {"gc.root_bead_id": "rt-1"}, "rt-1": root,
                 "an-1": {"work_dir": str(self.wt), **(anchor_meta or {})}}
        for bid, meta in beads.items():
            # gc bd show --json may answer with a one-element list.
            (self.beads / f"{bid}.json").write_text(json.dumps([{"id": bid, "metadata": meta}]))

    def lane_commit(self, branch="fix/lane"):
        git("checkout", "-q", "-b", branch, cwd=self.wt)
        git("commit", "-q", "--allow-empty", "-m", "lane work", cwd=self.wt)
        return git("rev-parse", "HEAD", cwd=self.wt)

    def run_check(self, **env):
        r = subprocess.run(["sh", str(CHECK)], capture_output=True, text=True, env={**self.env, **env})
        return r.returncode, r.stdout.strip()

    def test_unpushed_lane_commit_is_not_yet(self):
        self.lane_commit()
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("not delivered", out)

    def test_pushed_lane_branch_is_delivered(self):
        self.lane_commit()
        git("push", "-q", "origin", "fix/lane", cwd=self.wt)
        self.assertEqual(self.run_check(), (0, f"delivered: {git('rev-parse', 'HEAD', cwd=self.wt)} is on origin/fix/lane"))

    def test_a_lane_with_no_commit_of_its_own_is_not_delivered_by_any_branch_at_the_base(self):
        # Another origin branch sits on the base commit: "some remote branch contains HEAD"
        # would read a lane that committed nothing as delivered.
        git("push", "-q", "origin", "trunk:refs/heads/develop", cwd=self.wt)
        code, out = self.run_check()
        self.assertEqual(code, 1, out)

    def test_base_branch_falls_back_to_the_remote_default(self):
        self.write_beads(root_meta={"gc.var.base_branch": None})
        git("push", "-q", "origin", "trunk:refs/heads/develop", cwd=self.wt)
        self.assertEqual(self.run_check()[0], 1)

    def test_open_or_merged_pr_delivers_a_commit_whose_branch_is_gone(self):
        self.lane_commit()
        merged = json.dumps([{"number": 7, "state": "MERGED"}])
        self.assertEqual(self.run_check(GH_PRS=merged), (0, f"delivered: {git('rev-parse', 'HEAD', cwd=self.wt)} is in PR #7"))
        closed = json.dumps([{"number": 8, "state": "CLOSED"}])
        self.assertEqual(self.run_check(GH_PRS=closed)[0], 1)

    def test_not_required_or_drain_item_passes_without_delivery(self):
        self.lane_commit()
        self.write_beads(root_meta={"gc.var.require_delivery": "false"})
        self.assertEqual(self.run_check()[0], 0)
        self.write_beads(root_meta={"gc.var.require_delivery": None})
        self.assertEqual(self.run_check()[0], 0)
        self.write_beads(root_meta={"gc.drain_control_id": "dr-1"})
        self.assertEqual(self.run_check()[0], 0)

    def test_require_delivery_is_read_from_graphv2_vars(self):
        self.lane_commit()
        self.write_beads(root_meta={"gc.var.require_delivery": None,
                                    "gc.graphv2_vars.v1": json.dumps({"require_delivery": "true"})})
        self.assertEqual(self.run_check()[0], 1)

    def test_infrastructure_failures_exit_75(self):
        self.lane_commit()
        self.assertEqual(self.run_check(GC_DOWN="1")[0], 75)
        self.assertEqual(self.run_check(GH_DOWN="1")[0], 75)
        git("remote", "set-url", "origin", str(self.tmp / "gone.git"), cwd=self.wt)
        self.assertEqual(self.run_check()[0], 75)

    def test_gh_without_credentials_is_not_yet_not_infra(self):
        self.lane_commit()
        self.assertEqual(self.run_check(GH_NOAUTH="1")[0], 1)
