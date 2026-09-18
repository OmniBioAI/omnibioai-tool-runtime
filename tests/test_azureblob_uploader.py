"""
Unit tests for omni_tool_runtime/uploaders/azureblob_uploader.py
Fully mocked — no azure SDK required.

Run:
    pytest tests/test_azureblob_uploader.py -v
    pytest tests/test_azureblob_uploader.py \
      --cov=omni_tool_runtime/uploaders/azureblob_uploader --cov-report=term-missing -v

Developer: Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out the azure SDK modules before importing the uploader so the module
# loads cleanly even without the real azure package installed.
# ---------------------------------------------------------------------------


def _install_azure_stubs():
    """Register fake azure/azure.storage/azure.storage.blob/azure.identity modules in sys.modules so the uploader imports cleanly without the real azure SDK."""
    azure = types.ModuleType("azure")
    azure_storage = types.ModuleType("azure.storage")
    azure_storage_blob = types.ModuleType("azure.storage.blob")
    azure_identity = types.ModuleType("azure.identity")

    azure_storage_blob.BlobServiceClient = MagicMock()
    azure_identity.DefaultAzureCredential = MagicMock()

    azure.storage = azure_storage
    azure_storage.blob = azure_storage_blob

    sys.modules.setdefault("azure", azure)
    sys.modules.setdefault("azure.storage", azure_storage)
    sys.modules.setdefault("azure.storage.blob", azure_storage_blob)
    sys.modules.setdefault("azure.identity", azure_identity)

    return azure_storage_blob, azure_identity


_azure_storage_blob_stub, _azure_identity_stub = _install_azure_stubs()

# Now safe to import
from omni_tool_runtime.uploaders.azureblob_uploader import AzureBlobUploader  # noqa: E402

MOD = "omni_tool_runtime.uploaders.azureblob_uploader"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_uploader(**kw) -> AzureBlobUploader:
    """Build an AzureBlobUploader with sensible defaults, overridable per test."""
    defaults = dict(account_name="myaccount", auth="managed_identity", connection_string=None)
    return AzureBlobUploader(**{**defaults, **kw})


def _mock_blob_service():
    """Return (mock_svc, mock_blob_client) wired together."""
    mock_bc = MagicMock()
    mock_svc = MagicMock()
    mock_svc.get_blob_client.return_value = mock_bc
    return mock_svc, mock_bc


# ---------------------------------------------------------------------------
# Dataclass construction
# ---------------------------------------------------------------------------


class TestAzureBlobUploaderConstruction:
    """The AzureBlobUploader dataclass stores account_name/auth/connection_string verbatim, defaulting to managed-identity auth."""
    def test_account_name_stored(self):
        """Store the given account_name unchanged."""
        assert _make_uploader(account_name="acct").account_name == "acct"

    def test_default_auth_is_managed_identity(self):
        """Default auth to managed_identity when not given."""
        assert AzureBlobUploader(account_name="acct").auth == "managed_identity"

    def test_explicit_auth_connection_string(self):
        """Store an explicitly given connection_string auth mode."""
        u = _make_uploader(auth="connection_string", connection_string="cs")
        assert u.auth == "connection_string"

    def test_connection_string_default_is_none(self):
        """Default connection_string to None when not given."""
        assert AzureBlobUploader(account_name="acct").connection_string is None

    def test_connection_string_stored(self):
        """Store the given connection_string unchanged."""
        cs = "DefaultEndpointsProtocol=https;..."
        assert _make_uploader(connection_string=cs).connection_string == cs


# ---------------------------------------------------------------------------
# _client — connection_string auth
# ---------------------------------------------------------------------------


class TestClientConnectionString:
    """_client() builds a BlobServiceClient via from_connection_string() and never touches DefaultAzureCredential."""

    def _make(self, connection_string="cs://fake"):
        """Build an uploader configured for connection_string auth."""
        return _make_uploader(auth="connection_string", connection_string=connection_string)

    def test_calls_from_connection_string(self):
        """_client() builds the BlobServiceClient via from_connection_string() using the stored connection string."""
        mock_bsc = MagicMock()
        _azure_storage_blob_stub.BlobServiceClient = mock_bsc
        uploader = self._make()
        uploader._client()
        mock_bsc.from_connection_string.assert_called_once_with("cs://fake")

    def test_returns_blob_service_client(self):
        """_client() returns the BlobServiceClient instance produced by from_connection_string()."""
        mock_bsc = MagicMock()
        sentinel = object()
        mock_bsc.from_connection_string.return_value = sentinel
        _azure_storage_blob_stub.BlobServiceClient = mock_bsc
        assert self._make()._client() is sentinel

    def test_missing_connection_string_raises(self):
        """Reject connection_string auth when no connection string is configured (None)."""
        uploader = _make_uploader(auth="connection_string", connection_string=None)
        with pytest.raises(RuntimeError, match="connection_string auth requires connection_string"):
            uploader._client()

    def test_empty_connection_string_raises(self):
        """Reject connection_string auth when the connection string is an empty string."""
        uploader = _make_uploader(auth="connection_string", connection_string="")
        with pytest.raises(RuntimeError, match="connection_string auth requires connection_string"):
            uploader._client()

    def test_does_not_use_default_azure_credential(self):
        """Never construct a DefaultAzureCredential when using connection_string auth."""
        mock_dac = MagicMock()
        _azure_identity_stub.DefaultAzureCredential = mock_dac
        _azure_storage_blob_stub.BlobServiceClient = MagicMock()
        self._make()._client()
        mock_dac.assert_not_called()


# ---------------------------------------------------------------------------
# _client — managed identity auth
# ---------------------------------------------------------------------------


class TestClientManagedIdentity:
    """_client() builds a BlobServiceClient authenticated via DefaultAzureCredential and never calls from_connection_string()."""

    def _make(self):
        """Build an uploader configured for managed_identity auth against a fixed account name."""
        return _make_uploader(auth="managed_identity", account_name="storageacct")

    def test_creates_default_azure_credential(self):
        """_client() constructs a DefaultAzureCredential with interactive browser login excluded."""
        mock_dac = MagicMock()
        mock_bsc = MagicMock()
        _azure_identity_stub.DefaultAzureCredential = mock_dac
        _azure_storage_blob_stub.BlobServiceClient = mock_bsc
        self._make()._client()
        mock_dac.assert_called_once_with(exclude_interactive_browser_credential=True)

    def test_builds_correct_account_url(self):
        """_client() builds the account_url as https://<account>.blob.core.windows.net."""
        mock_dac = MagicMock()
        mock_bsc = MagicMock()
        _azure_identity_stub.DefaultAzureCredential = mock_dac
        _azure_storage_blob_stub.BlobServiceClient = mock_bsc
        self._make()._client()
        call_kwargs = mock_bsc.call_args.kwargs
        assert call_kwargs["account_url"] == "https://storageacct.blob.core.windows.net"

    def test_credential_passed_to_blob_service_client(self):
        """_client() passes the constructed DefaultAzureCredential through to BlobServiceClient."""
        fake_cred = object()
        mock_dac = MagicMock(return_value=fake_cred)
        mock_bsc = MagicMock()
        _azure_identity_stub.DefaultAzureCredential = mock_dac
        _azure_storage_blob_stub.BlobServiceClient = mock_bsc
        self._make()._client()
        assert mock_bsc.call_args.kwargs["credential"] is fake_cred

    def test_does_not_call_from_connection_string(self):
        """Never call from_connection_string() when using managed_identity auth."""
        mock_dac = MagicMock()
        mock_bsc = MagicMock()
        _azure_identity_stub.DefaultAzureCredential = mock_dac
        _azure_storage_blob_stub.BlobServiceClient = mock_bsc
        self._make()._client()
        mock_bsc.from_connection_string.assert_not_called()

    def test_returns_blob_service_client_instance(self):
        """_client() returns the BlobServiceClient instance built for managed-identity auth."""
        sentinel = object()
        mock_dac = MagicMock()
        mock_bsc = MagicMock(return_value=sentinel)
        _azure_identity_stub.DefaultAzureCredential = mock_dac
        _azure_storage_blob_stub.BlobServiceClient = mock_bsc
        assert self._make()._client() is sentinel


