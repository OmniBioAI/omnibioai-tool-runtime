# omni_tool_runtime/contract.py
"""
OmniBioAI omni_tool_runtime.contract.

Purpose:
    Defines ToolContract and read_contract_from_env for omni_tool_runtime.contract.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolContract:
    tool_id: str
    run_id: str
    inputs: dict[str, Any]
    resources: dict[str, Any]
    result_uri: str


def read_contract_from_env() -> ToolContract:
    tool_id = os.getenv("TOOL_ID", "")
    run_id = os.getenv("RUN_ID", "")
    result_uri = os.getenv("RESULT_URI", "")

    inputs_raw = os.getenv("INPUTS_JSON", "{}")
    resources_raw = os.getenv("RESOURCES_JSON", "{}")

    try:
        inputs = json.loads(inputs_raw)
    except Exception as e:
        raise RuntimeError(f"bad INPUTS_JSON: {e}")

    try:
        resources = json.loads(resources_raw)
    except Exception as e:
        raise RuntimeError(f"bad RESOURCES_JSON: {e}")

    return ToolContract(
        tool_id=tool_id,
        run_id=run_id,
        inputs=inputs,
        resources=resources,
        result_uri=result_uri,
    )
