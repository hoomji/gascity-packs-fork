#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import validate_verdict_report

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


FRONT_MATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---(?:\n|\Z)", re.DOTALL)
BODY_HASH_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
UNSAFE_MARKER_RE = re.compile(r"<!--|--!?>|[\r\n]")
VALID_TRIAGE_VERDICTS = {
    "reproduced",
    "not_reproduced",
    "needs_info",
    "not_a_bug",
    "duplicate",
    "security_sensitive",
}
VALID_PRIORITIES = {"p0", "p1", "p2", "p3"}
VALID_ACTIONS = {"fix", "test_hardening", "close", "ask_reporter", "defer", "security_process"}
VALID_ACTIONS_BY_VERDICT = {
    "reproduced": {"fix", "defer"},
    "not_reproduced": {"test_hardening", "defer"},
    "needs_info": {"ask_reporter"},
    "not_a_bug": {"close"},
    "duplicate": {"close"},
    "security_sensitive": {"security_process"},
}


class ValidationError(Exception):
    pass


# The generic `review` formula's write-report step is validated against its artifact schema,
# gc.build.review.v1 (schemas/build/review.v1.yaml), so its report never carries
# gc.verdict-report.v1. Read both: verdict fields when the reviewer recorded them, else status.
BUILD_REVIEW_SCHEMA = "gc.build.review.v1"
BUILD_REVIEW_STATUS_VERDICTS = {
    "approved": ("pass", "none"),
    "changes_required": ("fail", "major"),
    "blocked": ("fail", "blocker"),
}


def load_review_report(text: str) -> validate_verdict_report.VerdictReport:
    match = FRONT_MATTER_RE.match(text)
    data = yaml.safe_load(match.group("body")) if match and yaml is not None else None
    if not isinstance(data, dict) or data.get("schema") != BUILD_REVIEW_SCHEMA:
        return validate_verdict_report.validate_report_text(text, expected_kind="review")
    status = data.get("status")
    if status not in BUILD_REVIEW_STATUS_VERDICTS:
        raise ValidationError(
            f"{BUILD_REVIEW_SCHEMA} status must be one of {sorted(BUILD_REVIEW_STATUS_VERDICTS)} "
            f"for a finished review, got {status!r}"
        )
    status_verdict, status_severity = BUILD_REVIEW_STATUS_VERDICTS[status]
    if "verdict" not in data and "severity" not in data:
        return validate_verdict_report.VerdictReport(
            schema=BUILD_REVIEW_SCHEMA, kind="review", verdict=status_verdict, severity=status_severity, findings=[]
        )
    report = validate_verdict_report.validate_report_data(
        {**data, "schema": "gc.verdict-report.v1", "kind": data.get("kind") or "review"}, expected_kind="review"
    )
    if report.verdict != status_verdict:
        raise ValidationError(f"status {status!r} contradicts verdict {report.verdict!r}")
    return report


YAML_ERROR_TYPES = (yaml.YAMLError,) if yaml is not None else ()
CLI_ERROR_TYPES = (OSError, UnicodeDecodeError, ValidationError, validate_verdict_report.ValidationError) + YAML_ERROR_TYPES


@dataclass(frozen=True)
class TriageReport:
    schema: str
    repo: str
    issue_number: int
    body_hash: str
    verdict: str
    priority: str
    recommended_next_action: str
    reproduction_artifact_path: str
    reproduction_diff_path: str
    analysis_body: str


