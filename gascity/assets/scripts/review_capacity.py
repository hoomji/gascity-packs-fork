#!/usr/bin/env python3
"""Can anyone serve this review workflow? A deterministic capacity verdict.

run-review waits on the review it launched; a step routed to an agent gc will
not start a session for makes that wait endless (2026-11-05: write-report sat
~6 h behind a provider red until 11-11 with no fallback). Verdict:
  hold  a ready, unclaimed work step of the review is routed to an agent with
        no live session, and (a) its provider and every fallback_providers
        entry is red in .gc/cache/provider-health.json by gc's rule
        (docs/reference/config.md), or (b) it stayed unclaimed past
        --claim-timeout (0 disables (b)). Unknown or stale health is not red.
  ok    otherwise.
Prints one JSON object. Exit 0 ok, 3 hold (reason starts "reviewer_capacity:"),
75 gc unreachable. Usage: review_capacity.py <review-root-id> [--claim-timeout 20m]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

HOLD, INFRA = 3, 75
# Orchestrator-owned bead kinds (formula-spec-v2 "Control kinds" and
# structural kinds): no session claims them, so they never signal capacity.
NOT_WORK = {"retry", "ralph", "check", "retry-eval", "fanout", "drain", "scope-check",
            "workflow-finalize", "scope", "cleanup", "spec"}
DEFAULT_TTL_S = 60.0  # gc providerHealthTTL, used when a record has no ttl_s
DEAD_STATES = {"closed", "suspended", "drained"}


class Unreachable(Exception):
    """gc gave no answer."""


def gc(*args: str) -> str:
    city = os.environ.get("GC_CITY_PATH", "")
    cmd = ["gc", *(["--city", city] if city else []), *args]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unreachable(f"{' '.join(args[:2])}: {exc}") from exc
    if out.returncode != 0:
        raise Unreachable(f"{' '.join(args[:2])}: exit {out.returncode}: {out.stderr.strip()[:200]}")
    return out.stdout


def seconds(text: str) -> float:
    total, rest = 0.0, text.strip()
    if rest in ("", "0"):
        return 0.0
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)([smh])", rest):
        total += float(num) * {"s": 1, "m": 60, "h": 3600}[unit]
    if not total or re.sub(r"\d+(?:\.\d+)?[smh]", "", rest):
        raise SystemExit(f"review_capacity: bad --claim-timeout {text!r} (want e.g. 20m, 1h30m, 0)")
    return total


def span(secs: float) -> str:
    return f"{int(secs // 60)}m" if secs >= 60 else f"{int(secs)}s"


def red_providers(now: float) -> dict[str, str]:
    """Providers gc treats as red right now, with the health file's reason."""
    path = Path(os.environ.get("GC_CITY_PATH", "")) / ".gc" / "cache" / "provider-health.json"
    try:
        records = json.loads(path.read_text(encoding="utf-8")).get("providers") or []
    except (OSError, ValueError, AttributeError):
        return {}  # no registry: fail open, as gc does
    red: dict[str, str] = {}
    for rec in records:
        # gc's providerHealthRecord.liveAt: an unhealthy record with a future
        # `until` always speaks; otherwise only within ttl_s (default 60 s).
        healthy = rec.get("status") == "healthy"
        held = not healthy and float(rec.get("until") or 0) > now
        ttl = float(rec.get("ttl_s") or 0) or DEFAULT_TTL_S
        if not (held or now - float(rec.get("probed_at") or 0) <= ttl):
            continue  # stale: gc fails open
        if healthy:
            red.pop(rec.get("provider", ""), None)
        else:
            red[rec.get("provider", "")] = str(rec.get("reason") or "unhealthy")
    return red


def agent_providers(cfg: dict, routed_to: str) -> list[str] | None:
    """[primary, *fallbacks] gc would try for a fresh session, None if unknown."""
    rig, _, name = routed_to.rpartition("/")
    for agent in cfg.get("agent") or []:
        an = agent.get("name", "")
        if (agent.get("dir") or "") == rig and (name == an or name.endswith("." + an)):
            if agent.get("start_command"):
                return []  # launches a command, not a provider: never held red
            primary = agent.get("provider") or (cfg.get("workspace") or {}).get("provider")
            # `gc config show` prints the resolved list: [agent_defaults] already
            # merged in, and an explicit `fallback_providers = []` opt-out omitted.
            fallbacks = agent.get("fallback_providers") or []
            return [p for p in [primary, *fallbacks] if p] if primary else None
    return None


def verdict(review_root: str, claim_timeout: float, now: float) -> tuple[int, dict]:
    rows = json.loads(gc("ready", "--metadata-field", f"gc.root_bead_id={review_root}", "--metadata-field",
                         "gc.routed_to", "--unassigned", "--json", "--limit", "0") or "[]")
    waiting = [r for r in rows if (r.get("metadata") or {}).get("gc.kind", "") not in NOT_WORK]
    if not waiting:
        return 0, {"verdict": "ok", "reason": "no ready unclaimed work step"}
    cfg = tomllib.loads(gc("config", "show"))
    red = red_providers(now)
    for row in waiting:
        meta = row.get("metadata") or {}
        agent = meta["gc.routed_to"]
        listing = json.loads(gc("session", "list", "--json", "--state", "all", "--template", agent) or "{}")
        live = [s for s in listing.get("sessions") or []
                if not s.get("closed") and s.get("state", "") not in DEAD_STATES]
        if live:
            continue
        step = f"{row.get('id')} ({meta.get('gc.step_id', '?')})"
        chain = agent_providers(cfg, agent)
        if chain and all(p in red for p in chain):
            held = "; ".join(f"{p}: {red[p]}" for p in chain)
            reason = (f"reviewer_capacity: {step} is routed to {agent}, which has no live session and "
                      f"no healthy provider in provider + fallback_providers ({held})")
            return HOLD, {"verdict": "hold", "failure_class": "reviewer_capacity", "step": row.get("id"),
                          "agent": agent, "reason": reason}
        try:
            created = datetime.fromisoformat(str(row.get("created_at")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue  # no age to judge; the provider arm above still applies
        if claim_timeout and now - created > claim_timeout:
            reason = (f"reviewer_capacity: {step} routed to {agent} unclaimed for {span(now - created)} "
                      f"with zero {agent} sessions (claim timeout {span(claim_timeout)})")
            return HOLD, {"verdict": "hold", "failure_class": "reviewer_capacity", "step": row.get("id"),
                          "agent": agent, "reason": reason}
    return 0, {"verdict": "ok", "reason": f"{len(waiting)} waiting step(s) can still be served"}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("review_root")
    parser.add_argument("--claim-timeout", default="20m")
    args = parser.parse_args(argv)
    try:
        code, out = verdict(args.review_root, seconds(args.claim_timeout), time.time())
    except Unreachable as exc:
        code, out = INFRA, {"verdict": "unknown", "reason": f"gc unreachable: {exc}"}
    print(json.dumps(out))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
