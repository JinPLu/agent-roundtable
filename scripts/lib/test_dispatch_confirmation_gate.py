import os, subprocess, pathlib, sys

_COMMON_SH = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "_common.sh"


def _run_gate(env_overrides: dict) -> tuple[int, str]:
    """Run a minimal bash snippet that sources _common.sh and calls check_dispatch_confirmed."""
    script = f"""
set -e
source {_COMMON_SH}
check_dispatch_confirmed
echo "PASSED"
"""
    env = {**os.environ, **env_overrides}
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    output = result.stdout + result.stderr
    return result.returncode, output


def test_gate_blocks_without_env():
    code, out = _run_gate({"ROUNDTABLE_DISPATCH_CONFIRMED": "", "ROUNDTABLE_FORCE": ""})
    assert code != 0, f"Expected non-zero exit without env vars\n{out}"


def test_gate_passes_with_confirmed():
    code, out = _run_gate({"ROUNDTABLE_DISPATCH_CONFIRMED": "1"})
    assert code == 0, f"Expected zero exit with CONFIRMED=1\n{out}"
    assert "PASSED" in out


def test_gate_passes_with_force():
    code, out = _run_gate({"ROUNDTABLE_FORCE": "1", "ROUNDTABLE_DISPATCH_CONFIRMED": ""})
    assert code == 0, f"Expected zero exit with FORCE=1\n{out}"
    assert "PASSED" in out
