#!/usr/bin/env python3
"""Emit shell exports for codex/claude resume gating (eval in turn scripts)."""
from __future__ import annotations

import argparse
import json
import pathlib
import shlex
import sys
import time

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from resume_policy import marker_still_valid, resume_allowed_for_role  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--role", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--blind", type=int, default=0)
    ap.add_argument("--planner-mode", choices=("fresh", "refine"), default="fresh")
    ap.add_argument("--force-resume", action="store_true")
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--marker", type=pathlib.Path, required=True)
    ap.add_argument("--git-sha", default="")
    ap.add_argument("--autopilot", default="0")
    args = ap.parse_args(argv)

    allowed, reason = resume_allowed_for_role(
        args.role,
        blind=bool(args.blind),
        planner_mode=args.planner_mode,
        force_resume=args.force_resume,
        no_resume=args.no_resume,
    )
    sid = ""
    run_resume = False
    if allowed and args.marker.exists():
        try:
            data = json.loads(args.marker.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        sid = str(data.get("session_id") or "").strip()
        marker_model = str(data.get("model") or "").strip()
        marker_git = str(data.get("git_sha") or "").strip()
        ts = float(data.get("ts") or 0)
        age = max(0.0, time.time() - ts)
        ttl = 86400.0
        ok_m, reason_m = marker_still_valid(
            marker_age_s=age,
            ttl_s=ttl,
            marker_model=marker_model,
            current_model=args.model.strip(),
            marker_git_sha=marker_git or None,
            current_git_sha=args.git_sha.strip() or None,
            autopilot_continue=args.autopilot == "1",
            force_resume=args.force_resume,
        )
        run_resume = bool(sid and ok_m)
        if not ok_m:
            reason = reason_m

    print(f"export ROUNDTABLE_RESUME_ALLOWED={1 if allowed else 0}")
    print(f"export ROUNDTABLE_RESUME_REASON={shlex.quote(reason)}")
    print(f"export ROUNDTABLE_RUN_RESUME={1 if run_resume else 0}")
    print(f"export ROUNDTABLE_SESSION_ID={shlex.quote(sid)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