# ---------------------------------------------------------------------------
# _client — missing azure packages raise RuntimeError
# ---------------------------------------------------------------------------


class TestClientMissingPackages:
    """_client() must fail with a clear, actionable error when the azure-storage-blob or azure-identity packages are not installed."""

    def test_missing_azure_storage_blob_raises(self):
        """Raise RuntimeError naming azure-storage-blob when that package is unavailable."""
        uploader = _make_uploader(auth="managed_identity")
        with (
            patch.dict(sys.modules, {"azure.storage.blob": None}),
            pytest.raises(RuntimeError, match="azure-storage-blob not installed"),
        ):
            uploader._client()

    def test_missing_azure_identity_raises(self):
        """Raise RuntimeError naming azure-identity when that package is unavailable under managed-identity auth."""
        uploader = _make_uploader(auth="managed_identity")
        # azure.storage.blob is present but azure.identity is missing
        real_bsc = _azure_storage_blob_stub.BlobServiceClient
        _azure_storage_blob_stub.BlobServiceClient = MagicMock()
        with (
            patch.dict(sys.modules, {"azure.identity": None}),
            pytest.raises(RuntimeError, match="azure-identity not installed"),
        ):
            uploader._client()
        _azure_storage_blob_stub.BlobServiceClient = real_bsc

    def test_missing_blob_error_message_mentions_install(self):
        """Point to the omnibioai-tool-runtime install extra in the missing-azure-storage-blob error message."""
        uploader = _make_uploader(auth="managed_identity")
        with (
            patch.dict(sys.modules, {"azure.storage.blob": None}),
            pytest.raises(RuntimeError, match="omnibioai-tool-runtime"),
        ):
            uploader._client()


