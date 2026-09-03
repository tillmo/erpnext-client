"""Tests der lieferantenspezifischen Textparser (PurchaseInvoiceParser) mit synthetischen Zeilen.

Die Zeilen in support.factories bilden die Spaltengeometrie nach, die der Parser erwartet
(feste Offsets wie item_str[73:99]). Ob echte PDFs diese Geometrie liefern, prüft der
Online-Regressionstest tests/online_read/test_parser_regression.py.
"""
from __future__ import annotations

import pytest

from support import factories as F
from support.deps import skip_module_without_pdftotext, requires_de_locale
from support.fakes import FakeFrappeClient
from support.stubs import GuiCalled

skip_module_without_pdftotext()

import settings  # noqa: E402
from company import Company  # noqa: E402
from purchase_invoice import PurchaseInvoice  # noqa: E402
from purchase_invoice_parser import PurchaseInvoiceParser  # noqa: E402


def parse(comp: Company, supplier: str, lines: list[str], update_stock: bool = True) -> tuple[PurchaseInvoice, PurchaseInvoiceParser]:
    pinv = F.make_purchase_invoice(comp, update_stock)
    parser = PurchaseInvoiceParser(pinv, supplier, lines)
    parser.set_purchase_info()
    return pinv, parser


class TestKrannich:
    def test_header_and_items(self, somiko: Company) -> None:
        pinv, parser = parse(somiko, "krannich", F.krannich_lines())
        assert pinv.no == "41234567" and pinv.date == "2024-03-15"
        assert pinv.order_id == "AB998877"
        assert len(pinv.items) == 2
        modul, kabel = pinv.items
        assert (modul.item_code, modul.qty, modul.qty_unit, modul.amount, modul.rate) == ("KS-MOD-400", 2, "Stk", 1000.0, 500.0)
        assert modul.description == "Solarmodul 400 Wp schwarz"
        assert "Einzelpreis" not in modul.long_description
        # Rolle -> Meter aus der Beschreibung
        assert (kabel.item_code, kabel.qty, kabel.qty_unit, kabel.rate) == ("KS-KAB-50", 50, "Meter", 2.0)

    def test_roll_length_with_mm_in_description(self, somiko: Company) -> None:
        lines = F.krannich_lines()
        lines[8] = F.layout({5: "Solarkabel 6mm2 Rolle 50 m"})
        pinv, parser = parse(somiko, "krannich", lines)
        assert pinv.items[1].qty == 50 and pinv.items[1].qty_unit == "Meter"
        lines[8] = F.layout({5: "Solarkabel 6mm2 Rolle 100 Meter"})
        assert parse(somiko, "krannich", lines)[0].items[1].qty == 100

    def test_totals(self, somiko: Company) -> None:
        pinv, parser = parse(somiko, "krannich", F.krannich_lines())
        assert pinv.shipping == 100.0
        assert pinv.totals[19.0] == 1200.0 and pinv.vat[19.0] == 228.0
        assert pinv.total == 1200.0 and pinv.gross_total == 1428.0
        assert pinv.check_total() == ""

    def test_no_shipping_without_stock(self, somiko: Company) -> None:
        pinv, parser = parse(somiko, "krannich", F.krannich_lines(), update_stock=False)
        assert pinv.shipping == 0
        assert pinv.totals[19.0] == 1200.0

    def test_get_purchase_data(self, somiko: Company) -> None:
        pinv, parser = parse(somiko, "krannich", F.krannich_lines())
        pinv.supplier = "Krannich Solar GmbH & Co KG"
        data = parser.get_purchase_data()
        assert data["supplier"] == "Krannich Solar GmbH & Co KG"
        assert data["bill_no"] == "41234567" and data["order_id"] == "AB998877" and data["posting_date"] == "2024-03-15"
        assert data["total"] == 1200.0 and data["grand_total"] == 1428.0 and data["shipping"] == 100.0
        assert data["taxes"] == [{"rate": 19.0, "tax_amount": 228.0}]
        assert data["items"][0] == {"description": "Solarmodul 400 Wp schwarz", "qty": 2, "uom": "Stk", "rate": 500.0,
                                    "amount": 1000.0}

    def test_get_purchase_data_omits_missing_keys(self, somiko: Company) -> None:
        pinv = F.make_purchase_invoice(somiko)
        pinv.items, pinv.shipping = [], 0
        data = PurchaseInvoiceParser(pinv, "krannich", []).get_purchase_data()
        assert set(data) == {"supplier", "total", "grand_total", "taxes"}

    def test_get_amount_krannich(self) -> None:
        lines = [F.right_aligned("Freight", "12,50", 40), F.right_aligned("Insurance", "7,50", 40)]
        assert PurchaseInvoiceParser.get_amount_krannich(lines) == 20.0
        assert PurchaseInvoiceParser.get_amount_krannich([]) == 0


