"""
Unit tests for omni_tool_runtime/upload_result.py — fully mocked, no cloud calls.

Run:
    pytest tests/test_upload_result.py -v
    pytest tests/test_upload_result.py \
      --cov=omni_tool_runtime/upload_result --cov-report=term-missing -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from omni_tool_runtime.upload_result import (
    _normalize_result_uri,
    _parse_azureblob,
    _parse_s3,
    upload_to_result_uri,
)

MOD = "omni_tool_runtime.upload_result"


# ---------------------------------------------------------------------------
# _normalize_result_uri
# ---------------------------------------------------------------------------


class TestNormalizeResultUri:
    def test_already_ends_in_json_unchanged(self):
        assert _normalize_result_uri("s3://bucket/results.json") == "s3://bucket/results.json"

    def test_trailing_slash_replaced_with_results_json(self):
        assert _normalize_result_uri("s3://bucket/prefix/") == "s3://bucket/prefix/results.json"

    def test_prefix_without_trailing_slash_appended(self):
        assert _normalize_result_uri("s3://bucket/prefix") == "s3://bucket/prefix/results.json"

    def test_multiple_trailing_slashes_normalized(self):
        result = _normalize_result_uri("s3://bucket/prefix///")
        assert result.endswith("/results.json")
        # Only check the path portion — the scheme "s3://" legitimately contains //
        path_part = result.split("://", 1)[1]
        assert "//" not in path_part

    def test_uppercase_json_extension_unchanged(self):
        # .JSON suffix counts as ending with .json (case-insensitive check)
        assert _normalize_result_uri("s3://bucket/out.JSON") == "s3://bucket/out.JSON"

    def test_other_json_extension_kept(self):
        assert (
            _normalize_result_uri("azureblob://acct/cont/blob.json")
            == "azureblob://acct/cont/blob.json"
        )

    def test_empty_string_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="RESULT_URI not set"):
            _normalize_result_uri("")

    def test_whitespace_only_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="RESULT_URI not set"):
            _normalize_result_uri("   ")

    def test_none_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="RESULT_URI not set"):
            _normalize_result_uri(None)

    def test_strips_leading_whitespace(self):
        result = _normalize_result_uri("  s3://b/p")
        assert result == "s3://b/p/results.json"


# ---------------------------------------------------------------------------
# _parse_s3
# ---------------------------------------------------------------------------


class TestParseS3:
    def test_returns_bucket_and_key(self):
        bucket, key = _parse_s3("s3://my-bucket/path/to/results.json")
        assert bucket == "my-bucket"
        assert key == "path/to/results.json"

    def test_simple_key(self):
        bucket, key = _parse_s3("s3://bucket/results.json")
        assert bucket == "bucket" and key == "results.json"

    def test_deep_key_path(self):
        _, key = _parse_s3("s3://bucket/a/b/c/results.json")
        assert key == "a/b/c/results.json"

    def test_wrong_scheme_raises(self):
        with pytest.raises(ValueError, match="Not an s3 URI"):
            _parse_s3("azureblob://acct/cont/blob.json")

    def test_missing_bucket_raises(self):
        with pytest.raises(ValueError, match="Invalid s3 URI"):
            _parse_s3("s3:///key/results.json")

    def test_missing_key_raises(self):
        with pytest.raises(ValueError, match="Invalid s3 URI"):
            _parse_s3("s3://bucket/")

    def test_http_scheme_raises(self):
        with pytest.raises(ValueError, match="Not an s3 URI"):
            _parse_s3("https://bucket.s3.amazonaws.com/key")

    def test_leading_slash_stripped_from_key(self):
        _, key = _parse_s3("s3://bucket/results.json")
        assert not key.startswith("/")


# ---------------------------------------------------------------------------
# _parse_azureblob
# ---------------------------------------------------------------------------


class TestParseAzureblob:
    def test_returns_account_container_blob(self):
        account, container, blob_path = _parse_azureblob(
            "azureblob://myaccount/mycontainer/path/to/results.json"
        )
        assert account == "myaccount"
        assert container == "mycontainer"
        assert blob_path == "path/to/results.json"

    def test_simple_blob_path(self):
        _, _, blob_path = _parse_azureblob("azureblob://acct/cont/results.json")
        assert blob_path == "results.json"

    def test_deep_blob_path(self):
        _, _, blob_path = _parse_azureblob("azureblob://acct/cont/a/b/c/results.json")
        assert blob_path == "a/b/c/results.json"

    def test_wrong_scheme_raises(self):
        with pytest.raises(ValueError, match="Not an azureblob URI"):
            _parse_azureblob("s3://bucket/key")

    def test_missing_container_raises(self):
        with pytest.raises(ValueError, match="Invalid azureblob URI"):
            _parse_azureblob("azureblob://acct/results.json")

    def test_empty_account_raises(self):
        with pytest.raises(ValueError):
            _parse_azureblob("azureblob:///container/blob.json")

    def test_leading_slash_stripped_from_path(self):
        _, _, blob_path = _parse_azureblob("azureblob://acct/cont/results.json")
        assert not blob_path.startswith("/")

    def test_container_extracted_correctly(self):
        _, container, _ = _parse_azureblob("azureblob://acct/my-container/blob.json")
        assert container == "my-container"


# ---------------------------------------------------------------------------
# upload_to_result_uri — argument validation
# ---------------------------------------------------------------------------


class TestUploadArgValidation:
    def test_no_content_or_data_raises_type_error(self):
        with pytest.raises(TypeError, match="content="):
            upload_to_result_uri(result_uri="s3://b/k.json")

    def test_content_none_and_data_none_raises(self):
        with pytest.raises(TypeError):
            upload_to_result_uri(result_uri="s3://b/k.json", content=None, data=None)

    def test_empty_result_uri_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="RESULT_URI not set"):
            upload_to_result_uri(result_uri="", content=b"x")

    def test_unsupported_scheme_raises_value_error(self):
        with patch(f"{MOD}.parse_result_uri") as mock_parse:
            mock_parse.return_value = MagicMock(scheme="gcs")
            with pytest.raises(ValueError, match="Unsupported RESULT_URI scheme"):
                upload_to_result_uri(result_uri="gcs://bucket/key.json", content=b"x")

    def test_content_preferred_over_data(self):
        mock_uploader = MagicMock()
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch(f"{MOD}.S3Uploader", return_value=mock_uploader),
        ):
            mock_parse.return_value = MagicMock(scheme="s3")
            upload_to_result_uri(
                result_uri="s3://bucket/results.json",
                content=b"preferred",
                data=b"legacy",
            )
        mock_uploader.upload_bytes.assert_called_once()
        assert mock_uploader.upload_bytes.call_args.kwargs["data"] == b"preferred"

    def test_data_used_when_content_is_none(self):
        mock_uploader = MagicMock()
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch(f"{MOD}.S3Uploader", return_value=mock_uploader),
        ):
            mock_parse.return_value = MagicMock(scheme="s3")
            upload_to_result_uri(
                result_uri="s3://bucket/results.json",
                data=b"legacy-payload",
            )
        assert mock_uploader.upload_bytes.call_args.kwargs["data"] == b"legacy-payload"


# ---------------------------------------------------------------------------
# upload_to_result_uri — S3 path
# ---------------------------------------------------------------------------


class TestUploadS3:
    def _call(self, uri="s3://my-bucket/results.json", content=b"payload", **kw):
        mock_uploader = MagicMock()
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch(f"{MOD}.S3Uploader", return_value=mock_uploader) as mock_cls,
        ):
            mock_parse.return_value = MagicMock(scheme="s3")
            upload_to_result_uri(result_uri=uri, content=content, **kw)
        return mock_cls, mock_uploader

    def test_s3_uploader_instantiated(self):
        mock_cls, _ = self._call()
        mock_cls.assert_called_once()

    def test_upload_bytes_called(self):
        _, mock_uploader = self._call()
        mock_uploader.upload_bytes.assert_called_once()

    def test_bucket_passed_correctly(self):
        _, mock_uploader = self._call(uri="s3://target-bucket/results.json")
        assert mock_uploader.upload_bytes.call_args.kwargs["bucket"] == "target-bucket"

    def test_key_passed_correctly(self):
        _, mock_uploader = self._call(uri="s3://bucket/path/to/results.json")
        assert mock_uploader.upload_bytes.call_args.kwargs["key"] == "path/to/results.json"

    def test_payload_passed_correctly(self):
        _, mock_uploader = self._call(content=b'{"ok": true}')
        assert mock_uploader.upload_bytes.call_args.kwargs["data"] == b'{"ok": true}'

    def test_default_content_type_is_json(self):
        _, mock_uploader = self._call()
        assert mock_uploader.upload_bytes.call_args.kwargs["content_type"] == "application/json"

    def test_custom_content_type_forwarded(self):
        _, mock_uploader = self._call(content_type="text/plain")
        assert mock_uploader.upload_bytes.call_args.kwargs["content_type"] == "text/plain"

    def test_aws_profile_passed_to_uploader(self):
        mock_cls, _ = self._call(aws_profile="my-profile")
        assert mock_cls.call_args.kwargs["aws_profile"] == "my-profile"

    def test_aws_profile_none_when_not_set(self):
        with patch.dict("os.environ", {}, clear=True):
            mock_cls, _ = self._call()
        assert mock_cls.call_args.kwargs["aws_profile"] is None

    def test_aws_profile_from_env_when_not_passed(self):
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch(f"{MOD}.S3Uploader") as mock_cls,
            patch.dict("os.environ", {"AWS_PROFILE": "env-profile"}, clear=True),
        ):
            mock_parse.return_value = MagicMock(scheme="s3")
            mock_cls.return_value = MagicMock()
            upload_to_result_uri(result_uri="s3://bucket/results.json", content=b"x")
        assert mock_cls.call_args.kwargs["aws_profile"] == "env-profile"

    def test_explicit_aws_profile_overrides_env(self):
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch(f"{MOD}.S3Uploader") as mock_cls,
            patch.dict("os.environ", {"AWS_PROFILE": "env-profile"}, clear=True),
        ):
            mock_parse.return_value = MagicMock(scheme="s3")
            mock_cls.return_value = MagicMock()
            upload_to_result_uri(
                result_uri="s3://bucket/results.json",
                content=b"x",
                aws_profile="explicit-profile",
            )
        assert mock_cls.call_args.kwargs["aws_profile"] == "explicit-profile"

    def test_prefix_uri_normalized_to_results_json(self):
        _, mock_uploader = self._call(uri="s3://bucket/run-outputs")
        assert mock_uploader.upload_bytes.call_args.kwargs["key"].endswith("results.json")

    def test_azure_uploader_not_called_for_s3(self):
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch(f"{MOD}.S3Uploader", return_value=MagicMock()),
            patch(f"{MOD}.AzureBlobUploader") as mock_azure,
        ):
            mock_parse.return_value = MagicMock(scheme="s3")
            upload_to_result_uri(result_uri="s3://bucket/results.json", content=b"x")
        mock_azure.assert_not_called()


# ---------------------------------------------------------------------------
# upload_to_result_uri — Azure Blob path
# ---------------------------------------------------------------------------


class TestUploadAzureBlob:
    _URI = "azureblob://myaccount/mycontainer/path/results.json"

    def _call(self, uri=None, content=b"payload", **kw):
        uri = uri or self._URI
        mock_uploader = MagicMock()
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch(f"{MOD}.AzureBlobUploader", return_value=mock_uploader) as mock_cls,
            patch.dict("os.environ", {}, clear=True),
        ):
            mock_parse.return_value = MagicMock(scheme="azureblob")
            upload_to_result_uri(result_uri=uri, content=content, **kw)
        return mock_cls, mock_uploader

    def test_azure_uploader_instantiated(self):
        mock_cls, _ = self._call()
        mock_cls.assert_called_once()

    def test_upload_bytes_called(self):
        _, mock_uploader = self._call()
        mock_uploader.upload_bytes.assert_called_once()

    def test_container_passed_correctly(self):
        _, mock_uploader = self._call()
        assert mock_uploader.upload_bytes.call_args.kwargs["container"] == "mycontainer"

    def test_blob_path_passed_correctly(self):
        _, mock_uploader = self._call()
        assert mock_uploader.upload_bytes.call_args.kwargs["blob_path"] == "path/results.json"

    def test_payload_passed_correctly(self):
        _, mock_uploader = self._call(content=b'{"result": 1}')
        assert mock_uploader.upload_bytes.call_args.kwargs["data"] == b'{"result": 1}'

    def test_default_content_type_is_json(self):
        _, mock_uploader = self._call()
        assert mock_uploader.upload_bytes.call_args.kwargs["content_type"] == "application/json"

    def test_custom_content_type_forwarded(self):
        _, mock_uploader = self._call(content_type="application/octet-stream")
        assert (
            mock_uploader.upload_bytes.call_args.kwargs["content_type"]
            == "application/octet-stream"
        )

    def test_account_name_passed_to_uploader(self):
        mock_cls, _ = self._call()
        assert mock_cls.call_args.kwargs["account_name"] == "myaccount"

    def test_default_auth_is_managed_identity(self):
        mock_cls, _ = self._call()
        assert mock_cls.call_args.kwargs["auth"] == "managed_identity"

    def test_explicit_auth_connection_string_passed(self):
        mock_cls, _ = self._call(
            azure_auth="connection_string",
            azure_connection_string="DefaultEndpointsProtocol=https;...",
        )
        assert mock_cls.call_args.kwargs["auth"] == "connection_string"

    def test_connection_string_passed_to_uploader(self):
        conn = "DefaultEndpointsProtocol=https;AccountName=x;..."
        mock_cls, _ = self._call(
            azure_auth="connection_string",
            azure_connection_string=conn,
        )
        assert mock_cls.call_args.kwargs["connection_string"] == conn

    def test_env_connection_string_used_when_not_passed(self):
        conn = "DefaultEndpointsProtocol=https;AccountName=env;..."
        mock_uploader = MagicMock()
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch(f"{MOD}.AzureBlobUploader", return_value=mock_uploader) as mock_cls,
            patch.dict("os.environ", {"AZURE_STORAGE_CONNECTION_STRING": conn}, clear=True),
        ):
            mock_parse.return_value = MagicMock(scheme="azureblob")
            upload_to_result_uri(result_uri=self._URI, content=b"x")
        assert mock_cls.call_args.kwargs["connection_string"] == conn

    def test_env_connection_string_upgrades_auth_to_connection_string(self):
        """When AZURE_STORAGE_CONNECTION_STRING is set, auth should flip to connection_string."""
        conn = "DefaultEndpointsProtocol=https;AccountName=env;..."
        mock_uploader = MagicMock()
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch(f"{MOD}.AzureBlobUploader", return_value=mock_uploader) as mock_cls,
            patch.dict("os.environ", {"AZURE_STORAGE_CONNECTION_STRING": conn}, clear=True),
        ):
            mock_parse.return_value = MagicMock(scheme="azureblob")
            upload_to_result_uri(result_uri=self._URI, content=b"x")
        assert mock_cls.call_args.kwargs["auth"] == "connection_string"

    def test_env_azure_auth_overrides_default(self):
        mock_uploader = MagicMock()
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch(f"{MOD}.AzureBlobUploader", return_value=mock_uploader) as mock_cls,
            patch.dict("os.environ", {"AZURE_AUTH": "connection_string"}, clear=True),
        ):
            mock_parse.return_value = MagicMock(scheme="azureblob")
            upload_to_result_uri(result_uri=self._URI, content=b"x")
        assert mock_cls.call_args.kwargs["auth"] == "connection_string"

    def test_s3_uploader_not_called_for_azure(self):
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch(f"{MOD}.AzureBlobUploader", return_value=MagicMock()),
            patch(f"{MOD}.S3Uploader") as mock_s3,
            patch.dict("os.environ", {}, clear=True),
        ):
            mock_parse.return_value = MagicMock(scheme="azureblob")
            upload_to_result_uri(result_uri=self._URI, content=b"x")
        mock_s3.assert_not_called()

    def test_prefix_uri_normalized(self):
        _, mock_uploader = self._call(uri="azureblob://myaccount/mycontainer/run-outputs")
        assert mock_uploader.upload_bytes.call_args.kwargs["blob_path"].endswith("results.json")

    def test_returns_none(self):
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch(f"{MOD}.AzureBlobUploader", return_value=MagicMock()),
            patch.dict("os.environ", {}, clear=True),
        ):
            mock_parse.return_value = MagicMock(scheme="azureblob")
            rv = upload_to_result_uri(result_uri=self._URI, content=b"x")
        assert rv is None


# ---------------------------------------------------------------------------
# upload_to_result_uri — GCS path (lines 144-163)
# ---------------------------------------------------------------------------


class TestUploadGCS:
    _URI = "gs://my-bucket/path/results.json"

    def _make_gcs_storage_mock(self):
        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_storage = MagicMock()
        mock_storage.Client.return_value = mock_client
        return mock_storage, mock_blob

    def _call(self, uri=None, content=b"payload", **kw):
        uri = uri or self._URI
        mock_storage, mock_blob = self._make_gcs_storage_mock()
        mock_gcloud = MagicMock(storage=mock_storage)
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch.dict("sys.modules", {
                "google.cloud": mock_gcloud,
                "google.cloud.storage": mock_storage,
            }),
        ):
            mock_parse.return_value = MagicMock(scheme="gs")
            upload_to_result_uri(result_uri=uri, content=content, **kw)
        return mock_storage, mock_blob

    def test_gcs_upload_called(self):
        _, mock_blob = self._call()
        mock_blob.upload_from_string.assert_called_once()

    def test_gcs_upload_content_passed(self):
        _, mock_blob = self._call(content=b"hello-gcs")
        args, _ = mock_blob.upload_from_string.call_args
        assert args[0] == b"hello-gcs"

    def test_gcs_upload_content_type_is_json(self):
        _, mock_blob = self._call()
        _, kwargs = mock_blob.upload_from_string.call_args
        assert kwargs.get("content_type") == "application/json"

    def test_gcs_upload_uses_correct_bucket(self):
        mock_storage, _ = self._call(uri="gs://target-bucket/results.json")
        mock_storage.Client.return_value.bucket.assert_called_with("target-bucket")

    def test_gcs_upload_uses_correct_blob_path(self):
        mock_storage, _ = self._call(uri="gs://bucket/path/to/results.json")
        mock_storage.Client.return_value.bucket.return_value.blob.assert_called_with(
            "path/to/results.json"
        )

    def test_gcs_missing_package_raises_runtime_error(self):
        """Covers lines 152-153: ImportError when google-cloud-storage is not installed."""
        mock_google_cloud = MagicMock(spec=[])
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch.dict("sys.modules", {
                "google.cloud": mock_google_cloud,
                "google.cloud.storage": None,
            }),
        ):
            mock_parse.return_value = MagicMock(scheme="gs")
            with pytest.raises(RuntimeError, match="google-cloud-storage not installed"):
                upload_to_result_uri(result_uri=self._URI, content=b"x")

    def test_gcs_invalid_uri_empty_bucket_raises(self):
        mock_storage, _ = self._make_gcs_storage_mock()
        mock_gcloud = MagicMock(storage=mock_storage)
        with (
            patch(f"{MOD}.parse_result_uri") as mock_parse,
            patch.dict("sys.modules", {
                "google.cloud": mock_gcloud,
                "google.cloud.storage": mock_storage,
            }),
        ):
            mock_parse.return_value = MagicMock(scheme="gs")
            with pytest.raises(ValueError, match="Invalid gs://"):
                upload_to_result_uri(result_uri="gs:///no-bucket", content=b"x")
