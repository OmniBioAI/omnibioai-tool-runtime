"""Dispatch of upload_to_result_uri() to the correct cloud uploader implementation based on RESULT_URI scheme.

Developer: Manish Kumar <manish@omnibioai.org>"""
# tests/test_upload_dispatch.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import omni_tool_runtime.upload_result as mod


class _S3Spy:
    """Fake S3Uploader that records upload_bytes() calls instead of touching AWS."""
    def __init__(self, aws_profile=None):
        self.aws_profile = aws_profile
        self.calls = []

    def upload_bytes(self, *, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.calls.append(
            {
                "bucket": bucket,
                "key": key,
                "data": data,
                "content_type": content_type,
                "aws_profile": self.aws_profile,
            }
        )


class _AzureSpy:
    """Fake AzureBlobUploader that records upload_bytes() calls instead of touching Azure."""
    def __init__(self, account_name: str, auth: str = "managed_identity", connection_string=None):
        self.account_name = account_name
        self.auth = auth
        self.connection_string = connection_string
        self.calls = []

    def upload_bytes(
        self, *, container: str, blob_path: str, data: bytes, content_type: str
    ) -> None:
        self.calls.append(
            {
                "account_name": self.account_name,
                "auth": self.auth,
                "connection_string": self.connection_string,
                "container": container,
                "blob_path": blob_path,
                "data": data,
                "content_type": content_type,
            }
        )


def test_upload_dispatch_to_s3(monkeypatch: pytest.MonkeyPatch):
    """Route an s3:// RESULT_URI to S3Uploader with the parsed bucket/key and given aws_profile."""
    _s3_spy = _S3Spy(aws_profile="prof1")

    # Patch constructor used inside upload_to_result_uri
    monkeypatch.setattr(mod, "S3Uploader", lambda aws_profile=None: _S3Spy(aws_profile=aws_profile))
    # But we need the created instance to inspect calls. So patch with closure:
    created = {}

    def _ctor(aws_profile=None):
        created["inst"] = _S3Spy(aws_profile=aws_profile)
        return created["inst"]

    monkeypatch.setattr(mod, "S3Uploader", _ctor)

    uri = "s3://bkt/prefix/run1/results.json"
    payload = b'{"ok": true}'
    mod.upload_to_result_uri(
        result_uri=uri, data=payload, content_type="application/json", aws_profile="prof1"
    )

    inst = created["inst"]
    assert len(inst.calls) == 1
    c = inst.calls[0]
    assert c["bucket"] == "bkt"
    assert c["key"] == "prefix/run1/results.json"
    assert c["data"] == payload
    assert c["content_type"] == "application/json"
    assert c["aws_profile"] == "prof1"


def test_upload_dispatch_to_azureblob(monkeypatch: pytest.MonkeyPatch):
    """Route an azureblob:// RESULT_URI to AzureBlobUploader with the parsed account/container/blob_path and given auth settings."""
    created = {}

    def _ctor(account_name: str, auth: str = "managed_identity", connection_string=None):
        created["inst"] = _AzureSpy(
            account_name=account_name, auth=auth, connection_string=connection_string
        )
        return created["inst"]

    monkeypatch.setattr(mod, "AzureBlobUploader", _ctor)

    uri = "azureblob://acct1/contA/tes-runs/r1/tools/echo_test/results.json"
    payload = b'{"ok": true}'

    mod.upload_to_result_uri(
        result_uri=uri,
        data=payload,
        content_type="application/json",
        azure_auth="connection_string",
        azure_connection_string="UseDevelopmentStorage=true",
    )

    inst = created["inst"]
    assert len(inst.calls) == 1
    c = inst.calls[0]
    assert c["account_name"] == "acct1"
    assert c["auth"] == "connection_string"
    assert c["connection_string"] == "UseDevelopmentStorage=true"
    assert c["container"] == "contA"
    assert c["blob_path"] == "tes-runs/r1/tools/echo_test/results.json"
    assert c["data"] == payload
    assert c["content_type"] == "application/json"


def test_upload_unsupported_scheme_raises():
    """Reject an unsupported RESULT_URI scheme before any uploader is constructed."""
    with pytest.raises(ValueError):
        mod.upload_to_result_uri(result_uri="ftp://bucket/key", data=b"x")


def test_upload_gcs_success():
    """GCS upload path calls blob.upload_from_string (covers upload_result.py line 161)."""
    import google.cloud.storage  # ensure importable

    mock_blob = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    with patch("google.cloud.storage.Client", return_value=mock_client):
        mod.upload_to_result_uri(
            result_uri="gs://mybucket/path/results.json",
            data=b'{"ok": true}',
        )

    mock_blob.upload_from_string.assert_called_once_with(
        b'{"ok": true}', content_type="application/json"
    )


def test_upload_gcs_empty_bucket_raises():
    """Redundant bucket check (line 149) is exercised by bypassing parse_result_uri."""
    from omni_tool_runtime.result_uri import ParsedResultURI

    # Patch parse_result_uri inside upload_result to skip its own validation,
    # then let urlparse("gs:///results.json") produce an empty netloc so line 149 fires.
    with patch(
        "omni_tool_runtime.upload_result.parse_result_uri",
        return_value=ParsedResultURI(scheme="gs", account_or_bucket="", container=None, path=""),
    ):
        with pytest.raises(ValueError, match="Invalid gs"):
            mod.upload_to_result_uri(result_uri="gs:///", data=b"x")
