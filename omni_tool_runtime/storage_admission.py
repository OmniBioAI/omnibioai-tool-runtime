"""TES managed output admission client and publication lifecycle.

The runtime receives a narrow run-scoped credential from TES. The admission
service is the Storage Ledger boundary; this module deliberately contains no
quota counters or policy calculations.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AdmissionError(RuntimeError):
    """Admission denied or could not be established; publication must stop."""


class AdmissionUnknown(AdmissionError):
    """The remote transition may have succeeded; retain allocation for repair."""


@dataclass(frozen=True)
class OutputAdmission:
    allocation_id: str
    max_bytes: int
    idempotency_key: str
    state: str = "RESERVED"
    actual_bytes: int = 0


class LedgerAdmission(Protocol):
    def reserve(self, *, run_id: str, output_id: str, max_bytes: int,
                idempotency_key: str, destination: str, backend: str) -> OutputAdmission: ...
    def start(self, *, allocation_id: str, physical_id: str, idempotency_key: str) -> None: ...
    def commit(self, *, allocation_id: str, actual_bytes: int, idempotency_key: str) -> None: ...
    def release(self, *, allocation_id: str, confirmed_absent: bool, idempotency_key: str) -> None: ...
    def delete_pending(self, *, allocation_id: str, idempotency_key: str) -> None: ...
    def confirmed_delete(self, *, allocation_id: str, confirmed_absent: bool,
                         idempotency_key: str) -> None: ...
    def status(self, *, allocation_id: str) -> dict[str, Any]: ...
    def reconcile(self, *, allocation_id: str, idempotency_key: str) -> dict[str, Any]: ...


class LedgerHTTPClient:
    """Small stdlib HTTP client; no credentials are included in errors/logs."""

    def __init__(self, base_url: str, bearer: str, *, timeout: float = 5.0):
        if not base_url.startswith("https://") or not bearer:
            raise AdmissionError("managed output admission configuration is invalid")
        self.base_url = base_url.rstrip("/")
        self.bearer = bearer
        self.timeout = timeout

    @classmethod
    def from_environment(cls) -> "LedgerHTTPClient":
        return cls(os.environ.get("TES_STORAGE_LEDGER_URL", ""),
                   os.environ.get("TES_STORAGE_ADMISSION_TOKEN", ""))

    def _call(self, action: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}/api/storage/tes/{action}",
            data=json.dumps(body or {}).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.bearer}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except HTTPError as exc:
            if exc.code >= 500:
                raise AdmissionUnknown("Storage Ledger response is unavailable") from None
            raise AdmissionError("Storage Ledger denied managed output") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise AdmissionUnknown("Storage Ledger outcome is unknown") from None
        if not isinstance(payload, dict):
            raise AdmissionUnknown("Storage Ledger returned an invalid response")
        return payload

    def reserve(self, **values: Any) -> OutputAdmission:
        result = self._call("reserve", values)
        try:
            return OutputAdmission(str(result["allocation_id"]), int(result["max_bytes"]),
                                   str(result["idempotency_key"]),
                                   str(result.get("state", "RESERVED")),
                                   int(result.get("actual_bytes", 0)))
        except (KeyError, TypeError, ValueError):
            raise AdmissionUnknown("Storage Ledger returned an incomplete reservation") from None

    def start(self, **values: Any) -> None: self._call("start", values)
    def commit(self, **values: Any) -> None: self._call("commit", values)
    def release(self, **values: Any) -> None: self._call("release", values)
    def delete_pending(self, **values: Any) -> None: self._call("delete_pending", values)
    def confirmed_delete(self, **values: Any) -> None: self._call("confirmed_delete", values)
    def status(self, **values: Any) -> dict[str, Any]: return self._call("status", values)
    def reconcile(self, **values: Any) -> dict[str, Any]: return self._call("reconcile", values)


def publish_managed_output(*, admission: LedgerAdmission, run_id: str, output_id: str,
                           destination: str, backend: str, content: bytes,
                           max_bytes: int, publish) -> str:
    """Reserve before publication and commit measured payload bytes afterwards.

    On a write or acknowledgement error the allocation remains held; only a
    reconciler with proof of physical absence may release it.
    """
    if type(max_bytes) is not int or max_bytes <= 0 or len(content) > max_bytes:
        raise AdmissionError("managed output exceeds its bounded reservation")
    key = f"tes:{run_id}:{output_id}"
    allocation = admission.reserve(run_id=run_id, output_id=output_id,
        max_bytes=max_bytes, idempotency_key=key, destination=destination, backend=backend)
    if allocation.state == "COMMITTED":
        if allocation.actual_bytes != len(content):
            raise AdmissionError("idempotency key is already committed with different bytes")
        return allocation.allocation_id
    if allocation.state != "RESERVED":
        raise AdmissionUnknown("existing managed output requires reconciliation")
    if len(content) > allocation.max_bytes:
        raise AdmissionError("managed output exceeds the admitted reservation")
    admission.start(allocation_id=allocation.allocation_id, physical_id=destination,
                    idempotency_key=key)
    # A thrown storage error has an uncertain physical outcome. Keep the hold.
    publish()
    admission.commit(allocation_id=allocation.allocation_id, actual_bytes=len(content),
                     idempotency_key=key)
    return allocation.allocation_id