def validate_triage_report_text(
    text: str,
    *,
    expected_repo: str = "",
    expected_issue_number: int = 0,
    expected_body_hash: str = "",
) -> TriageReport:
    if yaml is None:
        raise ValidationError("PyYAML is required to parse triage reports")
    match = FRONT_MATTER_RE.match(text)
    if not match:
        raise ValidationError("triage report must start with YAML front matter")
    data = yaml.safe_load(match.group("body")) or {}
    if not isinstance(data, dict):
        raise ValidationError("triage report front matter must be a mapping")

    schema = required_string(data, "schema")
    repo = required_string(data, "repo")
    issue_number = required_int(data, "issue_number")
    body_hash = required_string(data, "body_hash")
    verdict = required_string(data, "verdict")
    priority = required_string(data, "priority")
    recommended_next_action = required_string(data, "recommended_next_action")
    reproduction_artifact_path = optional_string(data, "reproduction_artifact_path")
    reproduction_diff_path = optional_string(data, "reproduction_diff_path")

    if schema != "gc.github-issue-triage-report.v1":
        raise ValidationError(f"schema must be gc.github-issue-triage-report.v1, got {schema!r}")
    if issue_number <= 0:
        raise ValidationError("issue_number must be a positive integer")
    if not BODY_HASH_RE.match(body_hash):
        raise ValidationError("body_hash must be sha256:<64 lowercase hex chars>")
    if verdict not in VALID_TRIAGE_VERDICTS:
        raise ValidationError(f"verdict must be one of {sorted(VALID_TRIAGE_VERDICTS)}, got {verdict!r}")
    if priority not in VALID_PRIORITIES:
        raise ValidationError(f"priority must be one of {sorted(VALID_PRIORITIES)}, got {priority!r}")
    if recommended_next_action not in VALID_ACTIONS:
        raise ValidationError(f"recommended_next_action must be one of {sorted(VALID_ACTIONS)}")
    if recommended_next_action not in VALID_ACTIONS_BY_VERDICT[verdict]:
        raise ValidationError(f"recommended_next_action {recommended_next_action!r} is invalid for verdict {verdict!r}")
    if expected_repo and repo != expected_repo:
        raise ValidationError(f"repo must be {expected_repo!r}, got {repo!r}")
    if expected_issue_number and issue_number != expected_issue_number:
        raise ValidationError(f"issue_number must be {expected_issue_number}, got {issue_number}")
    if expected_body_hash and body_hash != expected_body_hash:
        raise ValidationError(f"body_hash must be {expected_body_hash!r}, got {body_hash!r}")
    analysis_body = text[match.end() :].strip()
    if not analysis_body:
        raise ValidationError("triage report analysis body must not be empty")
    return TriageReport(
        schema=schema,
        repo=repo,
        issue_number=issue_number,
        body_hash=body_hash,
        verdict=verdict,
        priority=priority,
        recommended_next_action=recommended_next_action,
        reproduction_artifact_path=reproduction_artifact_path,
        reproduction_diff_path=reproduction_diff_path,
        analysis_body=analysis_body,
    )


def review_outcome(verdict: str, severity: str) -> str:
    if verdict == "pass" and severity == "none":
        return "approve"
    if verdict == "fail" and severity == "minor":
        return "comment"
    if verdict == "fail" and severity == "major":
        return "request_changes"
    if verdict == "fail" and severity == "blocker":
        return "block"
    raise ValidationError(f"unsupported review verdict/severity combination: {verdict}/{severity}")


# GitHub rejects comment bodies over 65,536 characters; keep headroom for the header lines.
MAX_FINDINGS_CHARS = 60_000
FINDINGS_HEADING_RE = re.compile(r"^##\s+Findings\s*$", re.MULTILINE)
NEXT_H2_RE = re.compile(r"^##\s", re.MULTILINE)


