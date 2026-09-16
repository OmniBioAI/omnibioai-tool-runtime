#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

TEMPLATE_RUN = """from __future__ import annotations

import json
import os
import sys

from omni_tool_runtime.contract import read_contract_from_env
from omni_tool_runtime.safe_log import describe_inputs
from omni_tool_runtime.upload_result import upload_to_result_uri


def main() -> int:
    c = read_contract_from_env()

    # TODO: validate inputs
    # Example:
    # x = c.inputs.get("x")
    # if x is None:
    #     result_obj = {"ok": False, "error": "missing inputs.x", "tool_id": c.tool_id, "run_id": c.run_id}
    #     code = 2
    # else:
    #     result_obj = {"ok": True, "tool_id": c.tool_id, "run_id": c.run_id, "results": {"x": x}}
    #     code = 0

    result_obj = {
        "ok": True,
        "tool_id": c.tool_id,
        "run_id": c.run_id,
        "results": {"message": "TODO: implement tool logic"},
        "inputs": c.inputs,
    }
    code = 0

    body = json.dumps(result_obj, indent=2).encode("utf-8")

    # PHI-safe logging: never print raw workflow input values or fully
    # resolved commands. Log key names/types only; the full result above
    # still goes to RESULT_URI, which is the access-controlled output
    # channel. See docs on PHI-safe runtime logging before changing this.
    print(json.dumps({
        "ok": result_obj["ok"],
        "tool_id": c.tool_id,
        "run_id": c.run_id,
        "input_summary": describe_inputs(c.inputs),
    }, indent=2))

    if not c.result_uri:
        print("ERROR: RESULT_URI not set", file=sys.stderr)
        return 3

    uri = c.result_uri.rstrip("/") + "/results.json"

    azure_auth = os.getenv("AZURE_AUTH", "managed_identity")
    azure_cs = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    aws_profile = os.getenv("AWS_PROFILE")

    upload_to_result_uri(
        result_uri=uri,
        data=body,
        content_type="application/json",
        aws_profile=aws_profile,
        azure_auth=azure_auth,
        azure_connection_string=azure_cs,
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
"""

TEMPLATE_INIT = "from __future__ import annotations\n"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: scripts/new_tool.py <tool_id>", file=sys.stderr)
        return 2

    tool_id = sys.argv[1].strip()
    if not re.fullmatch(r"[a-z0-9_]+", tool_id):
        print("tool_id must match ^[a-z0-9_]+$", file=sys.stderr)
        return 2

    root = Path(__file__).resolve().parents[1]
    tools_dir = root / "tools"
    pkg_dir = tools_dir / tool_id

    pkg_dir.mkdir(parents=True, exist_ok=True)

    (tools_dir / "__init__.py").write_text(TEMPLATE_INIT, encoding="utf-8")
    (pkg_dir / "__init__.py").write_text(TEMPLATE_INIT, encoding="utf-8")
    run_py = pkg_dir / "run.py"
    if run_py.exists():
        print(f"Refusing to overwrite existing {run_py}", file=sys.stderr)
        return 2
    run_py.write_text(TEMPLATE_RUN, encoding="utf-8")

    print(f"Created tool skeleton at: {pkg_dir}")
    print(f"Run locally: python -m tools.{tool_id}.run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
