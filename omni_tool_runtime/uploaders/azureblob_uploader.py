"""
OmniBioAI omni_tool_runtime.uploaders.azureblob_uploader.

Purpose:
    Defines AzureBlobUploader with upload_bytes methods for omni_tool_runtime.uploaders.azureblob_uploader.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AzureBlobUploader:
    account_name: str
    auth: str = "managed_identity"  # managed_identity | connection_string
    connection_string: str | None = None

    def _client(self):
        has_cs = bool(self.connection_string)
        print(
            f"[azureblob] auth={self.auth} account={self.account_name} has_conn_str={has_cs}",
            flush=True,
        )
        try:
            from azure.storage.blob import BlobServiceClient
        except Exception as e:
            raise RuntimeError(
                f"azure-storage-blob not installed (install omnibioai-tool-runtime[azure]): {e}"
            )

        if self.auth == "connection_string":
            if not self.connection_string:
                raise RuntimeError(
                    "AzureBlobUploader: connection_string auth requires connection_string"
                )
            return BlobServiceClient.from_connection_string(self.connection_string)

        # managed identity / az login / workload identity
        try:
            from azure.identity import DefaultAzureCredential
        except Exception as e:
            raise RuntimeError(
                f"azure-identity not installed (install omnibioai-tool-runtime[azure]): {e}"
            )

        cred = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        url = f"https://{self.account_name}.blob.core.windows.net"
        return BlobServiceClient(account_url=url, credential=cred)

    def upload_bytes(
        self, *, container: str, blob_path: str, data: bytes, content_type: str
    ) -> None:
        # Normalize container name before using it
        container = container.lower()
        print(f"[azureblob] upload container={container} blob={blob_path}", flush=True)

        svc = self._client()
        bc = svc.get_blob_client(container=container, blob=blob_path)
        # overwrite is fine for deterministic runs
        bc.upload_blob(data, overwrite=True, content_type=content_type)
