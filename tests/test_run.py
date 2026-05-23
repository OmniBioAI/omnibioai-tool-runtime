"""
Unit tests for omni_tool_runtime/run.py

Run:
    pytest tests/test_run.py -v
    pytest tests/test_run.py --cov=omni_tool_runtime/run --cov-report=term-missing -v
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

from omni_tool_runtime.run import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(env: dict, *, module=None):
    """
    Call main() with a controlled environment.

    - env:    dict passed to patch.dict("os.environ", ..., clear=True)
    - module: if provided, injected as the result of importlib.import_module;
              if None, import_module raises ImportError by default.
    """
    with patch.dict("os.environ", env, clear=True):
        if module is not None:
            with patch("omni_tool_runtime.run.importlib.import_module", return_value=module):
                return main()
        else:
            with patch(
                "omni_tool_runtime.run.importlib.import_module",
                side_effect=ImportError("no module"),
            ) as mock_import:
                return main(), mock_import


def _make_mod(main_return=0, has_main=True) -> types.ModuleType:
    """Return a fake tool module."""
    mod = types.ModuleType("tools.fake_tool.run")
    if has_main:
        mod.main = MagicMock(return_value=main_return)
    return mod


# ---------------------------------------------------------------------------
# TOOL_ID missing / empty
# ---------------------------------------------------------------------------


class TestToolIdMissing:
    def test_returns_2_when_tool_id_not_set(self, capsys):
        with patch.dict("os.environ", {}, clear=True):
            assert main() == 2

    def test_returns_2_when_tool_id_empty_string(self, capsys):
        with patch.dict("os.environ", {"TOOL_ID": ""}, clear=True):
            assert main() == 2

    def test_returns_2_when_tool_id_whitespace_only(self, capsys):
        with patch.dict("os.environ", {"TOOL_ID": "   "}, clear=True):
            assert main() == 2

    def test_stderr_message_when_tool_id_missing(self, capsys):
        with patch.dict("os.environ", {}, clear=True):
            main()
        assert "TOOL_ID" in capsys.readouterr().err

    def test_import_not_called_when_tool_id_missing(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("omni_tool_runtime.run.importlib.import_module") as mock_import,
        ):
            main()
        mock_import.assert_not_called()


# ---------------------------------------------------------------------------
# Module import failure
# ---------------------------------------------------------------------------


class TestImportFailure:
    def _call(self, tool_id="bad_tool", exc=None):
        exc = exc or ImportError("no module named tools.bad_tool.run")
        with (
            patch.dict("os.environ", {"TOOL_ID": tool_id}, clear=True),
            patch("omni_tool_runtime.run.importlib.import_module", side_effect=exc),
        ):
            return main()

    def test_returns_2_on_import_error(self):
        assert self._call() == 2

    def test_returns_2_on_arbitrary_exception(self):
        assert self._call(exc=RuntimeError("boom")) == 2

    def test_returns_2_on_module_not_found_error(self):
        assert self._call(exc=ModuleNotFoundError("nope")) == 2

    def test_stderr_contains_module_name(self, capsys):
        with (
            patch.dict("os.environ", {"TOOL_ID": "my_tool"}, clear=True),
            patch("omni_tool_runtime.run.importlib.import_module", side_effect=ImportError("x")),
        ):
            main()
        assert "tools.my_tool.run" in capsys.readouterr().err

    def test_stderr_contains_error_text(self, capsys):
        with (
            patch.dict("os.environ", {"TOOL_ID": "t"}, clear=True),
            patch(
                "omni_tool_runtime.run.importlib.import_module",
                side_effect=ImportError("specific error message"),
            ),
        ):
            main()
        assert "specific error message" in capsys.readouterr().err

    def test_import_called_with_correct_module_path(self):
        with (
            patch.dict("os.environ", {"TOOL_ID": "my_tool"}, clear=True),
            patch(
                "omni_tool_runtime.run.importlib.import_module", side_effect=ImportError("x")
            ) as mock_import,
        ):
            main()
        mock_import.assert_called_once_with("tools.my_tool.run")

    def test_tool_id_stripped_before_module_path_built(self):
        with (
            patch.dict("os.environ", {"TOOL_ID": "  spaced_tool  "}, clear=True),
            patch(
                "omni_tool_runtime.run.importlib.import_module", side_effect=ImportError("x")
            ) as mock_import,
        ):
            main()
        mock_import.assert_called_once_with("tools.spaced_tool.run")


# ---------------------------------------------------------------------------
# Module missing main()
# ---------------------------------------------------------------------------


class TestModuleMissingMain:
    def _call(self, tool_id="t"):
        mod = _make_mod(has_main=False)
        with (
            patch.dict("os.environ", {"TOOL_ID": tool_id}, clear=True),
            patch("omni_tool_runtime.run.importlib.import_module", return_value=mod),
        ):
            return main()

    def test_returns_2_when_no_main(self):
        assert self._call() == 2

    def test_stderr_mentions_missing_main(self, capsys):
        self._call(tool_id="no_main_tool")
        assert "main()" in capsys.readouterr().err

    def test_stderr_mentions_module_name(self, capsys):
        self._call(tool_id="no_main_tool")
        assert "tools.no_main_tool.run" in capsys.readouterr().err

    def test_main_not_invoked_when_absent(self):
        mod = _make_mod(has_main=False)
        with (
            patch.dict("os.environ", {"TOOL_ID": "t"}, clear=True),
            patch("omni_tool_runtime.run.importlib.import_module", return_value=mod),
        ):
            main()
        # No .main attribute means nothing to assert; reaching here without
        # AttributeError is the passing condition.


# ---------------------------------------------------------------------------
# Successful execution
# ---------------------------------------------------------------------------


class TestSuccessfulRun:
    def _call(self, tool_id="good_tool", main_return=0):
        mod = _make_mod(main_return=main_return)
        with (
            patch.dict("os.environ", {"TOOL_ID": tool_id}, clear=True),
            patch("omni_tool_runtime.run.importlib.import_module", return_value=mod),
        ):
            return main(), mod

    def test_returns_0_on_success(self):
        result, _ = self._call(main_return=0)
        assert result == 0

    def test_returns_1_when_tool_main_returns_1(self):
        result, _ = self._call(main_return=1)
        assert result == 1

    def test_returns_int(self):
        result, _ = self._call(main_return=0)
        assert isinstance(result, int)

    def test_tool_main_called_once(self):
        _, mod = self._call()
        mod.main.assert_called_once()

    def test_result_cast_to_int(self):
        # mod.main() returns a string "0"; run.main() should cast via int()
        mod = _make_mod()
        mod.main.return_value = "0"
        with (
            patch.dict("os.environ", {"TOOL_ID": "t"}, clear=True),
            patch("omni_tool_runtime.run.importlib.import_module", return_value=mod),
        ):
            result = main()
        assert result == 0
        assert isinstance(result, int)

    def test_no_stderr_on_success(self, capsys):
        self._call()
        assert capsys.readouterr().err == ""

    def test_import_called_with_correct_path(self):
        mod = _make_mod()
        with (
            patch.dict("os.environ", {"TOOL_ID": "specific_tool"}, clear=True),
            patch("omni_tool_runtime.run.importlib.import_module", return_value=mod) as mock_import,
        ):
            main()
        mock_import.assert_called_once_with("tools.specific_tool.run")

    def test_nonzero_exit_code_propagated(self):
        result, _ = self._call(main_return=3)
        assert result == 3


# ---------------------------------------------------------------------------
# __main__ block
# ---------------------------------------------------------------------------


class TestMainBlock:
    def test_raises_system_exit(self):
        mod = _make_mod(main_return=0)
        with (
            patch.dict("os.environ", {"TOOL_ID": "t"}, clear=True),
            patch("omni_tool_runtime.run.importlib.import_module", return_value=mod),
            patch("omni_tool_runtime.run.main", return_value=0),
            pytest.raises(SystemExit) as exc_info,
        ):
            import runpy

            runpy.run_module("omni_tool_runtime.run", run_name="__main__", alter_sys=False)
        assert exc_info.value.code == 0

    def test_raises_system_exit_with_error_code(self):
        with (
            patch("omni_tool_runtime.run.main", return_value=2),
            pytest.raises(SystemExit) as exc_info,
        ):
            import runpy

            runpy.run_module("omni_tool_runtime.run", run_name="__main__", alter_sys=False)
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# _run() helper coverage (lines 31-40)
# ---------------------------------------------------------------------------


class TestRunHelper:
    """Exercises the _run() helper directly to cover lines 31-40."""

    def test_run_with_module_returns_zero(self):
        mod = _make_mod(main_return=0)
        result = _run({"TOOL_ID": "tool-1"}, module=mod)
        assert result == 0

    def test_run_with_module_calls_tool_main(self):
        mod = _make_mod(main_return=0)
        _run({"TOOL_ID": "tool-1"}, module=mod)
        mod.main.assert_called_once()

    def test_run_with_module_propagates_nonzero_return(self):
        mod = _make_mod(main_return=3)
        result = _run({"TOOL_ID": "tool-1"}, module=mod)
        assert result == 3

    def test_run_without_module_returns_tuple(self):
        rc, mock_import = _run({"TOOL_ID": "tool-1"})
        assert rc == 2

    def test_run_without_module_mock_import_was_called(self):
        _, mock_import = _run({"TOOL_ID": "tool-1"})
        mock_import.assert_called_once_with("tools.tool-1.run")
