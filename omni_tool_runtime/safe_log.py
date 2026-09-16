# omni_tool_runtime/safe_log.py
"""
PHI-safe logging helpers.

Workflow inputs (sample/patient identifiers, file paths, genomic/clinical
parameters) and fully-resolved command lines must never be written to
runtime operational logs verbatim. These helpers produce structural,
non-reversible summaries that preserve debugging/correlation value
without exposing the underlying sensitive value.

`ref` fields are a one-way SHA-256 prefix: useful to confirm two log
lines refer to the same value, not to recover the value itself.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any


def hash_value(value: Any, length: int = 12) -> str:
    s = value if isinstance(value, (str, bytes)) else str(value)
    b = s.encode("utf-8", errors="replace") if isinstance(s, str) else s
    return hashlib.sha256(b).hexdigest()[:length]


def describe_value(value: Any) -> dict[str, Any]:
    """Structural, PHI-safe description of a single value. Never returns the value itself."""
    if isinstance(value, str):
        return {"type": "str", "len": len(value), "ref": hash_value(value)}
    if isinstance(value, bool):
        return {"type": "bool"}
    if isinstance(value, (int, float)):
        return {"type": type(value).__name__}
    if isinstance(value, (list, tuple)):
        return {"type": type(value).__name__, "count": len(value)}
    if isinstance(value, dict):
        return {"type": "dict", "keys": len(value)}
    if value is None:
        return {"type": "null"}
    return {"type": type(value).__name__}


def describe_inputs(inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Key-name-preserving, value-redacting summary of a workflow inputs dict."""
    return {str(k): describe_value(v) for k, v in (inputs or {}).items()}


def safe_cmd_summary(cmd: Iterable[str]) -> dict[str, Any]:
    """Structural summary of a resolved command line — never the raw argv/values."""
    cmd_list: list[str] = [str(c) for c in cmd]
    exe = cmd_list[0] if cmd_list else ""
    return {
        "executable": exe,
        "argc": len(cmd_list),
        "ref": hash_value(" ".join(cmd_list)),
    }