def render_pr_review_comment(
    report_path: Path,
    *,
    outcome: str,
    head_sha: str = "",
    artifact_ref: str = "",
    human_approved: bool = False,
) -> str:
    text = report_path.read_text(encoding="utf-8")
    report = load_review_report(text)
    if outcome != review_outcome(report.verdict, report.severity):
        raise ValidationError(f"outcome {outcome!r} does not match review report {report.verdict}/{report.severity}")
    head_sha = marker_value("head_sha", head_sha)
    gate_text = "human approved" if human_approved else "not human approved"
    lines = [
        f"<!-- gc:github-pr-review head_sha={head_sha} outcome={outcome} -->",
        "## GC PR Review",
        "",
        f"- outcome: {outcome}",
        f"- report: {report.verdict}/{report.severity}",
        f"- gate: {gate_text}",
    ]
    # A local report path means nothing to a PR reader; name an artifact only when the caller
    # supplies a public reference.
    if artifact_ref:
        lines.append(f"- artifact: {public_line('artifact_ref', artifact_ref)}")
    if report.findings:
        findings = "\n".join(render_finding(finding) for finding in report.findings)
    else:
        # gc.build.review.v1 reports (the default `review` formula) keep findings as Markdown
        # under a `## Findings` heading rather than in front matter.
        findings = public_markdown(markdown_findings_section(text))
    if findings:
        lines.extend(["", "### Findings", "", cap_length(findings)])
    return "\n".join(lines) + "\n"


def markdown_findings_section(text: str) -> str:
    match = FRONT_MATTER_RE.match(text)
    body = text[match.end():] if match else text
    heading = FINDINGS_HEADING_RE.search(body)
    if not heading:
        return ""
    rest = body[heading.end():]
    end = NEXT_H2_RE.search(rest)
    return (rest[: end.start()] if end else rest).strip()


def render_finding(finding: dict[str, Any]) -> str:
    def field(key: str, *, inline: bool = False) -> str:
        value = finding.get(key)
        if value in (None, ""):
            return ""
        flat = " ".join(str(value).split())
        if inline:
            # id and title sit inside a bold run: escape anything that would end it or open code.
            return neutralize(re.sub(r"([*_`])", r"\\\1", flat))
        return neutralize_inline(flat)

    head = (
        f"- **{field('id', inline=True) or '?'}** ({field('severity') or 'unrated'}): "
        f"{field('title', inline=True) or 'untitled'}"
    )
    parts = [head]
    if field("evidence"):
        parts.append(f"  - evidence: {field('evidence')}")
    if field("required_fix"):
        parts.append(f"  - fix: {field('required_fix')}")
    return "\n".join(parts)


CODE_SPAN_RE = re.compile(r"(`+)(.+?)\1")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING_SHIFT = 3  # report H1 lands at H4, below the comment's own `### Findings`


