"""A do-work step that must write named beads besides its own says so explicitly.

2026-11-03 (hoppy-city hc-cjiro, step hc-6iif6): the run-operator closed
do-work.prepare-worktree with gc.failure_class=instruction_conflict because its
startup rule allows updating only the claimed bead, while the step must stamp
gc.source_anchor_id on the workflow root and work_dir on the source anchor.
The implement and close steps then failed worktree_unavailable.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "gascity" / "assets" / "workflows"
NAMED_WRITE = re.compile(r"gc bd update <(root-bead-id|source-anchor-id)>")
GRANT = "nothing here conflicts with \"update or close only your claimed bead\""


def test_named_bead_writes_carry_the_grant():
    offenders = []
    for p in sorted([*ROOT.glob("do-work/*.md"), *ROOT.glob("do-work-item/*.md")]):
        text = p.read_text()
        if NAMED_WRITE.search(text) and GRANT not in text:
            offenders.append(str(p.relative_to(ROOT)))
    assert offenders == [], offenders


def test_prepare_worktree_names_both_writes():
    text = (ROOT / "do-work" / "prepare-worktree.md").read_text()
    head = text.split("1. ", 1)[0]
    assert GRANT in head
    assert "gc.source_anchor_id" in head and "work_dir" in head
