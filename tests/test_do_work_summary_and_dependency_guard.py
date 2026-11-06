"""do-work finds the implementation summary and refuses blocked anchors.

2026-11-05 native-sling trial:
- gl-rzkx2y (also gl-61ezxn, gl-l9n4xz, gl-t7jcbh, gl-8rox7n): implement
  recorded gc.implementation.summary_path on its iteration bead only;
  close-source-anchor's `needs` bead is the `implement` ralph control bead, which
  never carries it, so the close fell back to task-<id>-summary.md and failed
  missing_summary_evidence with a validated summary on disk.
- gl-c2tps2: a drain started anchor gl-thh95d while its blocker gl-10egi9 was
  open; the lane implemented it and the close failed dependency_open.
"""
import pathlib
import re

DW = pathlib.Path(__file__).resolve().parents[1] / "gascity" / "assets" / "workflows" / "do-work"


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


def test_prepare_worktree_refuses_an_anchor_with_open_blockers_before_the_worktree():
    text = read("prepare-worktree.md")
    guard = text.index("Dependency guard")
    create = text.index("Create or reuse a deterministic git worktree")
    assert guard < create
    seg = text[guard:create]
    assert "dependency_type=blocks" in seg and "dependency_open" in seg
    assert "do not create a worktree" in seg
