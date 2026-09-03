"""Unit tests for utils.py (pure helper functions)."""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import utils
from support.deps import requires_de_locale
from support.stubs import UserSettings
from version import VERSION


class TestDates:
    def test_convert_date4_german(self) -> None:
        assert utils.convert_date4("03.09.2026") == "2026-09-03"

    def test_convert_date4_us_fallback(self) -> None:
        assert utils.convert_date4("09/03/2026") == "2026-09-03"

    @pytest.mark.parametrize("bad", ["2026-09-03", "kein Datum", "", "3.9.26"])
    def test_convert_date4_invalid(self, bad: str) -> None:
        assert utils.convert_date4(bad) is None

    def test_convert_date2(self) -> None:
        assert utils.convert_date2("03.09.26") == "2026-09-03"
        assert utils.convert_date2("03.09.2026") is None

    def test_show_date4_roundtrip(self) -> None:
        assert utils.show_date4("2026-09-03") == "03.09.2026"
        assert utils.show_date4(utils.convert_date4("01.02.2020")) == "01.02.2020"
        assert utils.show_date4("03.09.2026") is None
        assert utils.show_date4(None) is None

    def test_yesterday_crosses_year(self) -> None:
        assert utils.yesterday("2026-01-01") == "2025-12-31"

    @pytest.mark.parametrize("d, expected", [
        (date(2026, 9, 3), "2026-02"),    # 90 days back: June -> Q2
        (date(2026, 1, 15), "2025-04"),   # turn of the year
        (date(2026, 4, 1), "2026-01"),    # 1.1. -> Q1
        (date(2026, 7, 1), "2026-02"),
    ])
    def test_last_quarter(self, d: date, expected: str) -> None:
        assert utils.last_quarter(d) == expected

    @pytest.mark.parametrize("quarter, expected", [
        ("2026-2", ("2026-04-01", "2026-06-30")),
        ("2026-02", ("2026-04-01", "2026-06-30")),
        ("2025-4", ("2025-10-01", "2025-12-31")),
        ("2024-1", ("2024-01-01", "2024-03-31")),
        ("2024-3", ("2024-07-01", "2024-09-30")),
    ])
    def test_quarter_to_dates(self, quarter: str, expected: tuple[str, str]) -> None:
        assert utils.quarter_to_dates(quarter) == expected

    def test_last_quarter_and_quarter_to_dates_are_consistent(self) -> None:
        q = utils.last_quarter(date(2026, 9, 3))
        start, end = utils.quarter_to_dates(q)
        assert start < end
        assert start.startswith(q.split("-")[0])

    @requires_de_locale
    def test_convert_date_written_month(self, restore_locale: None) -> None:
        assert utils.convert_date_written_month("15. März 2024") == "2024-03-15"
        assert utils.convert_date_written_month("1. Januar 2026") == "2026-01-01"
        assert utils.convert_date_written_month("15.03.2024") is None


class TestReadFloat:
    @pytest.mark.parametrize("s, expected", [
        ("1.234,56", 1234.56),      # German with thousands separator
        ("1,234.56", 1234.56),      # English
        ("12,50", 12.5),
        ("12.50", 12.5),            # two decimal places -> English
        ("1234", 1234.0),
        ("0,00", 0.0),
        ("*12,00", 12.0),           # asterisks (Kornkraft) are removed
        ("100,00 EUR", 100.0),      # only the first word counts
        ("12,50-", -12.5),          # trailing minus (bank format)
        ("-12,50", -12.5),
        ("  7,00  ", 7.0),
    ])
    def test_values(self, s: str, expected: float) -> None:
        assert utils.read_float(s) == pytest.approx(expected)

    def test_empty_is_zero(self) -> None:
        assert utils.read_float("") == 0.0
        assert utils.read_float(None) == 0.0

    def test_sign_soll(self) -> None:
        assert utils.read_float("12,50", "S") == -12.5
        assert utils.read_float("12,50", "H") == 12.5


class TestStrings:
    def test_remove_space(self) -> None:
        assert utils.remove_space("  a   b \n c ") == "a b c"

    def test_no_substr(self) -> None:
        assert utils.no_substr(["x", "y"], "abc") is True
        assert utils.no_substr(["b"], "abc") is False
        assert utils.no_substr([], "abc") is True

    def test_similar(self) -> None:
        assert utils.similar("abc", "abc") == 1.0
        assert utils.similar("abc", "xyz") == 0.0
        assert 0 < utils.similar("Krannich Solar", "Krannich Solar GmbH") < 1

    def test_showlist_skips_empty(self) -> None:
        assert utils.showlist(["a", None, 3, "", 0.5]) == "a / 3 / 0.5"
        assert utils.showlist([]) == ""

    @pytest.mark.parametrize("line, expected", [
        ("Rechnung 12345 Danke", "12345"),
        ("TAN 123456 Ueberweisung", "unbekannt"),
        ("nur Text ohne Zahlen", "unbekannt"),
        ("RE-2024-0815 Solar", "RE-2024-0815"),
        ("1234 zu kurz", "unbekannt"),       # len(w) > 4 required
        ("ab12 cd34 12345", "12345"),
    ])
    def test_find_ref(self, line: str, expected: str) -> None:
        assert utils.find_ref(line) == expected

    def test_extract_prnr(self) -> None:
        assert utils.extract_prnr("Ueberweisung Pre123 Solar") == "123"
        assert utils.extract_prnr("PreRechnung 5 Pre00042") == "00042"
        assert utils.extract_prnr("keine Nummer") is None
        # the 'R' in PreR00123 separates Pre from the digits
        assert utils.extract_prnr("PreR00123") is None

    def test_html_to_text(self) -> None:
        html = "<html><style>p {color: red}</style><body><p>Hallo    Welt</p>\n\n   <p>Zeile\t2</p></body></html>"
        text = utils.html_to_text(html)
        assert "Hallo Welt" in text
        assert "Zeile 2" in text
        assert "color" not in text
        assert "\n\n\n" not in text
        assert utils.html_to_text("<p>Name: <b>Max</b><br>Tel: 1</p><div>Ort</div>") == "Name: Max\nTel: 1\nOrt"


