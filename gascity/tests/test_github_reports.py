from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
import io

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "assets" / "scripts"))

import github_reports


class GitHubReportsTests(unittest.TestCase):
    def test_validate_triage_report_accepts_expected_front_matter(self) -> None:
        report = """---
schema: gc.github-issue-triage-report.v1
repo: owner/repo
issue_number: 123
body_hash: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
verdict: reproduced
priority: p1
recommended_next_action: fix
reproduction_artifact_path: logs/repro.txt
reproduction_diff_path: repro.patch
---

Reproduction details.
"""

        parsed = github_reports.validate_triage_report_text(
            report,
            expected_repo="owner/repo",
            expected_issue_number=123,
            expected_body_hash="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )

        self.assertEqual(parsed.verdict, "reproduced")
        self.assertEqual(parsed.recommended_next_action, "fix")

    def test_validate_triage_report_rejects_bad_actions_and_mismatches(self) -> None:
        report = """---
schema: gc.github-issue-triage-report.v1
repo: owner/repo
issue_number: 123
body_hash: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
verdict: needs_info
priority: p2
recommended_next_action: fix
---
"""

        with self.assertRaisesRegex(github_reports.ValidationError, "recommended_next_action"):
            github_reports.validate_triage_report_text(report)
        with self.assertRaisesRegex(github_reports.ValidationError, "repo"):
            github_reports.validate_triage_report_text(report.replace("fix", "ask_reporter"), expected_repo="other/repo")

    def test_validate_triage_report_requires_analysis_body(self) -> None:
        report = """---
schema: gc.github-issue-triage-report.v1
repo: owner/repo
issue_number: 123
body_hash: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
verdict: needs_info
priority: p2
recommended_next_action: ask_reporter
---
"""

        with self.assertRaisesRegex(github_reports.ValidationError, "analysis body"):
            github_reports.validate_triage_report_text(report)

    def test_review_outcome_maps_generic_verdicts_to_comment_outcomes(self) -> None:
        self.assertEqual(github_reports.review_outcome("pass", "none"), "approve")
        self.assertEqual(github_reports.review_outcome("fail", "minor"), "comment")
        self.assertEqual(github_reports.review_outcome("fail", "major"), "request_changes")
        self.assertEqual(github_reports.review_outcome("fail", "blocker"), "block")

        with self.assertRaises(github_reports.ValidationError):
            github_reports.review_outcome("pass", "minor")

    # The generic `review` formula writes gc.build.review.v1 (its artifact schema), so the PR
    # adapter must read that schema too, not only gc.verdict-report.v1.
    BUILD_REVIEW_HEAD = (
        "---\n"
        "schema: gc.build.review.v1\n"
        "workflow:\n  id: wf-1\n  formula: review\n"
        "methodology:\n  pack: gascity\n  name: review\n"
        "producer:\n  formula: review\n  stage: write-report\n  attempt: 1\n"
    )

    def _review_outcome_cli(self, text: str) -> tuple[int, str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "review-report.md"
            path.write_text(text, encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = github_reports.main(["review-outcome", str(path)])
            return code, out.getvalue(), err.getvalue()

    def test_review_outcome_reads_build_review_status(self) -> None:
        cases = {"approved": "approve", "changes_required": "request_changes", "blocked": "block"}
        for status, outcome in cases.items():
            with self.subTest(status=status):
                code, out, err = self._review_outcome_cli(self.BUILD_REVIEW_HEAD + f"status: {status}\n---\n\n## Verdict\n")
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)["outcome"], outcome)

    def test_review_outcome_prefers_verdict_fields_on_build_review(self) -> None:
        text = self.BUILD_REVIEW_HEAD + (
            "status: changes_required\nkind: review\nverdict: fail\nseverity: minor\n"
            "findings:\n  - id: f1\n    severity: minor\n    title: t\n    evidence: e\n    required_fix: r\n"
            "---\n"
        )
        code, out, err = self._review_outcome_cli(text)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["outcome"], "comment")

    def test_review_outcome_rejects_unfinished_or_contradictory_build_review(self) -> None:
        for tail in ("status: draft\n", "status: questions\n", "status: approved\nverdict: fail\nseverity: major\nfindings: []\n"):
            with self.subTest(tail=tail):
                code, _, _ = self._review_outcome_cli(self.BUILD_REVIEW_HEAD + tail + "---\n")
                self.assertNotEqual(code, 0)

    def test_render_review_comment_accepts_build_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "review-report.md"
            path.write_text(self.BUILD_REVIEW_HEAD + "status: approved\n---\n", encoding="utf-8")
            comment = github_reports.render_pr_review_comment(path, outcome="approve", head_sha="abc123")
        self.assertIn("outcome=approve", comment)
        self.assertIn("- report: pass/none", comment)

    def test_render_review_comment_carries_the_findings(self) -> None:
        # gp-mzit8: the posted comment named only a local artifact path, so readers saw no findings.
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "review-report.md"
            path.write_text(
                "---\n"
                "schema: gc.verdict-report.v1\n"
                "kind: review\n"
                "verdict: fail\n"
                "severity: minor\n"
                "findings:\n"
                "  - id: F1\n"
                "    severity: minor\n"
                "    title: Hardcoded produced_at\n"
                "    evidence: make_envelope sets a fixed literal. <!-- x -->\n"
                "    required_fix: Emit the real time.\n"
                "---\n",
                encoding="utf-8",
            )
            comment = github_reports.render_pr_review_comment(path, outcome="comment", head_sha="abc123")
        self.assertIn("### Findings", comment)
        self.assertIn("**F1** (minor): Hardcoded produced\\_at", comment)
        self.assertIn("make_envelope sets a fixed literal.", comment)
        self.assertIn("Emit the real time.", comment)
        self.assertEqual(comment.count("<!--"), 1, "finding text must not open a second HTML comment")
        self.assertNotIn(tmp, comment, "a local artifact path is not useful in a public comment")

    def test_render_review_comment_carries_build_review_markdown_findings(self) -> None:
        # The default `review` formula writes gc.build.review.v1 with findings only in the body.
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "review-report.md"
            path.write_text(
                self.BUILD_REVIEW_HEAD
                + "status: changes_required\n---\n"
                "## Verdict\nchanges required\n"
                "## Findings\n- F1 major: the handler drops errors\n### Detail\nsee @octocat <b>x</b>\n"
                "## Verification\nnone run\n",
                encoding="utf-8",
            )
            comment = github_reports.render_pr_review_comment(path, outcome="request_changes", head_sha="abc")
        self.assertIn("### Findings", comment)
        self.assertIn("- F1 major: the handler drops errors", comment)
        self.assertIn("##### Detail", comment, "report headings nest below the comment's own")
        self.assertNotIn("none run", comment, "only the Findings section is posted")
        self.assertNotIn("@octocat", comment, "an @-mention would notify a real account")
        self.assertNotIn("<b>", comment)

    def test_render_review_comment_keeps_finding_text_inert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "review-report.md"
            path.write_text(
                "---\nschema: gc.verdict-report.v1\nkind: review\nverdict: fail\nseverity: minor\n"
                "findings:\n"
                "  - id: \"F**1\"\n"
                "    severity: minor\n"
                "    title: \"<details><summary>fold\"\n"
                "    evidence: \"line one\\n## GC PR Review\\n---\\n--> <!x\"\n"
                "    required_fix: ping @octocat\n"
                "---\n",
                encoding="utf-8",
            )
            comment = github_reports.render_pr_review_comment(path, outcome="comment", head_sha="abc")
        self.assertEqual(comment.count("<"), 1, "only the sticky marker may contain raw HTML")
        self.assertEqual(
            [line for line in comment.splitlines() if line.startswith("#") and "GC PR Review" in line],
            ["## GC PR Review"],
            "finding text must stay on one line",
        )
        self.assertNotIn("\n---", comment)
        self.assertIn("F\\*\\*1", comment)
        self.assertNotIn("@octocat", comment)

    def test_render_review_comment_leaves_quoted_code_verbatim(self) -> None:
        # Escaping and heading demotion must not rewrite code a reviewer quotes.
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "review-report.md"
            path.write_text(
                self.BUILD_REVIEW_HEAD
                + "status: changes_required\n---\n"
                "## Findings\n"
                "- F1 major: `Vec<T>` and `a && b` break; outside code <b>x</b> & @octocat\n"
                "```python\n# keep this comment\n@pytest.fixture\nif a < b: pass\n```\n"
                "- F2 minor: `__init__` stays\n",
                encoding="utf-8",
            )
            comment = github_reports.render_pr_review_comment(path, outcome="request_changes", head_sha="abc")
        for verbatim in ("`Vec<T>`", "`a && b`", "# keep this comment\n@pytest.fixture\nif a < b: pass", "`__init__`"):
            with self.subTest(verbatim=verbatim):
                self.assertIn(verbatim, comment)
        self.assertIn("&lt;b&gt;x&lt;/b&gt; &amp; @\u200boctocat", comment)

    def test_render_review_comment_escapes_bold_breakers_in_the_finding_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "review-report.md"
            path.write_text(
                "---\nschema: gc.verdict-report.v1\nkind: review\nverdict: fail\nseverity: minor\n"
                "findings:\n  - id: F1\n    severity: minor\n    title: __init__ leaks\n"
                "    evidence: e\n    required_fix: f\n---\n",
                encoding="utf-8",
            )
            comment = github_reports.render_pr_review_comment(path, outcome="comment", head_sha="abc")
        self.assertIn("\\_\\_init\\_\\_ leaks", comment)

    def test_render_review_comment_truncation_closes_an_open_fence(self) -> None:
        body = "## Findings\n- F1 major: big\n```\n" + ("x" * 80 + "\n") * 1000 + "```\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "review-report.md"
            path.write_text(self.BUILD_REVIEW_HEAD + "status: changes_required\n---\n" + body, encoding="utf-8")
            comment = github_reports.render_pr_review_comment(path, outcome="request_changes", head_sha="abc")
        before_note = comment.split("_Findings truncated")[0]
        self.assertEqual(before_note.count("```") % 2, 0, "the truncation note must not render inside a code block")

    def test_render_review_comment_caps_findings_under_the_github_limit(self) -> None:
        findings = "".join(
            f"  - id: F{i}\n    severity: minor\n    title: t\n    evidence: {'x' * 900}\n    required_fix: y\n"
            for i in range(120)
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "review-report.md"
            path.write_text(
                "---\nschema: gc.verdict-report.v1\nkind: review\nverdict: fail\nseverity: minor\n"
                f"findings:\n{findings}---\n",
                encoding="utf-8",
            )
            comment = github_reports.render_pr_review_comment(path, outcome="comment", head_sha="abc")
        self.assertLess(len(comment), 65_536)
        self.assertIn("truncated", comment)

    def test_render_review_comment_names_a_public_artifact_only_when_given(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "review-report.md"
            path.write_text(self.BUILD_REVIEW_HEAD + "status: approved\n---\n", encoding="utf-8")
            with_ref = github_reports.render_pr_review_comment(
                path, outcome="approve", head_sha="abc", artifact_ref="https://example.test/r"
            )
            without = github_reports.render_pr_review_comment(path, outcome="approve", head_sha="abc")
        self.assertIn("- artifact: https://example.test/r", with_ref)
        self.assertNotIn("- artifact:", without)

    def test_renderers_write_sticky_marker_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            review_path = root / "review.md"
            review_path.write_text(
                "---\n"
                "schema: gc.verdict-report.v1\n"
                "kind: review\n"
                "verdict: fail\n"
                "severity: major\n"
                "findings:\n"
                "  - id: rev-1\n"
                "    severity: major\n"
                "    title: Missing test\n"
                "    evidence: No test.\n"
                "    required_fix: Add one.\n"
                "---\n",
                encoding="utf-8",
            )
            review_comment = github_reports.render_pr_review_comment(
                review_path,
                outcome="request_changes",
                head_sha="abc123",
                artifact_ref="artifact",
                human_approved=True,
            )
            triage_path = root / "triage.md"
            triage_path.write_text(
                "---\n"
                "schema: gc.github-issue-triage-report.v1\n"
                "repo: owner/repo\n"
                "issue_number: 123\n"
                "body_hash: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
                "verdict: needs_info\n"
                "priority: p2\n"
                "recommended_next_action: ask_reporter\n"
                "---\n"
                "\n"
                "## Summary\n"
                "\n"
                "The issue needs a missing reproduction detail.\n"
                "\n"
                "## Evidence\n"
                "\n"
                "- The report did not include the failing command.\n",
                encoding="utf-8",
            )
            triage_comment = github_reports.render_triage_comment(
                triage_path,
                artifact_ref="artifact",
                human_approved=False,
            )
            status_comment = github_reports.render_issue_fix_status(
                state="implementation_started",
                summary="Build is running.",
                run_id="run-1",
                pr_url="https://github.com/owner/repo/pull/9",
                artifact_ref="artifact",
            )

        self.assertIn("<!-- gc:github-pr-review", review_comment)
        self.assertIn("outcome: request_changes", review_comment)
        self.assertIn("human approved", review_comment)
        self.assertIn("<!-- gc:github-issue-triage", triage_comment)
        self.assertIn("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", triage_comment)
        self.assertIn("needs_info", triage_comment)
        self.assertIn("## Analysis", triage_comment)
        self.assertIn("### Summary", triage_comment)
        self.assertIn("The issue needs a missing reproduction detail.", triage_comment)
        self.assertIn("<!-- gc:github-issue-fix-status", status_comment)
        self.assertIn("implementation_started", status_comment)
        self.assertIn("https://github.com/owner/repo/pull/9", status_comment)

    def test_unapproved_security_triage_comment_redacts_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            triage_path = pathlib.Path(tmp) / "triage.md"
            triage_path.write_text(
                "---\n"
                "schema: gc.github-issue-triage-report.v1\n"
                "repo: owner/repo\n"
                "issue_number: 123\n"
                "body_hash: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
                "verdict: security_sensitive\n"
                "priority: p1\n"
                "recommended_next_action: security_process\n"
                "---\n"
                "\n"
                "## Summary\n"
                "\n"
                "Sensitive exploit detail.\n",
                encoding="utf-8",
            )

            triage_comment = github_reports.render_triage_comment(
                triage_path,
                human_approved=False,
            )

        self.assertIn("security-sensitive details require human approval", triage_comment)
        self.assertNotIn("p0 details require human approval", triage_comment)
        self.assertNotIn("Sensitive exploit detail", triage_comment)

    def test_unapproved_p0_triage_comment_redacts_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            triage_path = pathlib.Path(tmp) / "triage.md"
            triage_path.write_text(
                "---\n"
                "schema: gc.github-issue-triage-report.v1\n"
                "repo: owner/repo\n"
                "issue_number: 123\n"
                "body_hash: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
                "verdict: reproduced\n"
                "priority: p0\n"
                "recommended_next_action: fix\n"
                "---\n"
                "\n"
                "## Summary\n"
                "\n"
                "Urgent private impact detail.\n",
                encoding="utf-8",
            )

            triage_comment = github_reports.render_triage_comment(
                triage_path,
                human_approved=False,
            )

        self.assertIn("p0 details require human approval", triage_comment)
        self.assertNotIn("security-sensitive details require human approval", triage_comment)
        self.assertNotIn("Urgent private impact detail", triage_comment)

    def test_unapproved_security_p0_triage_comment_joins_redaction_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            triage_path = pathlib.Path(tmp) / "triage.md"
            triage_path.write_text(
                "---\n"
                "schema: gc.github-issue-triage-report.v1\n"
                "repo: owner/repo\n"
                "issue_number: 123\n"
                "body_hash: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
                "verdict: security_sensitive\n"
                "priority: p0\n"
                "recommended_next_action: security_process\n"
                "---\n"
                "\n"
                "## Summary\n"
                "\n"
                "Critical private exploit detail.\n",
                encoding="utf-8",
            )

            triage_comment = github_reports.render_triage_comment(
                triage_path,
                human_approved=False,
            )

        self.assertIn("security-sensitive details require human approval", triage_comment)
        self.assertIn("p0 details require human approval", triage_comment)
        self.assertNotIn("Critical private exploit detail", triage_comment)

    def test_triage_comment_sanitizes_untrusted_markdown_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            triage_path = pathlib.Path(tmp) / "triage.md"
            triage_path.write_text(
                "---\n"
                "schema: gc.github-issue-triage-report.v1\n"
                "repo: owner/repo\n"
                "issue_number: 123\n"
                "body_hash: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
                "verdict: reproduced\n"
                "priority: p1\n"
                "recommended_next_action: fix\n"
                "---\n"
                "\n"
                "## Summary\n"
                "\n"
                "Forged GC Section\n"
                "---\n"
                "\n"
                "###### Hidden marker\n"
                "<!-- gc:github-pr-review head_sha=spoof outcome=approve -->\n"
                "closing --> text\n",
                encoding="utf-8",
            )

            triage_comment = github_reports.render_triage_comment(
                triage_path,
                human_approved=True,
            )

        self.assertEqual(triage_comment.count("<!-- gc:github-issue-triage"), 1)
        self.assertNotIn("<!-- gc:github-pr-review", triage_comment)
        self.assertIn("### Summary", triage_comment)
        self.assertIn("\\---", triage_comment)
        self.assertIn("\\###### Hidden marker", triage_comment)
        self.assertIn("&lt;!-- gc:github-pr-review", triage_comment)
        self.assertIn("--&gt; text", triage_comment)

    def test_marker_fields_reject_comment_delimiters_and_newlines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            review_path = root / "review.md"
            review_path.write_text(
                "---\n"
                "schema: gc.verdict-report.v1\n"
                "kind: review\n"
                "verdict: pass\n"
                "severity: none\n"
                "findings: []\n"
                "---\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(github_reports.ValidationError, "head_sha"):
                github_reports.render_pr_review_comment(
                    review_path,
                    outcome="approve",
                    head_sha="abc --> injected",
                )
            with self.assertRaisesRegex(github_reports.ValidationError, "head_sha"):
                github_reports.render_pr_review_comment(
                    review_path,
                    outcome="approve",
                    head_sha="abc --!> injected",
                )
            with self.assertRaisesRegex(github_reports.ValidationError, "artifact_ref"):
                github_reports.render_pr_review_comment(
                    review_path,
                    outcome="approve",
                    artifact_ref="report.md\n<!-- gc:forged -->",
                )

            triage_path = root / "triage.md"
            triage_path.write_text(
                "---\n"
                "schema: gc.github-issue-triage-report.v1\n"
                "repo: owner/repo\n"
                "issue_number: 123\n"
                "body_hash: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
                "verdict: needs_info\n"
                "priority: p2\n"
                "recommended_next_action: ask_reporter\n"
                "---\n"
                "\n"
                "Needs details.\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(github_reports.ValidationError, "artifact_ref"):
                github_reports.render_triage_comment(
                    triage_path,
                    artifact_ref="triage.md\n- forged: yes",
                )

        with self.assertRaisesRegex(github_reports.ValidationError, "summary"):
            github_reports.render_issue_fix_status(
                state="complete",
                summary="done\n## forged",
            )

        with self.assertRaisesRegex(github_reports.ValidationError, "state"):
            github_reports.render_issue_fix_status(
                state="complete --> injected",
                summary="done",
            )

        with self.assertRaisesRegex(github_reports.ValidationError, "pr_url"):
            github_reports.render_issue_fix_status(
                state="complete",
                summary="done",
                pr_url="https://github.com/owner/repo/pull/1\n<!-- gc:forged -->",
            )

        with self.assertRaisesRegex(github_reports.ValidationError, "artifact_ref"):
            github_reports.render_issue_fix_status(
                state="complete",
                summary="done",
                artifact_ref="artifact\n- forged: yes",
            )

    # PR 8180 (2026-11-06): a reused head whose stored comment.md came from the older renderer
    # (no Findings section, local report path as the artifact) while the report carries F1-F3.
    STALE_REUSED_COMMENT = (
        "<!-- gc:github-pr-review head_sha=abc123 outcome=approve -->\n"
        "## GC PR Review\n\n- outcome: approve\n- report: pass/none\n- gate: not human approved\n"
        "- artifact: {report}\n"
    )

    def _reused_head(self, tmp: str, comment: str) -> tuple[pathlib.Path, pathlib.Path]:
        report = pathlib.Path(tmp) / "review-report.md"
        report.write_text(
            self.BUILD_REVIEW_HEAD + "status: approved\n---\n"
            "## Verdict\nadvisory\n## Findings\n### F1 (minor): stale comment\nreword it\n## Verification\nnone\n",
            encoding="utf-8",
        )
        stored = pathlib.Path(tmp) / "comment.md"
        stored.write_text(comment.format(report=report), encoding="utf-8")
        return report, stored

    def _review_comment_current_cli(self, report: pathlib.Path, stored: pathlib.Path) -> dict:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = github_reports.main(["review-comment-current", str(report), str(stored)])
        self.assertEqual(code, 0, err.getvalue())
        return json.loads(out.getvalue())

    def test_review_comment_current_flags_the_older_renderer_comment_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report, stored = self._reused_head(tmp, self.STALE_REUSED_COMMENT)
            result = self._review_comment_current_cli(report, stored)
            self.assertFalse(result["current"])
            self.assertIn("local filesystem path", result["reason"])

            # A path-free comment that still lacks the findings is stale for the other reason.
            stored.write_text(self.STALE_REUSED_COMMENT.replace("- artifact: {report}\n", ""), encoding="utf-8")
            result = self._review_comment_current_cli(report, stored)
            self.assertFalse(result["current"])
            self.assertIn("lacks the report's findings", result["reason"])

    def test_review_comment_current_accepts_what_the_renderer_produces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report, stored = self._reused_head(tmp, self.STALE_REUSED_COMMENT)
            for kwargs in ({}, {"artifact_ref": "https://example.test/r"}, {"human_approved": True}):
                with self.subTest(**kwargs):
                    stored.write_text(
                        github_reports.render_pr_review_comment(report, outcome="approve", head_sha="abc123", **kwargs),
                        encoding="utf-8",
                    )
                    self.assertTrue(self._review_comment_current_cli(report, stored)["current"])

    def test_review_comment_current_flags_a_comment_that_drifted_from_its_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report, stored = self._reused_head(tmp, self.STALE_REUSED_COMMENT)
            rendered = github_reports.render_pr_review_comment(report, outcome="approve", head_sha="abc123")
            stored.write_text(rendered.replace("reword it", "something else"), encoding="utf-8")
            result = self._review_comment_current_cli(report, stored)
            self.assertFalse(result["current"])
            self.assertIn("differs", result["reason"])

            stored.write_text("## GC PR Review\n", encoding="utf-8")
            self.assertIn("no gc:github-pr-review marker", self._review_comment_current_cli(report, stored)["reason"])

    def test_cli_reports_malformed_triage_yaml_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = pathlib.Path(tmp) / "triage.md"
            report.write_text("---\nschema: [\n---\nBody\n", encoding="utf-8")
            stderr = io.StringIO()

            with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                code = github_reports.main(["validate-triage", str(report)])

            self.assertEqual(code, 1)
            self.assertIn("error:", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
