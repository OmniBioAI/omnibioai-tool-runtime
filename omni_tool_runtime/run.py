"""
OmniBioAI omni_tool_runtime.run.

Purpose:
    Defines main for omni_tool_runtime.run.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import importlib
import os
import sys


def main() -> int:
    tool_id = (os.getenv("TOOL_ID") or "").strip()
    if not tool_id:
        print("ERROR: TOOL_ID not set", file=sys.stderr)
        return 2

    mod_name = f"tools.{tool_id}.run"
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:
        print(f"ERROR: cannot import {mod_name}: {e}", file=sys.stderr)
        return 2

    if not hasattr(mod, "main"):
        print(f"ERROR: {mod_name} has no main()", file=sys.stderr)
        return 2

    return int(mod.main())


if __name__ == "__main__":
    raise SystemExit(main())