def neutralize(text: str) -> str:
    """Make prose inert in a GitHub comment: no raw HTML, no @-mentions."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # A zero-width space after `@` stops GitHub from notifying a real account.
    return re.sub(r"@(?=[A-Za-z0-9])", "@\u200b", text)


def neutralize_inline(line: str) -> str:
    """neutralize() outside code spans; GitHub renders code spans literally, so leave them as written."""
    out, last = [], 0
    for match in CODE_SPAN_RE.finditer(line):
        out.append(neutralize(line[last : match.start()]))
        out.append(match.group(0))
        last = match.end()
    out.append(neutralize(line[last:]))
    return "".join(out)


def public_markdown(text: str) -> str:
    """Keep reviewer Markdown and its code verbatim, but make prose inert and nest headings below ours."""
    lines: list[str] = []
    fence = ""
    for line in text.strip().splitlines():
        marker = FENCE_RE.match(line)
        if fence:
            lines.append(line)
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = ""
            continue
        if marker:
            fence = marker.group(1)
            lines.append(line)
            continue
        lines.append(demote_heading_line(neutralize_inline(line)))
    if fence:
        lines.append(fence)  # never let an unclosed fence swallow the rest of the comment
    return "\n".join(lines).strip()


def demote_heading_line(line: str) -> str:
    hash_heading = re.match(r"^( {0,3})(#{1,6})(\s.*)?$", line)
    if hash_heading:
        level = len(hash_heading.group(2)) + HEADING_SHIFT
        rest = hash_heading.group(3) or ""
        if level <= 6:
            return f"{hash_heading.group(1)}{'#' * level}{rest}"
        return f"{hash_heading.group(1)}**{rest.strip()}**" if rest.strip() else ""
    if re.match(r"^ {0,3}(=+|-+)\s*$", line):
        return "\\" + line.strip()
    return line


def cap_length(text: str) -> str:
    if len(text) <= MAX_FINDINGS_CHARS:
        return text
    cut = text.rfind("\n", 0, MAX_FINDINGS_CHARS)
    cut = cut if cut > 0 else MAX_FINDINGS_CHARS
    kept = text[:cut]
    open_fence = ""
    for line in kept.splitlines():
        marker = FENCE_RE.match(line)
        if marker:
            open_fence = "" if open_fence else marker.group(1)
    if open_fence:
        kept += "\n" + open_fence
    return kept + "\n\n_Findings truncated to fit GitHub's comment size limit; see the full review report._"


def render_triage_comment(
    report_path: Path,
    *,
    artifact_ref: str = "",
    human_approved: bool = False,
) -> str:
    report = validate_triage_report_text(report_path.read_text(encoding="utf-8"))
    repo = marker_value("repo", report.repo, allow_empty=False)
    gate_text = "human approved" if human_approved else "not human approved"
    lines = [
        f"<!-- gc:github-issue-triage repo={repo} issue={report.issue_number} body_hash={report.body_hash} -->",
        "## GC Issue Triage",
        "",
        f"- verdict: {report.verdict}",
        f"- priority: {report.priority}",
        f"- next_action: {report.recommended_next_action}",
        f"- body_hash: {report.body_hash}",
        f"- gate: {gate_text}",
    ]
    if artifact_ref:
        lines.append(f"- artifact: {public_line('artifact_ref', artifact_ref)}")
    approval_notes = []
    if report.verdict == "security_sensitive":
        approval_notes.append("security-sensitive details require human approval before public posting")
    if report.priority == "p0":
        approval_notes.append("p0 details require human approval before public posting")
    if approval_notes and not human_approved:
        lines.append(f"- note: {'; '.join(approval_notes)}")
    elif report.analysis_body:
        lines.extend(["", "## Analysis", "", demote_markdown_headings(report.analysis_body)])
    return "\n".join(lines) + "\n"


def render_issue_fix_status(
    *,
    state: str,
    summary: str,
    run_id: str = "",
    pr_url: str = "",
    artifact_ref: str = "",
) -> str:
    state = marker_value("state", state, allow_empty=False)
    run_id = marker_value("run_id", run_id)
    summary = public_line("summary", summary)
    lines = [
        f"<!-- gc:github-issue-fix-status run_id={run_id} state={state} -->",
        "## GC Issue Fix",
        "",
        f"- state: {state}",
        f"- summary: {summary.strip()}",
    ]
    if pr_url:
        lines.append(f"- pr: {public_line('pr_url', pr_url)}")
    if artifact_ref:
        lines.append(f"- artifact: {public_line('artifact_ref', artifact_ref)}")
    return "\n".join(lines) + "\n"


def required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{key} must be a non-empty string")
    return value.strip()


def optional_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"{key} must be a string")
    return value.strip()


def required_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, int):
        return value
    raise ValidationError(f"{key} must be an integer")


def marker_value(name: str, value: str, *, allow_empty: bool = True) -> str:
    value = value.strip()
    if not value:
        if allow_empty:
            return ""
        raise ValidationError(f"{name} must not be empty")
    if UNSAFE_MARKER_RE.search(value):
        raise ValidationError(f"{name} contains unsafe marker text")
    return value


def public_line(name: str, value: str) -> str:
    value = value.strip()
    if not value:
        raise ValidationError(f"{name} must not be empty")
    if UNSAFE_MARKER_RE.search(value):
        raise ValidationError(f"{name} contains unsafe public text")
    return value


def demote_markdown_headings(text: str) -> str:
    lines: list[str] = []
    for line in text.strip().splitlines():
        safe_line = line.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
        hash_heading = re.match(r"^( {0,3})(#{1,5}\s.*)$", safe_line)
        max_hash_heading = re.match(r"^( {0,3})(#{6,}\s.*)$", safe_line)
        setext_underline = re.match(r"^( {0,3})(=+|-+)\s*$", safe_line)
        if hash_heading:
            lines.append(f"{hash_heading.group(1)}#{hash_heading.group(2)}")
        elif max_hash_heading:
            lines.append(f"{max_hash_heading.group(1)}\\{max_hash_heading.group(2)}")
        elif setext_underline:
            lines.append(f"{setext_underline.group(1)}\\{setext_underline.group(2)}")
        else:
            lines.append(safe_line)
    return "\n".join(lines).strip()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and render GitHub workflow reports")
    subparsers = parser.add_subparsers(dest="command", required=True)

    triage_parser = subparsers.add_parser("validate-triage")
    triage_parser.add_argument("path", type=Path)
    triage_parser.add_argument("--repo", default="")
    triage_parser.add_argument("--issue-number", type=int, default=0)
    triage_parser.add_argument("--body-hash", default="")

    outcome_parser = subparsers.add_parser("review-outcome")
    outcome_parser.add_argument("path", type=Path)

    review_comment_parser = subparsers.add_parser("render-review-comment")
    review_comment_parser.add_argument("report_path", type=Path)
    review_comment_parser.add_argument("--output", type=Path, required=True)
    review_comment_parser.add_argument("--head-sha", default="")
    review_comment_parser.add_argument("--artifact-ref", default="")
    review_comment_parser.add_argument("--human-approved", action="store_true")

    triage_comment_parser = subparsers.add_parser("render-triage-comment")
    triage_comment_parser.add_argument("report_path", type=Path)
    triage_comment_parser.add_argument("--output", type=Path, required=True)
    triage_comment_parser.add_argument("--artifact-ref", default="")
    triage_comment_parser.add_argument("--human-approved", action="store_true")

    fix_status_parser = subparsers.add_parser("render-issue-fix-status")
    fix_status_parser.add_argument("--state", required=True)
    fix_status_parser.add_argument("--summary", required=True)
    fix_status_parser.add_argument("--output", type=Path, required=True)
    fix_status_parser.add_argument("--run-id", default="")
    fix_status_parser.add_argument("--pr-url", default="")
    fix_status_parser.add_argument("--artifact-ref", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.command == "validate-triage":
            report = validate_triage_report_text(
                args.path.read_text(encoding="utf-8"),
                expected_repo=args.repo,
                expected_issue_number=args.issue_number,
                expected_body_hash=args.body_hash,
            )
            output = {"ok": True, "verdict": report.verdict, "recommended_next_action": report.recommended_next_action}
        elif args.command == "review-outcome":
            report = load_review_report(args.path.read_text(encoding="utf-8"))
            output = {"ok": True, "outcome": review_outcome(report.verdict, report.severity)}
        elif args.command == "render-review-comment":
            report = load_review_report(args.report_path.read_text(encoding="utf-8"))
            outcome = review_outcome(report.verdict, report.severity)
            args.output.write_text(
                render_pr_review_comment(
                    args.report_path,
                    outcome=outcome,
                    head_sha=args.head_sha,
                    artifact_ref=args.artifact_ref,
                    human_approved=args.human_approved,
                ),
                encoding="utf-8",
            )
            output = {"ok": True, "outcome": outcome, "output": str(args.output)}
        elif args.command == "render-triage-comment":
            args.output.write_text(
                render_triage_comment(
                    args.report_path,
                    artifact_ref=args.artifact_ref,
                    human_approved=args.human_approved,
                ),
                encoding="utf-8",
            )
            output = {"ok": True, "output": str(args.output)}
        elif args.command == "render-issue-fix-status":
            args.output.write_text(
                render_issue_fix_status(
                    state=args.state,
                    summary=args.summary,
                    run_id=args.run_id,
                    pr_url=args.pr_url,
                    artifact_ref=args.artifact_ref,
                ),
                encoding="utf-8",
            )
            output = {"ok": True, "output": str(args.output)}
        else:  # pragma: no cover
            raise ValidationError(f"unsupported command {args.command}")
    except CLI_ERROR_TYPES as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
