"""
PHI P1-4 — sentinel-value leakage tests.

These tests drive representative execution paths of the runners flagged
in the PHI-safe-logging audit (generic_sif_runner, echo_test) with
sentinel "sensitive" values standing in for patient/sample identifiers
and secrets, then assert those sentinel values never appear in anything
written to stdout/stderr (runtime operational logs).

They do NOT assert that the *uploaded* result (RESULT_URI content) is
redacted — that channel is the tool's intended, access-controlled output
and is expected to carry the real value. Only the log stream must be
PHI-safe.

Developer: Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from tools.echo_test.run import main as echo_main
from tools.generic_sif_runner.run import main as sif_main

SENTINEL_PATIENT = "PATIENT_TEST_987654"
SENTINEL_SECRET = "SECRET_TOKEN_TEST_ABC"


def _sif_tool_def(tmp_path, command=None, outputs=None):
    """Build a minimal tool-definition dict pointing at a fake SIF file for sif_main()."""
    sif = tmp_path / "tool.sif"
    sif.write_bytes(b"fake")
    return {
        "slurm": {
            "image": str(sif),
            "command": command or ["echo", "{sample_id}"],
            "outputs": outputs or [],
        }
    }


def _sif_env(tmp_path, td, inputs, resources_json="{}", result_uri=""):
    """Build the environment mapping sif_main() reads its TOOL_ID/INPUTS_JSON/etc. from."""
    return {
        "TOOL_ID": "tool-1",
        "RUN_ID": "run-1",
        "RESULT_URI": result_uri,
        "INPUTS_JSON": json.dumps(inputs),
        "RESOURCES_JSON": resources_json,
        "SIF_CACHE_DIR": str(tmp_path / "cache"),
        "WORK_DIR": str(tmp_path),
        "TOOL_DEF_JSON": json.dumps(td),
    }


class TestGenericSifRunnerSentinelLeakage:
    """Sentinel values must never reach stdout/stderr across execution paths."""

    def test_normal_execution_no_leak(self, tmp_path, capsys):
        """A successful run must not print the sentinel sample id or secret token to stdout/stderr."""
        td = _sif_tool_def(tmp_path, command=["echo", "{sample_id}", "{token}"])
        inputs = {"sample_id": SENTINEL_PATIENT, "token": SENTINEL_SECRET}
        env = _sif_env(tmp_path, td, inputs)
        mock_proc = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch.dict("os.environ", env, clear=True):
            with patch("subprocess.run", return_value=mock_proc):
                rc = sif_main()
        assert rc == 0
        captured = capsys.readouterr()
        assert SENTINEL_PATIENT not in captured.out
        assert SENTINEL_SECRET not in captured.out
        assert SENTINEL_PATIENT not in captured.err
        assert SENTINEL_SECRET not in captured.err

    def test_failed_execution_no_leak(self, tmp_path, capsys):
        """Tool exits non-zero; the resolved command must still not appear in logs."""
        td = _sif_tool_def(tmp_path, command=["some_tool", "--sample", "{sample_id}"])
        inputs = {"sample_id": SENTINEL_PATIENT}
        env = _sif_env(tmp_path, td, inputs)
        mock_proc = MagicMock(returncode=1, stdout="", stderr="tool failed")
        with patch.dict("os.environ", env, clear=True):
            with patch("subprocess.run", return_value=mock_proc):
                rc = sif_main()
        assert rc == 1
        captured = capsys.readouterr()
        assert SENTINEL_PATIENT not in captured.out
        assert SENTINEL_PATIENT not in captured.err

    def test_malformed_input_no_leak(self, capsys):
        """Malformed INPUTS_JSON must not echo the offending raw text (may embed a sentinel)."""
        env = {
            "TOOL_ID": "tool-1",
            "RUN_ID": "run-1",
            "RESULT_URI": "",
            "INPUTS_JSON": f'{{"sample_id": "{SENTINEL_PATIENT}", BAD_JSON',
            "RESOURCES_JSON": "{}",
        }
        with patch.dict("os.environ", env, clear=True):
            rc = sif_main()
        assert rc == 2
        captured = capsys.readouterr()
        assert SENTINEL_PATIENT not in captured.out
        assert SENTINEL_PATIENT not in captured.err

    def test_subprocess_failure_s3_download_no_leak(self, tmp_path, capsys):
        """A failed S3 input download must not print the sentinel-bearing S3 URI."""
        td = _sif_tool_def(tmp_path, command=["echo", "{sample_file}"])
        sentinel_uri = f"s3://bucket/{SENTINEL_PATIENT}/reads.fastq"
        inputs = {"sample_file": sentinel_uri}
        env = _sif_env(tmp_path, td, inputs)

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value.download_file.side_effect = Exception(
            f"NoSuchKey: {sentinel_uri}"
        )
        mock_proc = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch.dict("os.environ", env, clear=True):
            with patch.dict("sys.modules", {"boto3": mock_boto3}):
                with patch("subprocess.run", return_value=mock_proc):
                    rc = sif_main()
        assert rc == 0  # download failure falls back, run continues
        captured = capsys.readouterr()
        assert SENTINEL_PATIENT not in captured.out
        assert SENTINEL_PATIENT not in captured.err
        assert sentinel_uri not in captured.out

    def test_docker_direct_exec_command_no_leak(self, tmp_path, capsys):
        """Direct-exec (Docker fallback) path must not print the resolved argv."""
        td = {
            "slurm": {
                "image": "/nonexistent/tool.sif",
                "command": ["tool", "--secret", "{token}", "--sample", "{sample_id}"],
                "outputs": [],
                "docker_image": "my-image:latest",
            }
        }
        inputs = {"token": SENTINEL_SECRET, "sample_id": SENTINEL_PATIENT}
        env = _sif_env(tmp_path, td, inputs)
        mock_proc = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch.dict("os.environ", env, clear=True):
            with patch("subprocess.run", return_value=mock_proc):
                rc = sif_main()
        assert rc == 0
        captured = capsys.readouterr()
        assert SENTINEL_SECRET not in captured.out
        assert SENTINEL_PATIENT not in captured.out

    def test_useful_structural_logging_remains(self, tmp_path, capsys):
        """Redaction must not eliminate operationally useful signal."""
        td = _sif_tool_def(tmp_path, command=["echo", "{sample_id}"])
        inputs = {"sample_id": SENTINEL_PATIENT}
        env = _sif_env(tmp_path, td, inputs)
        mock_proc = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch.dict("os.environ", env, clear=True):
            with patch("subprocess.run", return_value=mock_proc):
                rc = sif_main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "tool-1" in out          # tool_id
        assert "run-1" in out           # run_id
        assert "downloading input 'sample_id'" not in out  # not a remote URI, no download log
        assert '"exit_code": 0' in out


class TestEchoTestSentinelLeakage:
    """Sentinel values must never reach stdout/stderr across echo_test execution paths."""

    def test_normal_execution_no_leak(self, capsys):
        """A successful echo_test run must not print the sentinel input value to stdout."""
        env = {
            "TOOL_ID": "echo-tool",
            "RUN_ID": "run-1",
            "RESULT_URI": "",
            "INPUTS_JSON": json.dumps({"text": SENTINEL_PATIENT}),
        }
        with patch.dict("os.environ", env, clear=True):
            rc = echo_main()
        assert rc == 0
        captured = capsys.readouterr()
        assert SENTINEL_PATIENT not in captured.out

    def test_cloud_mode_no_leak_even_though_uploaded(self, capsys):
        """The sentinel is legitimately uploaded (result channel) but must not be logged."""
        env = {
            "TOOL_ID": "echo-tool",
            "RUN_ID": "run-1",
            "RESULT_URI": "s3://bucket/key",
            "INPUTS_JSON": json.dumps({"text": SENTINEL_SECRET}),
        }
        with patch.dict("os.environ", env, clear=True):
            with patch("tools.echo_test.run.upload_to_result_uri") as mock_upload:
                rc = echo_main()
        assert rc == 0
        captured = capsys.readouterr()
        assert SENTINEL_SECRET not in captured.out
        _, kwargs = mock_upload.call_args
        assert SENTINEL_SECRET in kwargs["content"].decode("utf-8")

    def test_missing_text_error_no_leak(self, capsys):
        """The error path must not echo the raw inputs dict (may contain sentinels)."""
        env = {
            "TOOL_ID": "echo-tool",
            "RUN_ID": "run-1",
            "RESULT_URI": "",
            "INPUTS_JSON": json.dumps({"other_field": SENTINEL_PATIENT}),
        }
        with patch.dict("os.environ", env, clear=True):
            rc = echo_main()
        assert rc == 0
        captured = capsys.readouterr()
        assert SENTINEL_PATIENT not in captured.out

    def test_malformed_input_no_leak(self, capsys):
        """Malformed INPUTS_JSON must not echo the offending raw text, which may embed the sentinel value."""
        env = {
            "TOOL_ID": "echo-tool",
            "RUN_ID": "run-1",
            "RESULT_URI": "",
            "INPUTS_JSON": f'{{"text": "{SENTINEL_PATIENT}", BAD',
        }
        with patch.dict("os.environ", env, clear=True):
            rc = echo_main()
        assert rc == 2
        captured = capsys.readouterr()
        assert SENTINEL_PATIENT not in captured.out
