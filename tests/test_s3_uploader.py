"""
Unit tests for omni_tool_runtime/uploaders/s3_uploader.py
Fully mocked — no boto3 / AWS credentials required.

Run:
    pytest tests/test_s3_uploader.py -v
    pytest tests/test_s3_uploader.py \
      --cov=omni_tool_runtime/uploaders/s3_uploader --cov-report=term-missing -v

Developer: Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from omni_tool_runtime.uploaders.s3_uploader import S3Uploader

MOD = "omni_tool_runtime.uploaders.s3_uploader"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_boto3():
    """Return (mock_boto3, mock_session, mock_s3_client) wired together."""
    mock_s3 = MagicMock()
    mock_session = MagicMock()
    mock_session.client.return_value = mock_s3
    mock_boto3 = MagicMock()
    mock_boto3.Session.return_value = mock_session
    return mock_boto3, mock_session, mock_s3


def _call(uploader: S3Uploader, **kw):
    """Call upload_bytes with defaults, injecting a mocked boto3."""
    defaults = dict(
        bucket="my-bucket",
        key="path/to/results.json",
        data=b'{"ok": true}',
        content_type="application/json",
    )
    mock_boto3, mock_session, mock_s3 = _mock_boto3()
    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        uploader.upload_bytes(**{**defaults, **kw})
    return mock_boto3, mock_session, mock_s3


# ---------------------------------------------------------------------------
# Dataclass construction
# ---------------------------------------------------------------------------


class TestS3UploaderConstruction:
    """The S3Uploader dataclass stores an optional aws_profile without side effects."""
    def test_default_profile_is_none(self):
        """Default aws_profile to None when not given."""
        assert S3Uploader().aws_profile is None

    def test_explicit_profile_stored(self):
        """Store an explicitly given aws_profile."""
        assert S3Uploader(aws_profile="my-profile").aws_profile == "my-profile"

    def test_empty_string_profile_stored(self):
        # Empty string is falsy — treated as no profile in upload_bytes
        """Store an empty-string aws_profile as-is (its falsy handling happens later, in upload_bytes)."""
        assert S3Uploader(aws_profile="").aws_profile == ""


# ---------------------------------------------------------------------------
# Missing boto3
# ---------------------------------------------------------------------------


class TestMissingBoto3:
    """upload_bytes must fail with a clear, actionable error when boto3 is not installed."""
    def test_raises_runtime_error(self):
        """Raise RuntimeError when boto3 cannot be imported."""
        uploader = S3Uploader()
        with patch.dict(sys.modules, {"boto3": None}), pytest.raises(RuntimeError):
            uploader.upload_bytes(
                bucket="b", key="k.json", data=b"x", content_type="application/json"
            )

    def test_error_message_mentions_boto3(self):
        """Name boto3 in the missing-dependency error message."""
        uploader = S3Uploader()
        with (
            patch.dict(sys.modules, {"boto3": None}),
            pytest.raises(RuntimeError, match="boto3 not installed"),
        ):
            uploader.upload_bytes(
                bucket="b", key="k.json", data=b"x", content_type="application/json"
            )

    def test_error_message_mentions_install_extra(self):
        """Point to the omnibioai-tool-runtime install extra in the missing-dependency error message."""
        uploader = S3Uploader()
        with (
            patch.dict(sys.modules, {"boto3": None}),
            pytest.raises(RuntimeError, match="omnibioai-tool-runtime"),
        ):
            uploader.upload_bytes(
                bucket="b", key="k.json", data=b"x", content_type="application/json"
            )


# ---------------------------------------------------------------------------
# Session construction
# ---------------------------------------------------------------------------


class TestSessionConstruction:
    """upload_bytes must build a boto3 Session honoring the configured aws_profile."""
    def test_session_created(self):
        """Create exactly one boto3 Session per upload."""
        mock_boto3, mock_session, _ = _call(S3Uploader())
        mock_boto3.Session.assert_called_once()

    def test_no_profile_session_has_no_profile_kwarg(self):
        """Omit the profile_name kwarg from Session() when aws_profile is None."""
        mock_boto3, _, _ = _call(S3Uploader(aws_profile=None))
        assert "profile_name" not in mock_boto3.Session.call_args.kwargs

    def test_profile_passed_to_session(self):
        """Pass aws_profile through to Session() as profile_name."""
        mock_boto3, _, _ = _call(S3Uploader(aws_profile="staging"))
        assert mock_boto3.Session.call_args.kwargs["profile_name"] == "staging"

    def test_empty_string_profile_not_passed(self):
        # Empty string is falsy so should not be forwarded
        """Omit the profile_name kwarg from Session() when aws_profile is an empty (falsy) string."""
        mock_boto3, _, _ = _call(S3Uploader(aws_profile=""))
        assert "profile_name" not in mock_boto3.Session.call_args.kwargs

    def test_session_client_called_with_s3(self):
        """Request the 's3' client from the constructed Session."""
        _, mock_session, _ = _call(S3Uploader())
        mock_session.client.assert_called_once_with("s3")


# ---------------------------------------------------------------------------
# put_object forwarding
# ---------------------------------------------------------------------------


class TestPutObject:
    """upload_bytes must forward bucket/key/data/content_type to boto3's put_object unchanged."""
    def test_put_object_called(self):
        """Call put_object exactly once per upload."""
        _, _, mock_s3 = _call(S3Uploader())
        mock_s3.put_object.assert_called_once()

    def test_bucket_passed(self):
        """Forward the given bucket as put_object's Bucket kwarg."""
        _, _, mock_s3 = _call(S3Uploader(), bucket="target-bucket")
        assert mock_s3.put_object.call_args.kwargs["Bucket"] == "target-bucket"

    def test_key_passed(self):
        """Forward the given key as put_object's Key kwarg."""
        _, _, mock_s3 = _call(S3Uploader(), key="runs/run-1/results.json")
        assert mock_s3.put_object.call_args.kwargs["Key"] == "runs/run-1/results.json"

    def test_data_passed_as_body(self):
        """Forward the given data bytes as put_object's Body kwarg unmodified."""
        payload = b'{"result": 99}'
        _, _, mock_s3 = _call(S3Uploader(), data=payload)
        assert mock_s3.put_object.call_args.kwargs["Body"] == payload

    def test_content_type_passed(self):
        """Forward the given content_type as put_object's ContentType kwarg."""
        _, _, mock_s3 = _call(S3Uploader(), content_type="text/plain")
        assert mock_s3.put_object.call_args.kwargs["ContentType"] == "text/plain"

    def test_default_content_type_json(self):
        """Forward application/json as ContentType when that is the given content_type."""
        _, _, mock_s3 = _call(S3Uploader(), content_type="application/json")
        assert mock_s3.put_object.call_args.kwargs["ContentType"] == "application/json"

    def test_body_is_bytes(self):
        """Pass the Body kwarg through to put_object as bytes, not a str."""
        payload = b"binary-payload"
        _, _, mock_s3 = _call(S3Uploader(), data=payload)
        assert isinstance(mock_s3.put_object.call_args.kwargs["Body"], bytes)

    def test_returns_none(self):
        """upload_bytes returns None (the S3 call result is not surfaced to the caller)."""
        mock_boto3, mock_session, mock_s3 = _mock_boto3()
        uploader = S3Uploader()
        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            result = uploader.upload_bytes(
                bucket="b", key="k.json", data=b"x", content_type="application/json"
            )
        assert result is None

    def test_all_four_kwargs_present(self):
        """Always supply Bucket, Key, Body, and ContentType together to put_object."""
        _, _, mock_s3 = _call(S3Uploader())
        kw = mock_s3.put_object.call_args.kwargs
        for key in ("Bucket", "Key", "Body", "ContentType"):
            assert key in kw


