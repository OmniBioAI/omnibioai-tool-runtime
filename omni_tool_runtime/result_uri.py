# omni_tool_runtime/result_uri.py
"""
OmniBioAI omni_tool_runtime.result_uri.

Purpose:
    Defines ParsedResultURI and parse_result_uri for omni_tool_runtime.result_uri.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ParsedResultURI:
    scheme: str
    account_or_bucket: str
    container: str | None
    path: str  # key/blob path


def parse_result_uri(uri: str) -> ParsedResultURI:
    u = urlparse(uri)
    if not u.scheme:
        raise ValueError(f"Invalid RESULT_URI (missing scheme): {uri}")

    if u.scheme == "s3":
        bucket = u.netloc
        key = u.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"Invalid s3:// URI: {uri}")
        return ParsedResultURI(scheme="s3", account_or_bucket=bucket, container=None, path=key)

    if u.scheme == "azureblob":
        account = u.netloc
        p = u.path.lstrip("/")
        parts = p.split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid azureblob:// URI (need container/path): {uri}")
        container, blob_path = parts[0], parts[1]
        if not account or not container or not blob_path:
            raise ValueError(f"Invalid azureblob:// URI: {uri}")
        return ParsedResultURI(
            scheme="azureblob", account_or_bucket=account, container=container, path=blob_path
        )

    if u.scheme == "gs":
        bucket = u.netloc
        key = u.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"Invalid gs:// URI: {uri}")
        return ParsedResultURI(scheme="gs", account_or_bucket=bucket, container=None, path=key)

    raise ValueError(f"Unsupported RESULT_URI scheme {u.scheme!r}: {uri}")
