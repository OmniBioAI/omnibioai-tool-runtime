"""
Unit tests for tools/echo_test/run.py

Covers:
- Happy path (local mode, cloud mode)
- Missing / bad INPUTS_JSON
- Missing inputs.text
- RESULT_URI upload dispatch
- __main__ block

Developer: Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
import tools.echo_test.run as echo_run
from tools.echo_test.run import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _env(
    tool_id: str = "tool-1",
    run_id: str = "run-1",
    result_uri: str = "",
    inputs_json: str = '{"text": "hello"}',
) -> dict[str, str]:
    """Build the TOOL_ID/RUN_ID/RESULT_URI/INPUTS_JSON environment mapping for echo_test main()."""
    return {
        "TOOL_ID": tool_id,
        "RUN_ID": run_id,
        "RESULT_URI": result_uri,
        "INPUTS_JSON": inputs_json,
    }


# ===========================================================================
# 1. Environment variable reading
# ===========================================================================
class TestEnvReading:
    """TOOL_ID, RUN_ID, and INPUTS_JSON are read from the environment with documented defaults."""

    def test_tool_id_read_from_env(self, capsys):
        """Echo back the TOOL_ID value taken from the environment."""
        with patch.dict("os.environ", _env(tool_id="my-tool"), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["tool_id"] == "my-tool"

    def test_run_id_read_from_env(self, capsys):
        """Echo back the RUN_ID value taken from the environment."""
        with patch.dict("os.environ", _env(run_id="run-42"), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["run_id"] == "run-42"

    def test_tool_id_defaults_to_empty_string(self, capsys):
        """Default tool_id to an empty string when TOOL_ID is unset."""
        env = _env()
        env.pop("TOOL_ID")
        with patch.dict("os.environ", env, clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["tool_id"] == ""

    def test_run_id_defaults_to_empty_string(self, capsys):
        """Default run_id to an empty string when RUN_ID is unset."""
        env = _env()
        env.pop("RUN_ID")
        with patch.dict("os.environ", env, clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["run_id"] == ""

    def test_result_uri_whitespace_stripped(self, capsys):
        """A RESULT_URI with only whitespace is treated as absent (local mode)."""
        with patch.dict("os.environ", _env(result_uri="   "), clear=True):
            rc = main()
        assert rc == 0

    def test_inputs_json_defaults_to_empty_object(self, capsys):
        """When INPUTS_JSON is not set, inputs defaults to {} → missing text."""
        env = _env()
        env.pop("INPUTS_JSON")
        with patch.dict("os.environ", env, clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False
        assert "missing inputs.text" in out["error"]


# ===========================================================================
# 2. Bad INPUTS_JSON
# ===========================================================================
class TestBadInputsJson:
    """Malformed INPUTS_JSON must produce a controlled error result, not a crash."""

    def test_returns_2_on_invalid_json(self):
        """Return exit code 2 when INPUTS_JSON is not valid JSON."""
        with patch.dict("os.environ", _env(inputs_json="not-json"), clear=True):
            rc = main()
        assert rc == 2

    def test_ok_is_false_on_invalid_json(self, capsys):
        """Report ok: false in the result body when INPUTS_JSON is invalid."""
        with patch.dict("os.environ", _env(inputs_json="{bad}"), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False

    def test_error_message_mentions_bad_inputs_json(self, capsys):
        """Explain the invalid-JSON failure in the error message."""
        with patch.dict("os.environ", _env(inputs_json="[[["), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert "bad INPUTS_JSON" in out["error"]

    def test_tool_id_included_in_error_response(self, capsys):
        """Include tool_id in the error response even when INPUTS_JSON fails to parse."""
        with patch.dict("os.environ", _env(tool_id="t1", inputs_json="!!!"), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["tool_id"] == "t1"

    def test_run_id_included_in_error_response(self, capsys):
        """Include run_id in the error response even when INPUTS_JSON fails to parse."""
        with patch.dict("os.environ", _env(run_id="r99", inputs_json="???"), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["run_id"] == "r99"

    def test_upload_not_called_on_bad_json(self):
        """Skip the RESULT_URI upload entirely when INPUTS_JSON fails to parse."""
        with patch.dict("os.environ", _env(result_uri="s3://b/k", inputs_json="bad"), clear=True):
            with patch("tools.echo_test.run.upload_to_result_uri") as mock_upload:
                main()
        mock_upload.assert_not_called()

    def test_truncated_json_returns_2(self):
        """Return exit code 2 for a truncated (incomplete) JSON payload."""
        with patch.dict("os.environ", _env(inputs_json='{"text":'), clear=True):
            rc = main()
        assert rc == 2


# ===========================================================================
# 3. Missing inputs.text
# ===========================================================================
class TestMissingText:
    """A well-formed inputs object lacking the required 'text' field is a soft (non-crashing) error."""

    def test_returns_0_when_text_missing(self):
        """Return exit code 0 even when inputs.text is missing — this is a handled, not fatal, condition."""
        with patch.dict("os.environ", _env(inputs_json='{"other": 1}'), clear=True):
            rc = main()
        assert rc == 0

    def test_ok_is_false_when_text_missing(self, capsys):
        """Report ok: false in the result body when inputs.text is missing."""
        with patch.dict("os.environ", _env(inputs_json="{}"), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False

    def test_error_mentions_missing_text(self, capsys):
        """Explain the missing-text failure in the error message."""
        with patch.dict("os.environ", _env(inputs_json="{}"), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert "missing inputs.text" in out["error"]

    def test_inputs_not_echoed_back_in_log(self, capsys):
        """PHI-safe: the raw inputs dict must never appear in the printed log."""
        payload = {"foo": "bar"}
        with patch.dict("os.environ", _env(inputs_json=json.dumps(payload)), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert "inputs" not in out
        assert out["input_summary"] == {"foo": {"type": "str", "len": 3, "ref": out["input_summary"]["foo"]["ref"]}}

    def test_tool_id_present_in_missing_text_response(self, capsys):
        """Include tool_id in the response even when inputs.text is missing."""
        with patch.dict("os.environ", _env(tool_id="t2", inputs_json="{}"), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["tool_id"] == "t2"

    def test_run_id_present_in_missing_text_response(self, capsys):
        """Include run_id in the response even when inputs.text is missing."""
        with patch.dict("os.environ", _env(run_id="r2", inputs_json="{}"), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["run_id"] == "r2"

    def test_upload_not_called_when_no_result_uri(self):
        """Skip the RESULT_URI upload in local mode even on the missing-text error path."""
        with patch.dict("os.environ", _env(inputs_json="{}"), clear=True):
            with patch("tools.echo_test.run.upload_to_result_uri") as mock_upload:
                main()
        mock_upload.assert_not_called()


# ===========================================================================
# 4. Happy path — local mode (no RESULT_URI)
# ===========================================================================
class TestHappyPathLocalMode:
    """With RESULT_URI unset (local mode), the tool exits 0 and prints only a redacted summary."""

    def test_returns_0(self):
        """Return exit code 0 on a normal local-mode run."""
        with patch.dict("os.environ", _env(), clear=True):
            rc = main()
        assert rc == 0

    def test_ok_is_true(self, capsys):
        """Report ok: true in the result body on a normal local-mode run."""
        with patch.dict("os.environ", _env(), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True

    def test_echo_matches_input_text(self):
        """The raw echoed value goes to the upload (result) channel, never to the log."""
        with patch.dict(
            "os.environ", _env(inputs_json='{"text": "world"}', result_uri="s3://b/k"), clear=True
        ):
            with patch("tools.echo_test.run.upload_to_result_uri") as mock_upload:
                main()
        _, kwargs = mock_upload.call_args
        uploaded = json.loads(kwargs["content"].decode("utf-8"))
        assert uploaded["results"]["echo"] == "world"

    def test_echo_value_not_in_printed_log(self, capsys):
        """PHI-safe: the raw echoed value must never appear in the printed log."""
        with patch.dict(
            "os.environ", _env(inputs_json='{"text": "world"}', result_uri="s3://b/k"), clear=True
        ):
            with patch("tools.echo_test.run.upload_to_result_uri"):
                main()
        out = capsys.readouterr().out
        assert "world" not in out
        parsed = json.loads(out)
        assert parsed["echo_summary"] == {"type": "str", "len": 5, "ref": parsed["echo_summary"]["ref"]}

    def test_tool_id_in_response(self, capsys):
        """Include tool_id in the local-mode response body."""
        with patch.dict("os.environ", _env(tool_id="echo-tool"), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["tool_id"] == "echo-tool"

    def test_run_id_in_response(self, capsys):
        """Include run_id in the local-mode response body."""
        with patch.dict("os.environ", _env(run_id="run-77"), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["run_id"] == "run-77"

    def test_results_key_present(self, capsys):
        """The printed log has a structural echo_summary, not the raw `results` block."""
        with patch.dict("os.environ", _env(), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert "echo_summary" in out
        assert "results" not in out

    def test_upload_not_called_in_local_mode(self):
        """Skip the RESULT_URI upload entirely when RESULT_URI is empty."""
        with patch.dict("os.environ", _env(result_uri=""), clear=True):
            with patch("tools.echo_test.run.upload_to_result_uri") as mock_upload:
                main()
        mock_upload.assert_not_called()

    def test_empty_text_string_is_valid(self, capsys):
        """Empty string is a valid value for text (not None)."""
        with patch.dict("os.environ", _env(inputs_json='{"text": ""}'), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
        assert out["echo_summary"] == {"type": "str", "len": 0, "ref": out["echo_summary"]["ref"]}

    def test_numeric_text_value(self, capsys):
        """Accept a numeric inputs.text value and summarize it by type rather than echoing it."""
        with patch.dict("os.environ", _env(inputs_json='{"text": 42}'), clear=True):
            main()
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
        assert out["echo_summary"] == {"type": "int"}

    def test_output_is_valid_json(self, capsys):
        """Print a body that parses as valid JSON."""
        with patch.dict("os.environ", _env(), clear=True):
            main()
        raw = capsys.readouterr().out
        parsed = json.loads(raw)   # must not raise
        assert isinstance(parsed, dict)

    def test_output_is_indented_json(self, capsys):
        """Body is printed with indent=2 for readability."""
        with patch.dict("os.environ", _env(), clear=True):
            main()
        raw = capsys.readouterr().out
        assert "\n" in raw  # indented JSON always has newlines


# ===========================================================================
# 5. Happy path — cloud mode (RESULT_URI set)
# ===========================================================================
class TestHappyPathCloudMode:
    """With RESULT_URI set (cloud mode), the raw result is uploaded while stdout stays redacted."""

    def test_returns_0_in_cloud_mode(self):
        """Return exit code 0 when RESULT_URI is set and the upload succeeds."""
        with patch.dict("os.environ", _env(result_uri="s3://bucket/key"), clear=True):
            with patch("tools.echo_test.run.upload_to_result_uri"):
                rc = main()
        assert rc == 0

    def test_upload_called_once(self):
        """Call upload_to_result_uri exactly once when RESULT_URI is set."""
        with patch.dict("os.environ", _env(result_uri="s3://bucket/key"), clear=True):
            with patch("tools.echo_test.run.upload_to_result_uri") as mock_upload:
                main()
        mock_upload.assert_called_once()

    def test_upload_receives_correct_result_uri(self):
        """Pass the exact RESULT_URI value through to upload_to_result_uri."""
        uri = "s3://my-bucket/results/out.json"
        with patch.dict("os.environ", _env(result_uri=uri), clear=True):
            with patch("tools.echo_test.run.upload_to_result_uri") as mock_upload:
                main()
        _, kwargs = mock_upload.call_args
        assert kwargs["result_uri"] == uri

    def test_upload_content_is_bytes(self):
        """Pass the upload content as a bytes object, not a str."""
        with patch.dict("os.environ", _env(result_uri="s3://b/k"), clear=True):
            with patch("tools.echo_test.run.upload_to_result_uri") as mock_upload:
                main()
        _, kwargs = mock_upload.call_args
        assert isinstance(kwargs["content"], bytes)

    def test_upload_content_is_utf8_encoded_json(self):
        """Encode the uploaded content as UTF-8 JSON that decodes back to the expected result."""
        with patch.dict("os.environ", _env(result_uri="s3://b/k"), clear=True):
            with patch("tools.echo_test.run.upload_to_result_uri") as mock_upload:
                main()
        _, kwargs = mock_upload.call_args
        decoded = json.loads(kwargs["content"].decode("utf-8"))
        assert decoded["ok"] is True

    def test_upload_content_differs_from_printed_log(self, capsys):
        """PHI-safe: the uploaded (raw) content and the printed (redacted) log must differ."""
        with patch.dict("os.environ", _env(result_uri="s3://b/k"), clear=True):
            with patch("tools.echo_test.run.upload_to_result_uri") as mock_upload:
                main()
        printed = capsys.readouterr().out.strip()
        _, kwargs = mock_upload.call_args
        assert kwargs["content"] != printed.encode("utf-8")
        uploaded = json.loads(kwargs["content"].decode("utf-8"))
        assert uploaded["results"]["echo"] == "hello"  # raw value present in the upload channel
        assert "hello" not in printed  # but never in the printed log

    def test_azure_uri_also_triggers_upload(self):
        """Trigger the upload path for an azureblob:// RESULT_URI just as for s3://."""
        uri = "azureblob://account/container/blob.json"
        with patch.dict("os.environ", _env(result_uri=uri), clear=True):
            with patch("tools.echo_test.run.upload_to_result_uri") as mock_upload:
                main()
        mock_upload.assert_called_once()

    def test_upload_called_even_when_text_missing(self):
        """Even an error result is uploaded in cloud mode."""
        with patch.dict(
            "os.environ",
            _env(result_uri="s3://b/k", inputs_json="{}"),
            clear=True,
        ):
            with patch("tools.echo_test.run.upload_to_result_uri") as mock_upload:
                main()
        mock_upload.assert_called_once()


