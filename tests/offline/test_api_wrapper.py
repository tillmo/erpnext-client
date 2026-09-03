"""Tests for api_wrapper.py: capturing output/errors around API calls."""
from __future__ import annotations

import sys
from typing import NoReturn

import pytest

import api_wrapper
from version import VERSION


def ok(x: int, y: int = 1) -> int:
    return x + y


def noisy() -> int:
    print("Hallo")
    print("Warnung", file=sys.stderr)
    return 42


def failing() -> NoReturn:
    raise ValueError("kaputt")


class TestFunctionWrapper:
    def test_returns_resource_and_captures_output(self) -> None:
        r = api_wrapper.function_wrapper(noisy)
        assert r["resource"] == 42
        assert r["stdout"] == "Hallo\n"
        assert r["stderr"] == "Warnung\n"
        assert r["exception"] == ""

    def test_passes_arguments(self) -> None:
        assert api_wrapper.function_wrapper(ok, 2, y=3)["resource"] == 5

    def test_exception_is_captured_with_traceback(self) -> None:
        r = api_wrapper.function_wrapper(failing)
        assert r["resource"] == {}
        assert "kaputt" in r["exception"]
        assert "Traceback" in r["exception"]

    def test_streams_are_restored(self) -> None:
        out, err = sys.stdout, sys.stderr
        api_wrapper.function_wrapper(failing)
        assert sys.stdout is out and sys.stderr is err


class TestApiWrapper:
    def test_clean_call_has_no_error(self) -> None:
        r = api_wrapper.api_wrapper(ok, 1)
        assert r["err_msg"] == ""
        assert r["resource"] == 2

    def test_error_lines_are_extracted_from_html(self) -> None:
        def f() -> None:
            print("<html><p>Traceback (most recent call last):\n  File x\nValidationError: Konto fehlt\n</p></html>")
        r = api_wrapper.api_wrapper(f)
        assert r["err_msg"] == "ValidationError: Konto fehlt"

    def test_raise_exception_line_is_used_when_no_error_line(self) -> None:
        def f() -> None:
            print("<p>a\n    raise raise_exception(msg)\nDie eigentliche Meldung\nb</p>")
        r = api_wrapper.api_wrapper(f)
        assert r["err_msg"] == "Die eigentliche Meldung"

    def test_fallback_to_head_and_tail(self) -> None:
        def f() -> None:
            print("<p>" + "\n".join("zeile{}".format(i) for i in range(40)) + "</p>")
        r = api_wrapper.api_wrapper(f)
        lines = r["err_msg"].split("\n")
        assert lines[0] == "<p>zeile0"
        assert "[...]" in lines
        assert len(lines) == 10 + 1 + 14

    def test_plain_output_counts_as_error_message(self) -> None:
        # this makes server responses visible that FrappeClient.post_process only prints
        r = api_wrapper.api_wrapper(noisy)
        assert r["err_msg"] == "Hallo"

    def test_whitespace_only_output_is_no_error(self) -> None:
        def f() -> None:
            print("   \n  ")
        assert api_wrapper.api_wrapper(f)["err_msg"] == ""


class TestApiWrapperTest:
    def test_true_on_success(self) -> None:
        assert api_wrapper.api_wrapper_test(ok, 1) is True

    def test_false_on_exception_or_output(self) -> None:
        assert api_wrapper.api_wrapper_test(failing) is False
        assert api_wrapper.api_wrapper_test(noisy) is False


class TestGuiApiWrapper:
    def test_returns_resource(self) -> None:
        assert api_wrapper.gui_api_wrapper(ok, 1, y=2) == 3

    def test_returns_none_and_reports_on_exception(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert api_wrapper.gui_api_wrapper(failing) is None
        out = capsys.readouterr().out
        assert "Fehler in Kommunikation mit dem ERPNext API" in out
        assert VERSION in out
        assert "kaputt" in out
        assert "Aufruf: ()" in out

    def test_treats_stdout_as_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert api_wrapper.gui_api_wrapper(noisy) is None
        assert "Hallo" in capsys.readouterr().out