# ---------------------------------------------------------------------------
# Full end-to-end flow
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """Full upload_bytes flow, from constructor through the mocked boto3 call chain, without a profile and with one."""
    def test_full_flow_no_profile(self):
        """A profile-less uploader creates a bare Session() and uploads the exact bucket/key/body/content-type given."""
        mock_boto3, mock_session, mock_s3 = _mock_boto3()
        uploader = S3Uploader(aws_profile=None)
        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            uploader.upload_bytes(
                bucket="prod-bucket",
                key="outputs/run-42/results.json",
                data=b'{"status":"done"}',
                content_type="application/json",
            )
        mock_boto3.Session.assert_called_once_with()
        mock_session.client.assert_called_once_with("s3")
        mock_s3.put_object.assert_called_once_with(
            Bucket="prod-bucket",
            Key="outputs/run-42/results.json",
            Body=b'{"status":"done"}',
            ContentType="application/json",
        )

    def test_full_flow_with_profile(self):
        """A profiled uploader creates Session(profile_name=...) and uploads the exact bucket/key/body/content-type given."""
        mock_boto3, mock_session, mock_s3 = _mock_boto3()
        uploader = S3Uploader(aws_profile="dev")
        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            uploader.upload_bytes(
                bucket="dev-bucket",
                key="run-1/results.json",
                data=b"payload",
                content_type="application/octet-stream",
            )
        mock_boto3.Session.assert_called_once_with(profile_name="dev")
        mock_session.client.assert_called_once_with("s3")
        mock_s3.put_object.assert_called_once_with(
            Bucket="dev-bucket",
            Key="run-1/results.json",
            Body=b"payload",
            ContentType="application/octet-stream",
        )