class TestFormatting:
    def test_to_str_float(self) -> None:
        assert utils.to_str(1234.5) == "  1234,50"
        assert utils.to_str(np.float64(2.0)) == "     2,00"
        assert utils.to_str(np.float32(-1.25)) == "    -1,25"

    def test_to_str_date_and_passthrough(self) -> None:
        assert utils.to_str("2026-09-03") == "03.09.2026"
        assert utils.to_str("Text") == "Text"
        assert utils.to_str(3) == 3
        assert utils.to_str(None) is None

    def test_get(self) -> None:
        assert utils.get({"a": 1}, "a") == 1
        assert utils.get({"a": 1}, "b") == ""

    def test_format_entry(self) -> None:
        doc = {"amount": 1.0, "date": "2026-01-02"}
        assert utils.format_entry(doc, ["amount", "date", "missing"], ["Betrag", "Datum", "Fehlt"]) == \
            "Betrag:      1,00\nDatum: 02.01.2026\nFehlt: "

    def test_format_dic(self) -> None:
        dic = {"flag": 1, "off": 0, "pdf": "/private/files/rechnung.pdf", "long": "x" * 40, "num": 5}
        out = utils.format_dic(["flag", "off", "absent"], ["pdf"], dic)
        assert out["flag"] == "✓"
        assert out["off"] == " "
        assert out["short_pdf"] == "rechnung.pdf"
        assert out["long"] == "x" * 35
        assert out["num"] == 5
        assert "absent" not in out

    def test_sum_dict(self) -> None:
        sums = utils.sum_dict({"a": {"x": 1.0, "y": 2.0}, "b": {"x": 3.0}})
        assert dict(sums) == {"x": 4.0, "y": 2.0}
        assert sums["unbekannt"] == 0.0

    def test_print_dicts(self, capsys: pytest.CaptureFixture[str]) -> None:
        utils.print_dict({"a": 1.234})
        utils.print_dict2({"c": {"a": 1.0}})
        out = capsys.readouterr().out
        assert "a : 1.23" in out
        assert "c\na : 1.00" in out

    def test_title(self, user_settings: UserSettings) -> None:
        user_settings["-company-"] = "Firma"
        user_settings["-server-"] = "https://srv"
        assert utils.title() == "ERPNext-Client für Firma@https://srv " + VERSION
        user_settings.delete_entry("-company-")
        user_settings.delete_entry("-server-")
        assert utils.title() == "ERPNext-Client für Unbekannt@unbekannt " + VERSION


class TestIban:
    def test_iban_de_known_example(self) -> None:
        # common example from the IBAN documentation
        assert utils.iban_de(37040044, 532013000) == "DE89370400440532013000"

    def test_iban_de_single_digit_check(self) -> None:
        assert utils.iban_de(12030000, 202051) == "DE02120300000000202051"

    def test_iban_de_length(self) -> None:
        assert len(utils.iban_de(37040044, 532013000)) == 22


class TestFiles:
    def test_store_temp_file(self) -> None:
        fn = utils.store_temp_file(b"abc", ".pdf")
        try:
            assert fn.endswith(".pdf")
            with open(fn, "rb") as f:
                assert f.read() == b"abc"
        finally:
            os.remove(fn)

    def test_get_csv_plain(self, tmp_path: Path) -> None:
        p = tmp_path / "a.csv"
        p.write_text("a;b\r\nc\nd;e\r\n", encoding="utf-8")
        rows = list(utils.get_csv("utf-8", str(p)))
        assert rows == [["a", "b"], ["c"], ["d", "e"]]

    def test_get_csv_replacenl_joins_embedded_newlines(self, tmp_path: Path) -> None:
        p = tmp_path / "a.csv"
        p.write_text("a;b\r\nc\nd;e\r\n", encoding="utf-8")
        rows = list(utils.get_csv("utf-8", str(p), replacenl=True))
        assert rows == [["a", "b"], ["c d", "e"], []]

    def test_get_csv_codec(self, tmp_path: Path) -> None:
        p = tmp_path / "latin.csv"
        p.write_bytes("Müller;1\n".encode("iso-8859-4"))
        assert list(utils.get_csv("iso-8859-4", str(p))) == [["Müller", "1"]]

    def test_evince_spawns_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = []

        class P:
            def __init__(self, args: list[str], **kwargs: Any) -> None:
                calls.append(args)
        monkeypatch.setattr(utils.subprocess, "Popen", P)
        utils.evince("/tmp/x.pdf")
        assert calls == [["evince", "/tmp/x.pdf"]]


class TestMisc:
    def test_running_linux(self) -> None:
        assert utils.running_linux() == sys.platform.startswith("linux")

    def test_get_current_location(self) -> None:
        class Accurate:
            def current_location(self, more_accurate: bool = False) -> tuple[int, int]:
                return (10, 20) if more_accurate else (0, 0)

        class Inaccurate:
            def current_location(self) -> tuple[int, int]:
                return (5, 5)
        assert utils.get_current_location(Accurate()) == (10, 20)
        assert utils.get_current_location(Inaccurate()) == (None, None)