class TestHeckert:
    def test_parse(self, somiko: Company) -> None:
        pinv, parser = parse(somiko, "heckert", F.heckert_lines())
        assert pinv.no == "RE-2024-555" and pinv.date == "2024-04-12" and pinv.order_id == "AU-77001"
        assert len(pinv.items) == 1
        item = pinv.items[0]
        assert (item.item_code, item.qty, item.qty_unit) == ("HS-MOD-380", 2, "Stk")
        assert item.amount == 550.0 and item.rate == 275.0      # Rabatt eingerechnet
        assert item.description == "Modul NeMo 380 Wp"
        assert pinv.shipping == 30.0                             # Transportkosten-Position
        assert pinv.totals[19.0] == 580.0 and pinv.vat[19.0] == 110.20
        assert pinv.gross_total == 690.20
        assert pinv.check_total() == ""


class TestWagner:
    @requires_de_locale
    def test_rechnung(self, somiko: Company, restore_locale: None) -> None:
        pinv, parser = parse(somiko, "wagner", F.wagner_lines(rechnung=True))
        assert parser.is_rechnung is True
        assert pinv.no == "RE-88001" and pinv.date == "2024-03-15" and pinv.order_id == "AUF-4242"
        assert len(pinv.items) == 1
        item = pinv.items[0]
        assert (item.item_code, item.qty, item.qty_unit, item.amount, item.rate) == ("WS-ART-1", 3, "Stk", 600.0, 200.0)
        assert item.description == "Hybrid-Wechselrichter 5 kW"
        assert pinv.shipping == 45.0
        assert pinv.totals[19.0] == 645.0 and pinv.vat[19.0] == 122.55
        assert pinv.check_total() == ""

    @requires_de_locale
    def test_vorkasserechnung(self, somiko: Company, restore_locale: None) -> None:
        pinv, parser = parse(somiko, "wagner", F.wagner_lines(rechnung=False))
        assert parser.is_rechnung is False
        assert pinv.no == "VOR20841"
        assert [i.item_code for i in pinv.items] == ["WS-ART-1"]
        assert pinv.items[0].qty == 3 and pinv.shipping == 45.0

    @pytest.mark.parametrize("line, expected_no, is_rechnung", [
        ("1. Vorkasserechnung VOR20841   BEGeno / SolidarStrom", "VOR20841", False),
        ("Rechnung RE-1 Kunde", "RE-1", True),
        ("Auftragsbestätigung AB-9", "AB-9", False),
        ("Zwischensumme 100,00", None, None),
    ])
    def test_set_no_wagner(self, somiko: Company, line: str, expected_no: str | None, is_rechnung: bool | None) -> None:
        pinv = F.make_purchase_invoice(somiko)
        pinv.no = None
        parser = PurchaseInvoiceParser(pinv, "wagner", [])
        matched = parser.set_no_wagner(line, line.split())
        assert matched is (expected_no is not None)
        assert pinv.no == expected_no
        if is_rechnung is not None:
            assert parser.is_rechnung is is_rechnung

    def test_set_item_wagner_ignores_continuation_lines(self, somiko: Company) -> None:
        pinv = F.make_purchase_invoice(somiko, True)
        pinv.items, pinv.shipping = [], 0
        parser = PurchaseInvoiceParser(pinv, "wagner", [])
        parser.is_rechnung = True
        parser.set_item_wagner(["12 Jahre Produktgarantie\n"])
        parser.set_item_wagner(["Text ohne Position\n"])
        parser.set_item_wagner(["28100 Summe 5,00\n"])
        assert pinv.items == []

    def test_set_items_survives_broken_position(self, somiko: Company, capsys: pytest.CaptureFixture[str]) -> None:
        pinv = F.make_purchase_invoice(somiko, True)
        pinv.items, pinv.shipping = [], 0
        parser = PurchaseInvoiceParser(pinv, "wagner", [])
        parser.is_rechnung = False
        parser.line_items = [[], ["1 Kaputt ohne Artikelnr 3 200,00 600,00\n"], ["2 WS-A Ok 1 Stück 5,00 5,00\n"]]
        parser.set_items()
        assert "Position konnte nicht gelesen werden" in capsys.readouterr().out
        assert len(pinv.items) == 0    # zweite Position: Artikelnr. fehlt ebenfalls (Vorkasse-Format)


