import json
import os
import subprocess
import sys


def test_echo_test_local_mode_no_result_uri():
    env = dict(os.environ)
    env["TOOL_ID"] = "echo_test"
    env["RUN_ID"] = "local123"
    env["INPUTS_JSON"] = json.dumps({"text": "hello"})
    env["RESOURCES_JSON"] = json.dumps({"cpu": 1})
    env["RESULT_URI"] = ""  # local mode

    p = subprocess.run(
        [sys.executable, "-m", "tools.echo_test.run"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0
    out = json.loads(p.stdout)
    assert out["ok"] is True
    # PHI-safe: the raw echoed value must never appear in process stdout/logs.
    assert "echo_summary" in out
    assert "results" not in out
    assert "hello" not in p.stdout
