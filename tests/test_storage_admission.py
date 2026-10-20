from __future__ import annotations

import pytest

from omni_tool_runtime.storage_admission import (
    AdmissionError,
    OutputAdmission,
    publish_managed_output,
)


class FakeLedger:
    def __init__(self):
        self.calls = []
        self.fail_reserve = False

    def reserve(self, **kwargs):
        self.calls.append(("reserve", kwargs))
        if self.fail_reserve:
            raise AdmissionError("quota denied")
        return OutputAdmission("alloc-1", kwargs["max_bytes"], kwargs["idempotency_key"])

    def start(self, **kwargs): self.calls.append(("start", kwargs))
    def commit(self, **kwargs): self.calls.append(("commit", kwargs))
    def release(self, **kwargs): self.calls.append(("release", kwargs))
    def delete_pending(self, **kwargs): self.calls.append(("delete_pending", kwargs))
    def confirmed_delete(self, **kwargs): self.calls.append(("confirmed_delete", kwargs))
    def status(self, **kwargs): return {"state": "UPLOADING"}
    def reconcile(self, **kwargs): return {"state": "UPLOADING"}


def test_managed_publication_reserves_starts_and_commits_actual_payload_bytes():
    ledger = FakeLedger()
    published = []
    allocation_id = publish_managed_output(
        admission=ledger, run_id="run-1", output_id="result-1",
        destination="s3://managed/run-1/results.json", backend="s3",
        content=b"actual", max_bytes=20,
        publish=lambda: published.append(True),
    )
    assert allocation_id == "alloc-1"
    assert published == [True]
    assert [call[0] for call in ledger.calls] == ["reserve", "start", "commit"]
    assert ledger.calls[-1][1]["actual_bytes"] == 6
    assert ledger.calls[0][1]["idempotency_key"] == "tes:run-1:result-1"


def test_quota_denial_prevents_any_storage_write():
    ledger = FakeLedger()
    ledger.fail_reserve = True
    published = []
    with pytest.raises(AdmissionError):
        publish_managed_output(
            admission=ledger, run_id="run-1", output_id="result-1",
            destination="s3://managed/run-1/results.json", backend="s3",
            content=b"actual", max_bytes=20,
            publish=lambda: published.append(True),
        )
    assert published == []
    assert [call[0] for call in ledger.calls] == ["reserve"]


def test_unknown_or_over_capacity_output_is_rejected_before_publication():
    ledger = FakeLedger()
    published = []
    with pytest.raises(AdmissionError, match="bounded reservation"):
        publish_managed_output(
            admission=ledger, run_id="run-1", output_id="result-1",
            destination="s3://managed/run-1/results.json", backend="s3",
            content=b"too large", max_bytes=2,
            publish=lambda: published.append(True),
        )
    assert not ledger.calls
    assert not published


def test_write_exception_leaves_hold_for_reconciliation_without_premature_release():
    ledger = FakeLedger()
    def ambiguous_write():
        raise TimeoutError("provider timed out after request")
    with pytest.raises(TimeoutError):
        publish_managed_output(
            admission=ledger, run_id="run-1", output_id="result-1",
            destination="s3://managed/run-1/results.json", backend="s3",
            content=b"actual", max_bytes=20, publish=ambiguous_write,
        )
    assert [call[0] for call in ledger.calls] == ["reserve", "start"]


def test_http_writer_client_allows_plain_http_only_for_test_loopback(monkeypatch):
    from omni_tool_runtime.storage_admission import LedgerHTTPClient

    with pytest.raises(AdmissionError):
        LedgerHTTPClient("http://example.invalid", "cap")
    with pytest.raises(AdmissionError):
        LedgerHTTPClient("http://127.0.0.1:8000", "cap")
    monkeypatch.setenv("TES_STORAGE_TEST_ALLOW_HTTP_LOOPBACK", "1")
    client = LedgerHTTPClient("http://127.0.0.1:8000", "cap")
    assert client.base_url == "http://127.0.0.1:8000"
