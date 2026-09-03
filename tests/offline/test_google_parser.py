"""Tests für purchase_invoice_google_parser.py (Auswertung des Google-Document-AI-JSON)."""
from __future__ import annotations

from typing import Any

import pytest

from support import factories as F
from support.deps import skip_module_without_pdftotext, requires_datefinder

skip_module_without_pdftotext()

import purchase_invoice_google_parser as gp  # noqa: E402
from company import Company  # noqa: E402
from purchase_invoice import PurchaseInvoice  # noqa: E402
from purchase_invoice_google_parser import PurchaseInvoiceGoogleParser  # noqa: E402


def simple_find_date(s: str | None) -> str | None:
    import utils
    if s and len(s) == 10 and s[4] == "-":
        return s
    return utils.convert_date4(s) if s else None


@pytest.fixture(autouse=True)
def patched_find_date(monkeypatch: pytest.MonkeyPatch) -> None:
    # datefinder ist optional und bei deutschen Datumsformaten nicht deterministisch
    monkeypatch.setattr(gp, "find_date", simple_find_date)


def run(comp: Company, invoice_json: dict[str, Any], supplier: str | None = None, update_stock: bool = False,
        is_test: bool = True) -> tuple[PurchaseInvoice, PurchaseInvoiceGoogleParser]:
    pinv = F.make_purchase_invoice(comp, update_stock)
    parser = PurchaseInvoiceGoogleParser(pinv, invoice_json, supplier, is_test)
    parser.set_purchase_info()
    return pinv, parser