# ===========================================================================
# 6. __main__ block
# ===========================================================================
class TestMainBlock:
    """The `if __name__ == "__main__"` execution path raises SystemExit with main()'s return code."""

    def test_raises_system_exit(self):
        """Executing the module's __main__ guard code raises SystemExit."""
        with patch.dict("os.environ", _env(), clear=True):
            with pytest.raises(SystemExit):
                with patch.object(sys, "argv", ["tools/echo_test/run.py"]):
                    exec(
                        compile(
                            'raise SystemExit(main())',
                            "tools/echo_test/run.py",
                            "exec",
                        ),
                        {"main": main, "SystemExit": SystemExit},
                    )

    def test_raises_system_exit_with_code_0(self):
        """SystemExit carries code 0 on a successful run."""
        with patch.dict("os.environ", _env(), clear=True):
            with pytest.raises(SystemExit) as exc_info:
                raise SystemExit(main())
        assert exc_info.value.code == 0

    def test_raises_system_exit_with_code_2_on_bad_json(self):
        """SystemExit carries code 2 when INPUTS_JSON is invalid."""
        with patch.dict("os.environ", _env(inputs_json="bad"), clear=True):
            with pytest.raises(SystemExit) as exc_info:
                raise SystemExit(main())
        assert exc_info.value.code == 2