# ---------------------------------------------------------------------------
# upload_bytes — argument forwarding
# ---------------------------------------------------------------------------


class TestUploadBytes:
    """upload_bytes() forwards container/blob_path/data/content_type to the Azure client, lowercasing the container name."""

    def _call(self, uploader=None, **kw):
        """Call upload_bytes with defaults, injecting a mocked BlobServiceClient via _client()."""
        uploader = uploader or _make_uploader()
        defaults = dict(
            container="MyContainer",
            blob_path="path/to/results.json",
            data=b'{"ok": true}',
            content_type="application/json",
        )
        mock_svc, mock_bc = _mock_blob_service()
        with patch.object(uploader, "_client", return_value=mock_svc):
            uploader.upload_bytes(**{**defaults, **kw})
        return mock_svc, mock_bc

    def test_get_blob_client_called(self):
        """Call get_blob_client exactly once per upload."""
        mock_svc, _ = self._call()
        mock_svc.get_blob_client.assert_called_once()

    def test_container_lowercased(self):
        """Lowercase a mixed-case container name before passing it to get_blob_client (Azure containers are case-sensitive and conventionally lowercase)."""
        mock_svc, _ = self._call(container="MyContainer")
        assert mock_svc.get_blob_client.call_args.kwargs["container"] == "mycontainer"

    def test_already_lowercase_container_unchanged(self):
        """Leave an already-lowercase container name unchanged."""
        mock_svc, _ = self._call(container="mycontainer")
        assert mock_svc.get_blob_client.call_args.kwargs["container"] == "mycontainer"

    def test_blob_path_passed_correctly(self):
        """Forward the given blob_path unchanged to get_blob_client."""
        mock_svc, _ = self._call(blob_path="output/run-1/results.json")
        assert mock_svc.get_blob_client.call_args.kwargs["blob"] == "output/run-1/results.json"

    def test_upload_blob_called(self):
        """Call upload_blob exactly once per upload."""
        _, mock_bc = self._call()
        mock_bc.upload_blob.assert_called_once()

    def test_data_passed_to_upload_blob(self):
        """Forward the given data bytes as upload_blob's first positional argument unmodified."""
        payload = b'{"result": 42}'
        _, mock_bc = self._call(data=payload)
        assert mock_bc.upload_blob.call_args.args[0] == payload

    def test_overwrite_is_true(self):
        """Always pass overwrite=True to upload_blob so re-runs replace prior results."""
        _, mock_bc = self._call()
        assert mock_bc.upload_blob.call_args.kwargs["overwrite"] is True

    def test_content_type_passed(self):
        """Forward the given content_type to upload_blob."""
        _, mock_bc = self._call(content_type="text/plain")
        assert mock_bc.upload_blob.call_args.kwargs["content_type"] == "text/plain"

    def test_default_content_type_json(self):
        """Forward application/json as content_type when that is the given content_type."""
        _, mock_bc = self._call(content_type="application/json")
        assert mock_bc.upload_blob.call_args.kwargs["content_type"] == "application/json"

    def test_client_called_once(self):
        """Call _client() exactly once per upload."""
        uploader = _make_uploader()
        mock_svc, _ = _mock_blob_service()
        with patch.object(uploader, "_client", return_value=mock_svc) as mock_client:
            uploader.upload_bytes(
                container="c",
                blob_path="b.json",
                data=b"x",
                content_type="application/json",
            )
        mock_client.assert_called_once()

    def test_returns_none(self):
        """upload_bytes returns None (the Azure call result is not surfaced to the caller)."""
        uploader = _make_uploader()
        mock_svc, _ = _mock_blob_service()
        with patch.object(uploader, "_client", return_value=mock_svc):
            result = uploader.upload_bytes(
                container="c",
                blob_path="b.json",
                data=b"x",
                content_type="application/json",
            )
        assert result is None

    def test_upload_blob_receives_bytes_not_string(self):
        """Pass the payload through to upload_blob as bytes, not a str."""
        payload = b"binary-content"
        _, mock_bc = self._call(data=payload)
        uploaded = mock_bc.upload_blob.call_args.args[0]
        assert isinstance(uploaded, bytes)

    def test_stdout_logged(self, capsys):
        """Log the container and blob path (structural, non-sensitive identifiers) to stdout on upload."""
        uploader = _make_uploader()
        mock_svc, _ = _mock_blob_service()
        with patch.object(uploader, "_client", return_value=mock_svc):
            uploader.upload_bytes(
                container="mycontainer",
                blob_path="path/result.json",
                data=b"x",
                content_type="application/json",
            )
        out = capsys.readouterr().out
        assert "mycontainer" in out
        assert "path/result.json" in out


