"""Tests für table.Table (Datenaufbereitung, CSV- und PDF-Export; die GUI-Anzeige bleibt außen vor)."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest
from reportlab.lib.pagesizes import A4

import table
from support.stubs import GuiCalled

ENTRIES = [{"date": "2026-01-02", "amount": 1234.5, "text": "erste Zeile", "bold": 3},
           {"date": "2026-01-03", "amount": -2.0, "text": "zweite", "disabled": True},
           {"date": "2026-01-04", "amount": 0.0, "bold": 1}]
KEYS = ["date", "amount", "text"]
HEADINGS = ["Datum", "Betrag", "Text"]


def make(**kw: Any) -> table.Table:
    return table.Table(ENTRIES, KEYS, HEADINGS, "Titel", **kw)


class TestData:
    def test_data_is_formatted(self) -> None:
        tbl = make()
        assert tbl.data == [["02.01.2026", "  1234,50", "erste Zeile"],
                            ["03.01.2026", "    -2,00", "zweite"],
                            ["04.01.2026", "     0,00", ""]]
        assert tbl.entries is ENTRIES and tbl.headings == HEADINGS and tbl.keys == KEYS

    def test_defaults_and_format(self) -> None:
        tbl = make()
        assert (tbl.just, tbl.max_col_width, tbl.display_row_numbers, tbl.enable_events) == ("left", 60, False, False)
        assert (tbl.page_width, tbl.page_height) == (A4[0], A4[1])
        tbl = make(landscape=True)
        assert (tbl.page_width, tbl.page_height) == (A4[1], A4[0])


class TestExport:
    def test_csv_export(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        fn = tmp_path / "t.csv"
        tbl = make(filename=str(fn))
        tbl.csv_export()
        rows = list(csv.reader(fn.open(encoding="utf-8"), delimiter=";"))
        assert rows == [HEADINGS] + tbl.data
        assert "exportiert" in capsys.readouterr().out

    def test_pdf_export(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        fn = tmp_path / "t.pdf"
        tbl = make(filename=str(fn))
        tbl.pdf_export()
        data = fn.read_bytes()
        assert data.startswith(b"%PDF") and len(data) > 500
        assert tbl.landscape is False

    def test_pdf_export_landscape_and_child(self, tmp_path: Path) -> None:
        child = table.Table([{"a": 1}], ["a"], ["A"], "Kind")
        fn = tmp_path / "t.pdf"
        tbl = make(filename=str(fn), child=child, child_title=" mit Kind")
        tbl.pdf_export(with_child=True, landscape=True)
        assert tbl.landscape is True and (tbl.page_width, tbl.page_height) == (A4[1], A4[0])
        assert fn.read_bytes().startswith(b"%PDF")

    def test_pdf_elements_apply_bold_levels(self) -> None:
        entries = [{"a": 1, "bold": 3}, {"a": 2}, {"a": 3, "bold": 1}, {"a": 4, "bold": 2}]
        elements = table.Table(entries, ["a"], ["A"], "T").pdf_elements()
        assert len(elements) == 2                      # Abstandhalter + Tabelle
        t = elements[1]
        assert t._nrows == len(entries) + 1
        fonts = [t._cellStyles[row][0].fontname for row in range(t._nrows)]
        assert fonts == ["Helvetica-Bold",             # Kopfzeile
                         "Helvetica-Bold",             # bold 3
                         "Helvetica",                  # ohne bold
                         "Helvetica-Oblique",          # bold 1
                         "Helvetica-BoldOblique"]      # bold 2


class TestDisplay:
    def test_display_needs_gui(self) -> None:
        with pytest.raises(GuiCalled):
            make().display()
