# Autopilot × Codex resume — expected token synergy

`/roundtable-goal` autopilot (Cursor `stop` hook H5) can issue many consecutive executor rounds. Without session resume, each round re-ingests the full `build_prompt` package (~10–80k+ input tokens depending on thread size).

With **Codex `codex exec resume <session_id>`** (and Claude `--continue`, coarse session affinity), subsequent executor rounds send primarily the **addendum delta**, while provider-side caching handles the stable prefix.

## Rule-of-thumb scenario

| Mode | Approx input tokens / executor round |
|------|--------------------------------------|
| Fresh full prompt every round | ~80k × N rounds |
| Resume + delta addendum | ~80k first round + ~8k × (N−1) |

For **N = 15**, naive fresh totals ~**1.2M** input tokens vs resumed ~**192k** (~**84%** reduction). Exact ratios depend on thread tail length and whether GOAL / PLAN grew between rounds.

## Hook protocol field

`followup_message` includes `prefer_resume=1` so the Goal orchestrator exports **`ROUNDTABLE_AUTOPILOT_CONTINUE=1`**, which bypasses the **24h TTL** gate in `scripts/lib/_resume.sh` while **still enforcing**:

- marker **model** match vs current `--model`
- marker **git_sha** vs `HEAD` (working tree progression must invalidate stale codex workspace assumptions)

## Measuring locally

After each Codex turn inspect `<hist>/usage.json` (written by `extract_codex_usage.py`). Compare `cached_input_ratio` across round 1 vs round 2+ — resumed rounds should show sharply higher cached fraction when the backend honors prompt caching.