# ---------------------------------------------------------------------------
# upload_bytes — end-to-end with connection_string auth
# ---------------------------------------------------------------------------


class TestUploadBytesEndToEndConnectionString:
    """Full upload_bytes() flow using connection_string auth, from client construction through the final upload_blob call."""

    def test_full_flow_connection_string(self):
        """Full upload_bytes flow using connection_string auth: builds the client via from_connection_string, uploads to the exact container/blob/body/content-type given."""
        conn = "DefaultEndpointsProtocol=https;AccountName=x;..."
        uploader = _make_uploader(
            auth="connection_string",
            connection_string=conn,
        )
        mock_svc, mock_bc = _mock_blob_service()
        mock_bsc = MagicMock()
        mock_bsc.from_connection_string.return_value = mock_svc

        _azure_storage_blob_stub.BlobServiceClient = mock_bsc
        uploader.upload_bytes(
            container="results",
            blob_path="run-1/results.json",
            data=b'{"ok":true}',
            content_type="application/json",
        )

        mock_bsc.from_connection_string.assert_called_once_with(conn)
        mock_svc.get_blob_client.assert_called_once_with(
            container="results", blob="run-1/results.json"
        )
        mock_bc.upload_blob.assert_called_once_with(
            b'{"ok":true}', overwrite=True, content_type="application/json"
        )


# ---------------------------------------------------------------------------
# upload_bytes — end-to-end with managed identity auth
# ---------------------------------------------------------------------------


class TestUploadBytesEndToEndManagedIdentity:
    """Full upload_bytes() flow using managed_identity auth, from client construction through the final upload_blob call."""

    def test_full_flow_managed_identity(self):
        """Full upload_bytes flow using managed_identity auth: builds the client via DefaultAzureCredential, lowercases the container, and uploads the exact blob/body/content-type given."""
        uploader = _make_uploader(auth="managed_identity", account_name="storageacct")
        mock_svc, mock_bc = _mock_blob_service()

        fake_cred = object()
        mock_dac = MagicMock(return_value=fake_cred)
        mock_bsc = MagicMock(return_value=mock_svc)

        _azure_identity_stub.DefaultAzureCredential = mock_dac
        _azure_storage_blob_stub.BlobServiceClient = mock_bsc

        uploader.upload_bytes(
            container="OUT",
            blob_path="run-2/results.json",
            data=b"payload",
            content_type="application/octet-stream",
        )

        mock_dac.assert_called_once_with(exclude_interactive_browser_credential=True)
        mock_bsc.assert_called_once_with(
            account_url="https://storageacct.blob.core.windows.net",
            credential=fake_cred,
        )
        # Container is lowercased
        mock_svc.get_blob_client.assert_called_once_with(container="out", blob="run-2/results.json")
        mock_bc.upload_blob.assert_called_once_with(
            b"payload", overwrite=True, content_type="application/octet-stream"
        )
