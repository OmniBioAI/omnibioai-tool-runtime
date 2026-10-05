# omni_tool_runtime/uploaders/s3_uploader.py
"""
OmniBioAI omni_tool_runtime.uploaders.s3_uploader.

Purpose:
    Defines S3Uploader with upload_bytes methods for omni_tool_runtime.uploaders.s3_uploader.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class S3Uploader:
    aws_profile: str | None = None

    def upload_bytes(self, *, bucket: str, key: str, data: bytes, content_type: str) -> None:
        try:
            import boto3
        except Exception as e:
            raise RuntimeError(f"boto3 not installed (install omnibioai-tool-runtime[aws]): {e}")

        session_kwargs = {}
        if self.aws_profile:
            session_kwargs["profile_name"] = self.aws_profile
        session = boto3.Session(**session_kwargs)
        s3 = session.client("s3")
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
