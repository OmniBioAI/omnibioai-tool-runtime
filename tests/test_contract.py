"""
Unit tests for omni_tool_runtime/contract.py

Run:
    pytest tests/test_contract.py -v
    pytest tests/test_contract.py --cov=omni_tool_runtime/contract --cov-report=term-missing -v

Developer: Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import json

import pytest

from omni_tool_runtime.contract import ToolContract, read_contract_from_env

# ---------------------------------------------------------------------------
# ToolContract dataclass
# ---------------------------------------------------------------------------


class TestToolContract:
    """The ToolContract dataclass stores tool_id/run_id/inputs/resources/result_uri verbatim and stays mutable."""
    def _make(self, **kw) -> ToolContract:
        """Build a ToolContract with sensible defaults, overridable per test."""
        defaults = dict(
            tool_id="tool-1",
            run_id="run-1",
            inputs={"param": "value"},
            resources={"cpu": 2},
            result_uri="s3://bucket/result.json",
        )
        return ToolContract(**{**defaults, **kw})

    def test_stores_tool_id(self):
        """Store the given tool_id unchanged."""
        assert self._make(tool_id="my-tool").tool_id == "my-tool"

    def test_stores_run_id(self):
        """Store the given run_id unchanged."""
        assert self._make(run_id="run-abc").run_id == "run-abc"

    def test_stores_inputs(self):
        """Store the given inputs dict unchanged."""
        inputs = {"alpha": 1, "beta": "x"}
        assert self._make(inputs=inputs).inputs == inputs

    def test_stores_resources(self):
        """Store the given resources dict unchanged."""
        resources = {"memory": "4Gi", "gpu": 0}
        assert self._make(resources=resources).resources == resources

    def test_stores_result_uri(self):
        """Store the given result_uri unchanged."""
        uri = "s3://my-bucket/path/result.json"
        assert self._make(result_uri=uri).result_uri == uri

    def test_empty_inputs_ok(self):
        """Accept an empty inputs dict without error."""
        assert self._make(inputs={}).inputs == {}

    def test_empty_resources_ok(self):
        """Accept an empty resources dict without error."""
        assert self._make(resources={}).resources == {}

    def test_empty_strings_ok(self):
        """Accept empty strings for tool_id/run_id/result_uri without error."""
        c = self._make(tool_id="", run_id="", result_uri="")
        assert c.tool_id == "" and c.run_id == "" and c.result_uri == ""

    def test_is_dataclass_instance(self):
        """ToolContract is a real dataclass, not a plain object mimicking one."""
        import dataclasses

        assert dataclasses.is_dataclass(self._make())

    def test_fields_are_assignable(self):
        """ToolContract fields are mutable after construction."""
        c = self._make()
        c.tool_id = "updated"
        assert c.tool_id == "updated"


# ---------------------------------------------------------------------------
# read_contract_from_env — happy paths
# ---------------------------------------------------------------------------


class TestReadContractFromEnvHappyPath:
    """read_contract_from_env() builds a ToolContract from well-formed TOOL_ID/RUN_ID/RESULT_URI/INPUTS_JSON/RESOURCES_JSON."""
    def _call(self, env: dict) -> ToolContract:
        """Read a ToolContract from a given environment mapping."""
        import unittest.mock as mock

        with mock.patch.dict("os.environ", env, clear=True):
            return read_contract_from_env()

    def test_returns_tool_contract(self):
        """Return a ToolContract instance from well-formed environment variables."""
        result = self._call(
            {
                "TOOL_ID": "t1",
                "RUN_ID": "r1",
                "RESULT_URI": "s3://b/r.json",
                "INPUTS_JSON": "{}",
                "RESOURCES_JSON": "{}",
            }
        )
        assert isinstance(result, ToolContract)

    def test_tool_id_read(self):
        """Read tool_id verbatim from TOOL_ID."""
        result = self._call(
            {
                "TOOL_ID": "my-tool",
                "RUN_ID": "",
                "RESULT_URI": "",
                "INPUTS_JSON": "{}",
                "RESOURCES_JSON": "{}",
            }
        )
        assert result.tool_id == "my-tool"

    def test_run_id_read(self):
        """Read run_id verbatim from RUN_ID."""
        result = self._call(
            {
                "TOOL_ID": "",
                "RUN_ID": "run-xyz",
                "RESULT_URI": "",
                "INPUTS_JSON": "{}",
                "RESOURCES_JSON": "{}",
            }
        )
        assert result.run_id == "run-xyz"

    def test_result_uri_read(self):
        """Read result_uri verbatim from RESULT_URI."""
        result = self._call(
            {
                "TOOL_ID": "",
                "RUN_ID": "",
                "RESULT_URI": "az://container/out.json",
                "INPUTS_JSON": "{}",
                "RESOURCES_JSON": "{}",
            }
        )
        assert result.result_uri == "az://container/out.json"

    def test_inputs_json_parsed(self):
        """Parse INPUTS_JSON into the inputs dict."""
        payload = {"vcf": "/data/file.vcf", "threshold": 0.05}
        result = self._call(
            {
                "TOOL_ID": "",
                "RUN_ID": "",
                "RESULT_URI": "",
                "INPUTS_JSON": json.dumps(payload),
                "RESOURCES_JSON": "{}",
            }
        )
        assert result.inputs == payload

    def test_resources_json_parsed(self):
        """Parse RESOURCES_JSON into the resources dict."""
        resources = {"cpu": 4, "memory": "8Gi"}
        result = self._call(
            {
                "TOOL_ID": "",
                "RUN_ID": "",
                "RESULT_URI": "",
                "INPUTS_JSON": "{}",
                "RESOURCES_JSON": json.dumps(resources),
            }
        )
        assert result.resources == resources

    def test_empty_inputs_json_gives_empty_dict(self):
        """Parse an INPUTS_JSON of "{}" into an empty inputs dict."""
        result = self._call(
            {
                "TOOL_ID": "",
                "RUN_ID": "",
                "RESULT_URI": "",
                "INPUTS_JSON": "{}",
                "RESOURCES_JSON": "{}",
            }
        )
        assert result.inputs == {}

    def test_empty_resources_json_gives_empty_dict(self):
        """Parse a RESOURCES_JSON of "{}" into an empty resources dict."""
        result = self._call(
            {
                "TOOL_ID": "",
                "RUN_ID": "",
                "RESULT_URI": "",
                "INPUTS_JSON": "{}",
                "RESOURCES_JSON": "{}",
            }
        )
        assert result.resources == {}

    def test_nested_inputs_parsed(self):
        """Parse nested objects inside INPUTS_JSON without flattening or dropping structure."""
        payload = {"filters": {"maf": 0.01, "tags": ["a", "b"]}}
        result = self._call(
            {
                "TOOL_ID": "",
                "RUN_ID": "",
                "RESULT_URI": "",
                "INPUTS_JSON": json.dumps(payload),
                "RESOURCES_JSON": "{}",
            }
        )
        assert result.inputs == payload

    def test_inputs_list_value_ok(self):
        """Parse a list-valued field inside INPUTS_JSON without coercion."""
        payload = {"samples": ["s1", "s2", "s3"]}
        result = self._call(
            {
                "TOOL_ID": "",
                "RUN_ID": "",
                "RESULT_URI": "",
                "INPUTS_JSON": json.dumps(payload),
                "RESOURCES_JSON": "{}",
            }
        )
        assert result.inputs["samples"] == ["s1", "s2", "s3"]

    def test_all_fields_populated_together(self):
        """Populate all five ToolContract fields correctly from one combined environment."""
        inputs = {"k": "v"}
        resources = {"cpu": 1}
        result = self._call(
            {
                "TOOL_ID": "t",
                "RUN_ID": "r",
                "RESULT_URI": "s3://b/f.json",
                "INPUTS_JSON": json.dumps(inputs),
                "RESOURCES_JSON": json.dumps(resources),
            }
        )
        assert result.tool_id == "t"
        assert result.run_id == "r"
        assert result.result_uri == "s3://b/f.json"
        assert result.inputs == inputs
        assert result.resources == resources


# ---------------------------------------------------------------------------
# read_contract_from_env — missing env vars use defaults
# ---------------------------------------------------------------------------


class TestReadContractFromEnvDefaults:
    """read_contract_from_env() falls back to empty strings/dicts when the corresponding env vars are unset."""
    def _call_empty(self) -> ToolContract:
        """Read a ToolContract from a completely empty environment."""
        import unittest.mock as mock

        with mock.patch.dict("os.environ", {}, clear=True):
            return read_contract_from_env()

    def test_tool_id_defaults_to_empty_string(self):
        """Default tool_id to an empty string when TOOL_ID is unset."""
        assert self._call_empty().tool_id == ""

    def test_run_id_defaults_to_empty_string(self):
        """Default run_id to an empty string when RUN_ID is unset."""
        assert self._call_empty().run_id == ""

    def test_result_uri_defaults_to_empty_string(self):
        """Default result_uri to an empty string when RESULT_URI is unset."""
        assert self._call_empty().result_uri == ""

    def test_inputs_defaults_to_empty_dict(self):
        """Default inputs to an empty dict when INPUTS_JSON is unset."""
        assert self._call_empty().inputs == {}

    def test_resources_defaults_to_empty_dict(self):
        """Default resources to an empty dict when RESOURCES_JSON is unset."""
        assert self._call_empty().resources == {}


# ---------------------------------------------------------------------------
# read_contract_from_env — bad JSON raises RuntimeError
# ---------------------------------------------------------------------------


class TestReadContractFromEnvBadJson:
    """read_contract_from_env() raises RuntimeError, naming the offending variable, on malformed INPUTS_JSON/RESOURCES_JSON."""
    def _call(self, env: dict):
        """Read a ToolContract from a given environment mapping, expected to raise."""
        import unittest.mock as mock

        with mock.patch.dict("os.environ", env, clear=True):
            return read_contract_from_env()

    def test_bad_inputs_json_raises_runtime_error(self):
        """Raise RuntimeError when INPUTS_JSON is not valid JSON."""
        with pytest.raises(RuntimeError):
            self._call(
                {
                    "TOOL_ID": "",
                    "RUN_ID": "",
                    "RESULT_URI": "",
                    "INPUTS_JSON": "not-json",
                    "RESOURCES_JSON": "{}",
                }
            )

    def test_bad_inputs_json_message_mentions_inputs(self):
        """Name INPUTS_JSON in the error message for invalid inputs JSON."""
        with pytest.raises(RuntimeError, match="INPUTS_JSON"):
            self._call(
                {
                    "TOOL_ID": "",
                    "RUN_ID": "",
                    "RESULT_URI": "",
                    "INPUTS_JSON": "{bad",
                    "RESOURCES_JSON": "{}",
                }
            )

    def test_bad_resources_json_raises_runtime_error(self):
        """Raise RuntimeError when RESOURCES_JSON is not valid JSON."""
        with pytest.raises(RuntimeError):
            self._call(
                {
                    "TOOL_ID": "",
                    "RUN_ID": "",
                    "RESULT_URI": "",
                    "INPUTS_JSON": "{}",
                    "RESOURCES_JSON": "not-json",
                }
            )

    def test_bad_resources_json_message_mentions_resources(self):
        """Name RESOURCES_JSON in the error message for invalid resources JSON."""
        with pytest.raises(RuntimeError, match="RESOURCES_JSON"):
            self._call(
                {
                    "TOOL_ID": "",
                    "RUN_ID": "",
                    "RESULT_URI": "",
                    "INPUTS_JSON": "{}",
                    "RESOURCES_JSON": "}bad{",
                }
            )

    def test_truncated_inputs_json_raises(self):
        """Raise RuntimeError for a truncated (incomplete) INPUTS_JSON payload."""
        with pytest.raises(RuntimeError):
            self._call(
                {
                    "TOOL_ID": "",
                    "RUN_ID": "",
                    "RESULT_URI": "",
                    "INPUTS_JSON": '{"key": ',
                    "RESOURCES_JSON": "{}",
                }
            )

    def test_plain_string_inputs_json_raises(self):
        # A bare string is valid JSON but not a dict — however json.loads
        # succeeds so it is stored as-is; this test confirms no error is raised.
        """A bare JSON string (not an object) for INPUTS_JSON parses successfully and is stored as-is, without raising."""
        result = self._call(
            {
                "TOOL_ID": "",
                "RUN_ID": "",
                "RESULT_URI": "",
                "INPUTS_JSON": '"just-a-string"',
                "RESOURCES_JSON": "{}",
            }
        )
        assert result.inputs == "just-a-string"

    def test_both_bad_raises_on_inputs_first(self):
        # inputs is parsed first, so a bad inputs raises before resources is checked
        """When both INPUTS_JSON and RESOURCES_JSON are malformed, the inputs error is raised first."""
        with pytest.raises(RuntimeError, match="INPUTS_JSON"):
            self._call(
                {
                    "TOOL_ID": "",
                    "RUN_ID": "",
                    "RESULT_URI": "",
                    "INPUTS_JSON": "!!!",
                    "RESOURCES_JSON": "!!!",
                }
            )
