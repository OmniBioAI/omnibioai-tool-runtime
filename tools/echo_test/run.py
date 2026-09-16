# tools/echo_test/run.py
from __future__ import annotations

import json
import os

from omni_tool_runtime.safe_log import describe_inputs, describe_value
from omni_tool_runtime.upload_result import upload_to_result_uri


def main() -> int:
    tool_id = os.getenv("TOOL_ID", "")
    run_id = os.getenv("RUN_ID", "")
    result_uri = (os.getenv("RESULT_URI", "") or "").strip()

    inputs_json = os.getenv("INPUTS_JSON", "{}")
    try:
        inputs = json.loads(inputs_json)
    except Exception as e:
        out = {"ok": False, "error": f"bad INPUTS_JSON: {e}", "tool_id": tool_id, "run_id": run_id}
        print(json.dumps(out))
        return 2

    text = inputs.get("text")  # keep strict contract (or: inputs.get("text") or inputs.get("msg"))
    if text is None:
        result_obj = {
            "ok": False,
            "error": "missing inputs.text",
            "tool_id": tool_id,
            "run_id": run_id,
            "inputs": inputs,
        }
        log_obj = {
            "ok": False,
            "error": "missing inputs.text",
            "tool_id": tool_id,
            "run_id": run_id,
            "input_summary": describe_inputs(inputs),
        }
    else:
        result_obj = {
            "ok": True,
            "tool_id": tool_id,
            "run_id": run_id,
            "results": {"echo": text},
        }
        log_obj = {
            "ok": True,
            "tool_id": tool_id,
            "run_id": run_id,
            "echo_summary": describe_value(text),
        }

    body = json.dumps(result_obj, indent=2)

    # PHI-safe: log a structural summary only — never the raw echoed value
    # or raw inputs dict. The full `result_obj`/`body` (which may carry a
    # caller-supplied value) still goes to RESULT_URI unredacted below,
    # which is this tool's intended, access-controlled output channel.
    print(json.dumps(log_obj, indent=2))

    # If RESULT_URI not set -> local mode: succeed
    if not result_uri:
        return 0

    # Cloud mode: upload
    upload_to_result_uri(result_uri=result_uri, content=body.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