class TestPvXchange:
    def test_items_and_totals(self, somiko: Company) -> None:
        pinv, parser = parse(somiko, "pvxchange", F.pvxchange_lines())
        assert len(pinv.items) == 1
        item = pinv.items[0]
        assert (item.qty, item.rate, item.amount, item.qty_unit, item.item_code) == (4, 150.0, 600.0, "Stk", "PVX-410")
        assert item.description.startswith("Solarmodul Mono 410 Wp")
        assert pinv.shipping == 40.0
        assert pinv.totals[19.0] == 640.0 and pinv.vat[19.0] == 121.60
        assert pinv.check_total() == ""

    def test_number_and_date_on_invoice(self, somiko: Company) -> None:
        pinv, parser = parse(somiko, "pvxchange", F.pvxchange_lines())
        assert pinv.no == "PVX-2024-100" and pinv.date == "2024-05-12"


class TestNkkAndKornkraft:
    def test_nkk(self, laden: Company) -> None:
        pinv, parser = parse(laden, "nkk", F.nkk_lines(), update_stock=False)
        assert pinv.no == "555123" and pinv.date == "2024-06-12"
        assert pinv.vat == {19.0: 22.80, 7.0: 14.70}
        assert pinv.totals == {19.0: 120.0, 7.0: 210.0}
        assert pinv.total == 330.0 and pinv.gross_total == 367.5
        by_acc = {i["expense_account"]: i for i in pinv.e_items}
        assert by_acc[settings.NKK_ACCOUNTS[19.0]]["rate"] == 120.0
        assert by_acc[settings.NKK_ACCOUNTS[7.0]]["rate"] == 210.0
        assert pinv.items == []

    def test_kornkraft(self, laden: Company) -> None:
        pinv, parser = parse(laden, "kornkraft", F.kornkraft_lines(), update_stock=False)
        assert pinv.no == "777001" and pinv.date == "2024-06-20"
        assert pinv.vat == {19.0: 19.0, 7.0: 21.0}
        assert pinv.totals == {19.0: 100.0, 7.0: 300.0}
        assert pinv.gross_total == 440.0
        assert {i["expense_account"] for i in pinv.e_items} == set(settings.KORNKRAFT_ACCOUNTS.values())

    def test_kornkraft_asterisks_are_removed(self, laden: Company) -> None:
        lines = F.kornkraft_lines()
        lines[-2] = "Steuer 19,0 % Netto 100,00 *19,00 *119,00\n"
        pinv, parser = parse(laden, "kornkraft", lines, update_stock=False)
        assert pinv.vat[19.0] == 19.0


class TestGeneric:
    def test_generic_supplier_headless(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        pinv = F.make_purchase_invoice(somiko)
        PurchaseInvoiceParser(pinv, "generic", F.GENERIC_INVOICE_LINES, is_test=True).set_purchase_info()
        assert pinv.no == "2026-0815" and pinv.totals[19.0] == 100.0
        assert fake_api.calls == []

    def test_generic_supplier_without_is_test_reaches_gui(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        pinv = F.make_purchase_invoice(somiko)
        with pytest.raises(GuiCalled):
            PurchaseInvoiceParser(pinv, "generic", F.GENERIC_INVOICE_LINES).set_purchase_info()