class TestHelpers:
    def test_get_element_with_high_confidence(self) -> None:
        j = F.google_invoice_json()
        assert gp.get_element_with_high_confidence(j, "supplier") == "Muster Solartechnik GmbH"
        assert gp.get_element_with_high_confidence(j, "bill_no") == "RE 2024-77"
        assert gp.get_element_with_high_confidence(j, "gibt_es_nicht") is None

    def test_get_element_strips_strings_only(self) -> None:
        j = {"entities": [{"type": "x", "value": "  a  ", "confidence": 0.5}, {"type": "y", "value": 3, "confidence": "0.9"}]}
        assert gp.get_element_with_high_confidence(j, "x") == "a"
        assert gp.get_element_with_high_confidence(j, "y") == 3

    @pytest.mark.parametrize("s, expected", [
        ("1.190,00 EUR", 1190.0), ("1190.50", 1190.5), ("1,5", 1.5), ("USD 12.30", 12.3),
        ("1 234,50", 1234.5), ("abc", 0), ("", 0),
    ])
    def test_get_float_number(self, s: str, expected: float) -> None:
        assert gp.get_float_number(s) == expected

    @requires_datefinder
    def test_find_date_real(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.undo()
        import importlib
        importlib.reload(gp)
        assert gp.find_date("Rechnungsdatum 2024-03-15") == "2024-03-15"
        assert gp.find_date("kein datum") is None


class TestSetPurchaseInfo:
    def test_basic_fields(self, somiko: Company) -> None:
        pinv, parser = run(somiko, F.google_invoice_json())
        assert pinv.no == "RE2024-77"               # Leerzeichen entfernt
        assert pinv.supplier == "Muster Solartechnik GmbH"
        assert pinv.order_id == "BEST-1"
        assert pinv.gross_total == 1190.0 and pinv.totals[19.0] == 1000.0 and pinv.vat[19.0] == 190.0
        assert pinv.date == "2024-03-15"
        assert pinv.supplier_address is None and pinv.shipping_address is None
        assert pinv.shipping == 0 and pinv.items == []
        assert pinv.total == 1000.0 and pinv.extract_items is False

    def test_given_supplier_wins(self, somiko: Company) -> None:
        pinv, _ = run(somiko, F.google_invoice_json(), supplier="Vorgabe GmbH")
        assert pinv.supplier == "Vorgabe GmbH"

    def test_vat_derived_from_gross(self, somiko: Company) -> None:
        pinv, _ = run(somiko, F.google_invoice_json(net=None, tax=None))
        assert pinv.vat[19.0] == 190.0 and pinv.totals[19.0] == 1000.0

    def test_only_net_given(self, somiko: Company) -> None:
        pinv, _ = run(somiko, F.google_invoice_json(total=None, tax=None, net="1.000,00"))
        assert pinv.gross_total == 1000.0
        assert pinv.vat[19.0] == 159.66 and pinv.totals[19.0] == 840.34

    def test_net_recomputed_when_inconsistent(self, somiko: Company) -> None:
        pinv, _ = run(somiko, F.google_invoice_json(net="900,00"))
        assert pinv.totals[19.0] == 1000.0

    def test_tax_and_gross_without_net(self, somiko: Company) -> None:
        pinv, _ = run(somiko, F.google_invoice_json(net=None))
        assert pinv.totals[19.0] == 1000.0

    @pytest.mark.parametrize("posting, due, supplier, expected", [
        ("15.03.2024", "20.03.2024", "X", "2024-03-15"),
        ("25.03.2024", "20.03.2024", "X", "2024-03-20"),      # min()
        ("25.03.2024", "20.03.2024", "Heckert Solar GmbH", "2024-03-20"),
        ("15.03.2024", "10.03.2024", "Heckert Solar GmbH", "2024-03-10"),   # Heckert: immer due_date
        (None, "20.03.2024", "X", "2024-03-20"),
        ("15.03.2024", None, "X", "2024-03-15"),
        (None, None, "X", None),
    ])
    def test_date_logic(self, somiko: Company, posting: str | None, due: str | None, supplier: str, expected: str | None) -> None:
        pinv, _ = run(somiko, F.google_invoice_json(posting_date=posting, due_date=due), supplier=supplier)
        assert pinv.date == expected


ITEMS_OK = [
    {"description": "Solarmodul 400", "code": "M1", "qty": "2 Stk", "rate": "100,00", "amount": "200,00"},
    {"description": "Kleinteile", "amount": "20,00"},          # ohne Menge -> übersprungen, landet im Rundungsrest
    {"description": "Vorkasse Abzug", "qty": "1", "amount": "-500,00"},
]


class TestItems:
    def test_items_are_parsed(self, somiko: Company, capsys: pytest.CaptureFixture[str]) -> None:
        j = F.google_invoice_json(total="261,80", tax="41,80", net="220,00", items=ITEMS_OK)
        pinv, parser = run(somiko, j, update_stock=True)
        assert len(pinv.items) == 1
        item = pinv.items[0]
        assert (item.description, item.item_code, item.qty, item.qty_unit, item.rate, item.amount) == \
            ("Solarmodul 400", "M1", 2.0, "Stk", 100.0, 200.0)
        assert item.long_description == "Solarmodul 400"
        # 261,80 - 41,80 - 200 = 20 -> als Rundungsrest zu den Versandkosten
        assert pinv.shipping == 20.0
        # totals enthalten wie bei den internen Parsern den Versand
        assert pinv.totals[19.0] == 220.0 and pinv.gross_total == 261.80
        assert pinv.check_total() == ""
        assert pinv.extract_items is True
        assert "Keine Mengen- oder Wertangabe gefunden für Kleinteile" in capsys.readouterr().out

    def test_gross_total_includes_shipping(self, somiko: Company) -> None:
        j = F.google_invoice_json(total="261,80", tax="41,80", net="220,00", items=ITEMS_OK)
        pinv, _ = run(somiko, j, update_stock=True)
        assert pinv.gross_total == 261.80

    def test_freight_positions_go_to_shipping(self, somiko: Company) -> None:
        items = [{"description": "Modul", "qty": "1", "rate": "200,00", "amount": "200,00"},
                 {"description": "Fracht", "qty": "1", "rate": "20,00", "amount": "20,00"},
                 {"description": "Versandkosten", "qty": "1", "amount": "5,00"}]
        # Brutto so gewählt, dass kein Rundungsrest entsteht: 200 + 25 = 225 netto
        j = F.google_invoice_json(total="267,75", tax="42,75", net="225,00", items=items)
        pinv, _ = run(somiko, j, update_stock=True)
        assert [i.description for i in pinv.items] == ["Modul"]
        assert pinv.shipping == pytest.approx(25.0)
        assert pinv.totals[19.0] == 225.0 and pinv.check_total() == ""

    def test_freight_is_not_double_counted(self, somiko: Company) -> None:
        items = [{"description": "Modul", "qty": "1", "rate": "200,00", "amount": "200,00"},
                 {"description": "Fracht", "qty": "1", "rate": "20,00", "amount": "20,00"}]
        j = F.google_invoice_json(total="261,80", tax="41,80", net="220,00", items=items)
        pinv, _ = run(somiko, j, update_stock=True)
        assert pinv.shipping == 20.0
        assert pinv.totals[19.0] == 220.0

    @pytest.mark.parametrize("qty_str, expected", [("3X", 3.0), ("2 Stk", 2.0), ("4 ST", 4.0), ("5STX", 5.0), ("-1", 0)])
    def test_quantity_parsing(self, somiko: Company, qty_str: str, expected: float) -> None:
        items = [{"description": "A", "qty": qty_str, "rate": "10,00", "amount": "10,00"}]
        j = F.google_invoice_json(total="11,90", tax="1,90", net="10,00", items=items)
        pinv, _ = run(somiko, j, update_stock=True)
        if expected:
            assert pinv.items[0].qty == expected
        else:
            assert pinv.items == []   # Menge 0 -> nicht übernommen

    def test_amount_or_qty_derived_from_rate(self, somiko: Company) -> None:
        items = [{"description": "A", "qty": "2", "rate": "10,00"},        # amount = rate*qty
                 {"props": [("item-description", "B"), ("item-amount", "30,00"), ("item-unit-price", "10,00")]}]  # qty = amount/rate
        j = F.google_invoice_json(total="59,50", tax="9,50", net="50,00", items=items)
        pinv, _ = run(somiko, j, update_stock=True)
        a, b = pinv.items
        assert (a.qty, a.amount) == (2.0, 20.0)
        assert (b.qty, b.amount, b.rate) == (3.0, 30.0, 10.0)

    def test_rate_computed_when_missing(self, somiko: Company) -> None:
        items = [{"description": "A", "qty": "4", "amount": "10,00"}]
        j = F.google_invoice_json(total="11,90", tax="1,90", net="10,00", items=items)
        pinv, _ = run(somiko, j, update_stock=True)
        assert pinv.items[0].rate == 2.5

    def test_items_ignored_without_stock(self, somiko: Company) -> None:
        j = F.google_invoice_json(items=ITEMS_OK)
        pinv, _ = run(somiko, j, update_stock=False)
        assert pinv.items == []


class TestErrors:
    def test_stock_invoice_raises(self, somiko: Company) -> None:
        with pytest.raises(KeyError):
            run(somiko, {}, update_stock=True)

    def test_non_stock_invoice_reports(self, somiko: Company, capsys: pytest.CaptureFixture[str]) -> None:
        run(somiko, {}, update_stock=False, is_test=False)
        assert "Rückfall auf Standard-Rechnungsbehandlung" in capsys.readouterr().out

    def test_non_stock_invoice_silent_in_test(self, somiko: Company, capsys: pytest.CaptureFixture[str]) -> None:
        run(somiko, {}, update_stock=False, is_test=True)
        assert capsys.readouterr().out == ""


class TestGetPurchaseData:
    def test_full(self, somiko: Company) -> None:
        j = F.google_invoice_json(total="261,80", tax="41,80", net="220,00", items=ITEMS_OK)
        pinv, parser = run(somiko, j, update_stock=True)
        data = parser.get_purchase_data()
        assert data["supplier"] == "Muster Solartechnik GmbH"
        assert data["bill_no"] == "RE2024-77" and data["order_id"] == "BEST-1" and data["posting_date"] == "2024-03-15"
        assert data["total"] == 220.0 and data["grand_total"] == 261.80 and data["shipping"] == 20.0
        assert data["taxes"] == [{"rate": 19, "tax_amount": 41.80}]
        assert data["items"] == [{"item_code": "M1", "description": "Solarmodul 400", "qty": 2.0, "uom": "Stk",
                                  "rate": 100.0, "amount": 200.0}]

    def test_minimal(self, somiko: Company) -> None:
        pinv = F.make_purchase_invoice(somiko)
        pinv.items, pinv.shipping = [], 0
        data = PurchaseInvoiceGoogleParser(pinv, {}, None, True).get_purchase_data()
        assert data == {"supplier": None, "total": 0, "grand_total": 0, "taxes": []}
