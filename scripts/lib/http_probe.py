#!/usr/bin/env python3
"""Shared HTTP probe for agent-roundtable smoke tests and speed measurements.

Used by backend.sh (apply + validate) and speed_test.py.
stdlib only — no third-party dependencies.
"""
import json
import time
import urllib.error
import urllib.request
from typing import TypedDict

SMOKE_UA = "curl/8.4.0 agent-roundtable-smoke"


class ProbeResult(TypedDict):
    ok: bool
    status: int          # HTTP status code; 0 on network error
    body_preview: str    # first 300 chars of response body
    elapsed_s: float


def _post(url: str, headers: dict, body: dict, timeout: float) -> ProbeResult:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={**headers, "User-Agent": SMOKE_UA},
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return {
                "ok": True,
                "status": r.status,
                "body_preview": raw[:300],
                "elapsed_s": round(time.monotonic() - t0, 3),
            }
    except urllib.error.HTTPError as e:
        body_preview = (e.read() or b"").decode("utf-8", "replace")[:300]
        return {
            "ok": False,
            "status": e.code,
            "body_preview": body_preview,
            "elapsed_s": round(time.monotonic() - t0, 3),
        }
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {
            "ok": False,
            "status": 0,
            "body_preview": str(e)[:300],
            "elapsed_s": round(time.monotonic() - t0, 3),
        }


def ping_codex(base_url: str, api_key: str, model: str, *, timeout: float = 10.0) -> ProbeResult:
    """Send a 1-token OpenAI-compat ping. Returns ProbeResult."""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }
    return _post(url, headers, body, timeout)


def ping_claude(base_url: str, api_key: str, model: str, *, timeout: float = 10.0) -> ProbeResult:
    """Send a 1-token Anthropic-compat ping. Returns ProbeResult."""
    url = base_url.rstrip("/") + "/v1/messages"
    headers = {
        "x-api-key": api_key,
        "Authorization": f"Bearer {api_key}",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
    }
    return _post(url, headers, body, timeout)


if __name__ == "__main__":
    import argparse
    import sys
    p = argparse.ArgumentParser(description="Smoke-ping an LLM endpoint")
    p.add_argument("--endpoint", choices=("codex", "claude"), required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--api-key", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()
    fn = ping_codex if args.endpoint == "codex" else ping_claude
    result = fn(args.base_url, args.api_key, args.model, timeout=args.timeout)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["ok"] else 1)
