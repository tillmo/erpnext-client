"""Tests für purchase_invoice.py (ohne Lieferanten-Parser, siehe test_purchase_invoice_parser.py)."""
import subprocess

import pytest

from support import factories as F
from support.deps import skip_module_without_pdftotext
from support.stubs import GuiCalled

skip_module_without_pdftotext()

import purchase_invoice  # noqa: E402
import settings  # noqa: E402
from purchase_invoice import PurchaseInvoice  # noqa: E402
from supplier_item import SupplierItem  # noqa: E402


@pytest.fixture
def pinv(somiko):
    return F.make_purchase_invoice(somiko)


@pytest.fixture
def generic_pdf(tmp_path):
    return F.write_generic_invoice_pdf(tmp_path / "rechnung.pdf")


class TestExtractors:
    def test_extract_amounts(self):
        assert purchase_invoice.extract_amounts("Summe 119,00 EUR, MwSt 19,00 und 7") == [119.0, 19.0]
        assert purchase_invoice.extract_amounts("nichts") == []
        # Tausenderpunkte werden nicht erkannt: nur der Teil nach dem Punkt zählt
        assert purchase_invoice.extract_amounts("1.234,56") == [234.56]

    def test_extract_amount_and_vat_direct(self):
        lines = ["Netto 100,00", "MwSt 19,00", "Brutto 119,00"]
        assert purchase_invoice.extract_amount_and_vat(lines, [19.0, 7.0]) == (119.0, 19.0)

    def test_extract_amount_and_vat_reduced_rate(self):
        assert purchase_invoice.extract_amount_and_vat(["Brutto 107,00", "MwSt 7,00"], [19.0, 7.0]) == (107.0, 7.0)

    def test_extract_amount_and_vat_via_mwst_line(self):
        lines = ["Rabatt 200,00", "Brutto 119,00", "MwSt 19% 19,00"]
        assert purchase_invoice.extract_amount_and_vat(lines, [19.0]) == (119.0, 19.0)

    def test_extract_amount_and_vat_fallbacks(self):
        assert purchase_invoice.extract_amount_and_vat(["Betrag 50,00"], [19.0]) == (50.0, 0)
        assert purchase_invoice.extract_amount_and_vat(["kein Betrag"], [19.0]) == (None, None)

    def test_extract_date_prefers_rechnungsdatum(self):
        lines = ["Lieferdatum 01.09.2026", "Rechnungsdatum 03.09.2026"]
        assert purchase_invoice.extract_date(lines) == "2026-09-03"
        assert purchase_invoice.extract_date(["irgendwo 05.09.2026 im Text"]) == "2026-09-05"
        assert purchase_invoice.extract_date(["kein Datum"]) is None

    @pytest.mark.parametrize("line, expected", [
        ("Rechnungsnummer: 2026-0815", "2026-0815"),
        ("Rechnungs-Nr. 4711", "4711"),
        ("Rechnung Nr 2024/117", "Nr 2024/117"),     # 'Rechnung'-Muster nimmt das Wort 'Nr' mit
        ("Belegnummer / Document Number RE-2024-555", "RE-2024-555"),
        ("Deine Rechnung RE_77 vom", "RE_77"),
        ("Zahlung EXP-24-01-00042 erhalten", "EXP-24-01-00042"),
        ("Seite 1 von 2 Rechnungsnr. 999", None),
        ("Verwendungszweck Rechnung 12345", None),
        ("nur Text", None),
    ])
    def test_extract_no(self, line, expected):
        assert purchase_invoice.extract_no([line]) == expected

    def test_extract_no_takes_longest_candidate(self):
        assert purchase_invoice.extract_no(["Rechnungsnr. 12", "Rechnungsnummer: 2026-0815"]) == "2026-0815"

    def test_extract_supplier(self):
        assert purchase_invoice.extract_supplier(["  Muster   GmbH  \n", "x"]) == "Muster GmbH"
        assert len(purchase_invoice.extract_supplier(["A" * 200])) == 80

    def test_decode_utf8(self):
        assert purchase_invoice.decode_uft_8("ä\n".encode("utf-8")) == "ä\n"
        assert purchase_invoice.decode_uft_8(b"\xff\xfe") == ""


class TestPdfToText:
    def test_lines_end_with_newline(self, generic_pdf):
        lines = purchase_invoice.pdf_to_text(generic_pdf)
        assert lines and all(l.endswith("\n") for l in lines)
        assert " ".join(lines[0].split()) == "Muster Solartechnik GmbH"
        assert any("2026-0815" in l for l in lines)

    def test_raw_mode(self, generic_pdf):
        lines = purchase_invoice.pdf_to_text(generic_pdf, raw=True)
        assert any("Rechnungsdatum" in l for l in lines)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="pdftotext"):
            purchase_invoice.pdf_to_text(str(tmp_path / "fehlt.pdf"))

    def test_check_pdftotext_rejects_old_version(self, monkeypatch):
        class R:
            def __init__(self, out):
                self.stdout = out
        monkeypatch.setattr(subprocess, "run", lambda cmd, **k: R(b"pdftotext version 3.03\n") if "-v" in cmd else R(b""))
        with pytest.raises(RuntimeError, match="version >= 4"):
            purchase_invoice._check_pdftotext()

    def test_check_pdftotext_falls_back_to_layout(self, monkeypatch, capsys):
        class R:
            def __init__(self, out):
                self.stdout = out
        monkeypatch.setattr(subprocess, "run",
                            lambda cmd, **k: R(b"pdftotext version 24.02.0\n") if "-v" in cmd else R(b"-layout only"))
        old = purchase_invoice.PDFTOTEXT_LAYOUT_OPTION
        try:
            purchase_invoice._check_pdftotext()
            assert purchase_invoice.PDFTOTEXT_LAYOUT_OPTION == "-layout"
            assert "WARNUNG" in capsys.readouterr().out
        finally:
            purchase_invoice.PDFTOTEXT_LAYOUT_OPTION = old

    def test_ask_if_to_continue(self, gui):
        assert purchase_invoice.ask_if_to_continue("") is True
        gui.answers["ccbox"] = False
        assert purchase_invoice.ask_if_to_continue("Fehler", " weiter?") is False
        assert gui.calls[-1][1][0] == "Fehler weiter?"


class TestInit:
    def test_defaults(self, pinv, somiko):
        assert pinv.company is somiko and pinv.company_name == somiko.name
        assert pinv.default_vat == 19.0 and pinv.vat_rates == [19.0]
        assert pinv.vat == {19.0: 0.0} and pinv.totals == {19.0: 0.0}
        assert pinv.update_stock is False and pinv.aggregate_item_code is None
        assert pinv.e_items == [] and pinv.infiles == [] and pinv.is_duplicate is False
        assert pinv.skonto == 0 and pinv.parser is None and pinv.cli_overrides is None
        assert pinv.date is None and pinv.order_id is None and pinv.paid_by_submitter is False

    def test_two_vat_rates(self, laden):
        p = F.make_purchase_invoice(laden)
        assert sorted(p.vat_rates) == [7.0, 19.0] and p.default_vat == 19.0

    def test_extract_order_id(self, pinv):
        pinv.extract_order_id("Auftragsbestätigung", "Ihre Auftragsbestätigung AB123 vom 1.1.")
        assert pinv.order_id == "AB123"
        pinv.extract_order_id("Order confirmation", "Order confirmation")   # kein Folgewort -> unverändert
        assert pinv.order_id == "AB123"
        pinv.extract_order_id("Fehlt", "andere Zeile")
        assert pinv.order_id == "AB123"


class TestTotalsAndItems:
    def test_compute_total(self, pinv, capsys):
        pinv.totals[19.0] = 100.0
        pinv.vat[19.0] = 19.0
        pinv.compute_total()
        assert (pinv.total, pinv.total_vat, pinv.gross_total) == (100.0, 19.0, 119.0)
        assert "Abweichung" not in capsys.readouterr().out

    def test_compute_total_reports_vat_deviation(self, pinv, capsys):
        pinv.totals[19.0] = 100.0
        pinv.vat[19.0] = 18.0
        pinv.compute_total()
        assert "Abweichung bei MWSt" in capsys.readouterr().out

    def test_assign_default_e_items(self, pinv):
        pinv.totals[19.0] = 100.0
        pinv.update_stock = True
        pinv.assign_default_e_items({19.0: "4210 - Miete und Nebenkosten - SoMiKo"})
        assert pinv.e_items == [{"item_code": settings.DEFAULT_ITEM_CODE, "qty": 1, "rate": 100.0,
                                 "expense_account": "4210 - Miete und Nebenkosten - SoMiKo", "cost_center": "Haupt - SoMiKo"}]
        assert pinv.update_stock is False

    def test_assign_default_e_items_negative_and_two_rates(self, laden):
        p = F.make_purchase_invoice(laden)
        p.totals[19.0] = -50.0
        p.totals[7.0] = 20.0
        p.assign_default_e_items(settings.NKK_ACCOUNTS)
        by_rate = {i["rate"]: i for i in p.e_items}
        assert by_rate[50.0]["qty"] == -1 and by_rate[50.0]["expense_account"] == settings.NKK_ACCOUNTS[19.0]
        assert by_rate[20.0]["qty"] == 1 and by_rate[20.0]["expense_account"] == settings.NKK_ACCOUNTS[7.0]

    def test_assign_default_e_items_skips_zero_totals(self, pinv):
        pinv.assign_default_e_items({19.0: "X"})
        assert pinv.e_items == []

    def test_assign_aggregate_e_item(self, somiko):
        p = F.make_purchase_invoice(somiko, True, aggregate_item_code=settings.AGGREGATE_ITEMS["default"])
        p.totals[19.0] = 250.0
        p.assign_aggregate_e_item()
        assert p.e_items == [{"item_code": "000.100.301", "qty": 2.5, "rate": 100.0, "cost_center": "Haupt - SoMiKo"}]
        p.shipping = 50.0        # Versand ist in totals enthalten und wird separat gebucht
        p.assign_aggregate_e_item()
        assert p.e_items[0]["qty"] == 2.0

    def test_create_taxes(self, pinv):
        pinv.vat[19.0] = 19.0
        pinv.create_taxes()
        assert pinv.taxes == [{"add_deduct_tax": "Add", "charge_type": "Actual",
                               "account_head": "1576 - Abziehbare VSt. 19% - SoMiKo", "cost_center": "Haupt - SoMiKo",
                               "description": settings.VAT_DESCRIPTION, "tax_amount": 19.0}]
        pinv.vat[19.0] = 0.0
        pinv.create_taxes()
        assert pinv.taxes == []

    def test_create_doc(self, pinv):
        pinv.supplier, pinv.no, pinv.date = "Muster GmbH", "2026-0815", "2026-09-03"
        pinv.totals[19.0], pinv.vat[19.0] = 100.0, 19.0
        pinv.compute_total()
        pinv.assign_default_e_items({19.0: "4210 - Miete und Nebenkosten - SoMiKo"})
        pinv.create_taxes()
        pinv.project, pinv.remarks, pinv.order_id = "PROJ-0001", "Bemerkung", "AB-1"
        pinv.create_doc()
        d = pinv.doc
        assert d["doctype"] == "Purchase Invoice" and d["company"] == pinv.company.name
        assert d["title"] == "Muster 2026-0815"
        assert d["bill_no"] == "2026-0815" and d["posting_date"] == "2026-09-03" and d["order_id"] == "AB-1"
        assert d["project"] == "PROJ-0001" and d["remarks"] == "Bemerkung"
        assert d["credit_to"] == pinv.company.payable_account
        assert d["naming_series"] == settings.STANDARD_NAMING_SERIES_PINV
        assert d["buying_price_list"] == settings.STANDARD_PRICE_LIST
        assert d["update_stock"] == 0 and d["is_return"] is False and d["set_posting_time"] == 1
        assert d["items"] == pinv.e_items and d["taxes"] == pinv.taxes
        assert "discount_amount" not in d

    def test_create_doc_skonto_shipping_return(self, pinv):
        pinv.supplier, pinv.no = "A B", "1"
        pinv.totals[19.0] = -10.0
        pinv.compute_total()
        pinv.taxes = []
        pinv.skonto, pinv.shipping = 3.0, 12.5
        pinv.create_doc()
        assert pinv.doc["is_return"] is True
        assert pinv.doc["apply_discount_on"] == "Grand Total" and pinv.doc["discount_amount"] == 3.0
        assert pinv.doc["taxes"] == [{"add_deduct_tax": "Add", "charge_type": "Actual",
                                      "account_head": settings.DELIVERY_COST_ACCOUNT,
                                      "description": settings.DELIVERY_COST_DESCRIPTION, "tax_amount": 12.5}]

    def test_check_total(self, pinv):
        pinv.total, pinv.shipping = 250.0, 50.0
        item = SupplierItem(pinv)
        item.rate, item.qty = 100.0, 2
        pinv.items = [item]
        assert pinv.check_total() == ""
        pinv.shipping = 40.0
        err = pinv.check_total()
        assert "Abweichung! Summe in Rechnung: 250.0, Summe der Posten: 240.0" in err
        assert pinv.check_total(check_dup=False) == ""

    def test_check_duplicates(self, pinv):
        pinv.e_items = [{"item_code": "A", "qty": 1}, {"item_code": "A", "qty": 2}, {"item_code": "B", "qty": 1}]
        err = pinv.check_duplicates()
        assert "mehrfach" in err and "Trotzdem Rechnung erstellen?" in err
        pinv.e_items = [{"item_code": settings.AGGREGATE_ITEMS["default"]}, {"item_code": settings.AGGREGATE_ITEMS["default"]}]
        assert pinv.check_duplicates() == ""
        pinv.e_items = []
        assert pinv.check_duplicates() == ""

    def test_summary(self, pinv):
        from api import Api
        Api.items_by_code = {"000.000.000": {"item_name": "Generisch"}}
        pinv.supplier, pinv.no, pinv.date = "Muster GmbH", "1", "2026-09-03"
        pinv.totals[19.0], pinv.vat[19.0] = 100.0, 19.0
        pinv.compute_total()
        pinv.assign_default_e_items({19.0: "4210 - Miete und Nebenkosten - SoMiKo"})
        pinv.create_taxes()
        pinv.doc = None
        s = pinv.summary()
        assert "Rechnungsnr.: 1" in s and "Lieferant: Muster GmbH" in s
        assert "1x 000.000.000 Generisch à 100.00€ = 100.00€ auf 4210" in s
        assert "19.00€ auf 1576 - Abziehbare VSt. 19% - SoMiKo" in s
        assert s.splitlines()[-1] == "Summe: 119.00€"
        assert all(len(l) <= 70 for l in s.splitlines())


class TestCheckIfPresent:
    def test_no_number(self, pinv, fake_api):
        assert pinv.check_if_present() is False
        pinv.no = "  "
        assert pinv.check_if_present() is False
        assert fake_api.calls == []

    def test_check_dup_false(self, pinv, fake_api):
        pinv.no = "1"
        assert pinv.check_if_present(check_dup=False) is False

    def test_duplicate_found_attaches_pdf(self, pinv, fake_api, gui, generic_pdf):
        name = fake_api.add("Purchase Invoice", bill_no="2026-0815", status="Unpaid", supplier="M")
        fake_api.add("Purchase Invoice", bill_no="2026-0815", status="Cancelled", supplier="M")
        pinv.no, pinv.infiles = "2026-0815", [generic_pdf]
        gui.answers["msgbox"] = None
        assert pinv.check_if_present() is True
        assert pinv.is_duplicate is True and pinv.doc["name"] == name
        assert fake_api.attachments == [("Purchase Invoice", name, "/private/files/rechnung.pdf")]
        msg = gui.calls[-1][1][0]
        assert "schon als {} in ERPNext".format(name) in msg and "wurde dort angefügt" in msg

    def test_order_id_match_only_warns(self, pinv, fake_api, gui):
        fake_api.add("Purchase Invoice", bill_no="anders", order_id="AB-1", status="Unpaid")
        pinv.no, pinv.order_id = "neu", "AB-1"
        gui.answers["msgbox"] = None
        assert pinv.check_if_present() is False
        assert pinv.is_duplicate is False
        assert "möglicherweise" in gui.calls[-1][1][0]

    def test_not_present(self, pinv, fake_api):
        pinv.no = "neu"
        assert pinv.check_if_present() is False


class TestApplyChanges:
    def _diff_symbols(self):
        from jsondiff.symbols import insert, delete
        return insert, delete

    def test_insert(self, pinv):
        insert, delete = self._diff_symbols()
        diff = {insert: {"supplier": "Neu GmbH", "taxes": [{"rate": 19.0, "tax_amount": 19.0}],
                         "items": [{"description": "Modul", "qty": 2, "uom": "Stk", "rate": 5.0, "amount": 10.0}],
                         "total": 100.0, "grand_total": 119.0, "bill_no": "B-1", "order_id": "O-1",
                         "posting_date": "2026-01-01", "shipping": 3.0}}
        pinv.apply_info_changes(diff, None)
        assert pinv.supplier == "Neu GmbH" and pinv.vat[19.0] == 19.0 and pinv.total_vat == 19.0
        assert len(pinv.items) == 1 and pinv.items[0].description == "Modul" and pinv.items[0].qty_unit == "Stk"
        assert pinv.totals[19.0] == 100.0 and pinv.gross_total == 119.0
        assert (pinv.no, pinv.order_id, pinv.date, pinv.shipping) == ("B-1", "O-1", "2026-01-01", 3.0)

    def test_insert_zero_taxes(self, pinv):
        insert, _ = self._diff_symbols()
        pinv.vat[19.0] = 5.0
        pinv.apply_info_changes({insert: {"taxes": []}}, None)
        assert pinv.vat[19.0] == 0 and pinv.total_vat == 0

    def test_delete(self, pinv):
        insert, delete = self._diff_symbols()
        pinv.supplier, pinv.no, pinv.order_id, pinv.date, pinv.shipping = "S", "N", "O", "D", 1.0
        pinv.vat[19.0], pinv.totals[19.0], pinv.gross_total = 19.0, 100.0, 119.0
        pinv.items = [SupplierItem(pinv)]
        pinv.apply_info_changes({delete: {"supplier": 1, "taxes": 1, "items": 1, "total": 1, "grand_total": 1,
                                          "bill_no": 1, "order_id": 1, "posting_date": 1, "shipping": 1}},
                                {"items": [{"description": "aus Modell", "qty": 1}]})
        assert pinv.supplier is None and pinv.no is None and pinv.order_id is None and pinv.date is None
        assert pinv.vat[19.0] == 0 and pinv.totals[19.0] == 0 and pinv.gross_total == 0 and pinv.shipping == 0
        assert [i.description for i in pinv.items] == ["aus Modell"]

    def test_changed_values(self, pinv):
        diff = {"supplier": ["alt", "neu"], "taxes": [[{"rate": 19.0, "tax_amount": 1.0}], [{"rate": 19.0, "tax_amount": 38.0}]],
                "items": None, "total": [1, 200.0], "grand_total": [1, 238.0], "bill_no": ["a", "b"],
                "order_id": ["x", "y"], "posting_date": ["d1", "d2"], "shipping": [0, 4.0]}
        model = {"items": [{"description": "I1", "qty": 1, "uom": "Stk", "rate": 200.0, "amount": 200.0}],
                 "taxes": [{"rate": 19.0, "tax_amount": 38.0}]}
        pinv.apply_info_changes(diff, model)
        assert pinv.supplier == "neu" and pinv.vat[19.0] == 38.0 and pinv.total_vat == 38.0
        assert [i.description for i in pinv.items] == ["I1"]
        assert (pinv.totals[19.0], pinv.gross_total, pinv.no, pinv.order_id, pinv.date, pinv.shipping) == \
            (200.0, 238.0, "b", "y", "d2", 4.0)

    def test_changed_taxes_from_model(self, pinv):
        pinv.apply_info_changes({"taxes": {0: {"tax_amount": [1, 2]}}}, {"taxes": [{"rate": 19.0, "tax_amount": 2.0}]})
        assert pinv.vat[19.0] == 2.0

    def test_apply_final_data(self, pinv, capsys):
        pinv.no, pinv.supplier = "alt", "S"
        pinv.apply_final_data({"bill_no": " neu ", "order_id": "", "posting_date": None, "supplier": "S", "other": 1})
        assert pinv.no == "neu" and pinv.order_id is None and pinv.date is None and pinv.supplier == "S"
        out = capsys.readouterr().out
        assert "Übernehme bill_no = 'neu'" in out and "supplier" not in out

    def test_merge_items(self, pinv, capsys):
        items1 = [{"item_code": "A", "description": "Modul A"}, {"item_code": "B", "description": "Kabel"},
                  {"description": "nur Text Modul"}]
        items2 = [{"item_code": "A", "description": "Modul A lang"}, {"item_code": "C", "description": "Neu"},
                  {"item_code": "D", "description": "nur Text Modul D"}]
        merged = pinv.merge_items(items1, items2)
        by_code = {i.get("item_code"): i for i in merged if i.get("item_code")}
        assert by_code["A"]["description"] == "Modul A lang"
        assert set(by_code) == {"A", "B", "C", "D"}
        assert sum(1 for i in merged if i.get("item_code") == "D") == 2   # Textposition dem Artikel D zugeordnet
        assert [i for i in merged if "item_code" not in i] == [{"description": "nur Text Modul"}]
        assert pinv.merge_items([], items2) == items2

    def test_edit_data_model_manually(self, pinv, monkeypatch):
        import jsoneditor
        insert, _ = self._diff_symbols()
        monkeypatch.setattr(pinv, "apply_info_changes", lambda diff, model: setattr(pinv, "seen", (diff, model)))
        monkeypatch.setattr(purchase_invoice.jsondiff, "diff", lambda a, b, syntax: {insert: {"bill_no": "X"}})
        monkeypatch.setattr(jsoneditor, "editjson", lambda data, callback: callback(dict(data, bill_no="X")))
        monkeypatch.setattr(purchase_invoice.utils, "running_linux", lambda: False)
        model = pinv.edit_data_model_manually({"supplier": "S"}, "/tmp/x.pdf")
        assert model == {"supplier": "S", "bill_no": "X"}
        assert pinv.seen == ({insert: {"bill_no": "X"}}, model)


class TestGenericParsing:
    def test_parse_generic_is_test(self, pinv):
        assert pinv.parse_generic(F.GENERIC_INVOICE_LINES, is_test=True) is pinv
        assert pinv.parser == "generic" and pinv.extract_items is False
        assert pinv.supplier == "Muster Solartechnik GmbH"
        assert pinv.no == "2026-0815" and pinv.date == "2026-09-03"
        assert pinv.vat[19.0] == 19.0 and pinv.totals[19.0] == 100.0 and pinv.shipping == 0.0
        assert pinv.total == 100.0 and pinv.gross_total == 119.0

    def test_parse_generic_without_lines(self, pinv):
        pinv.supplier = "Vorgabe"
        pinv.parse_generic([], is_test=True)
        assert pinv.supplier == "Vorgabe" and pinv.no == "" and pinv.vat[19.0] == ""

    def test_parse_generic_cli_overrides(self, pinv, fake_api):
        pinv.cli_overrides = {"betrag": 238.0, "mwst": 38.0, "lieferant": "CLI GmbH", "rechnungsnr": "CLI-1",
                              "datum": "01.02.2026", "konto": "4985", "selbst_bezahlt": True}
        assert pinv.parse_generic(F.GENERIC_INVOICE_LINES) is pinv
        assert pinv.supplier == "CLI GmbH" and pinv.no == "CLI-1" and pinv.date == "2026-02-01"
        assert pinv.vat[19.0] == 38.0 and pinv.totals[19.0] == 200.0 and pinv.gross_total == 238.0
        assert pinv.paid_by_submitter is True
        assert pinv.e_items[0]["expense_account"] == "4985 - Werkzeuge und Kleingeräte - SoMiKo"

    def test_parse_generic_gui_path_is_detected(self, pinv, fake_api):
        with pytest.raises(GuiCalled):
            pinv.parse_generic(F.GENERIC_INVOICE_LINES)

    def test_complete_data_by_cli_prompts_for_vat(self, pinv, fake_api, monkeypatch):
        answers = iter(["Prompt GmbH", "P-1", "05.06.2026", "19,00", "119,00", "0"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
        pinv.cli_overrides = {}
        pinv.no = None
        pinv.vat[19.0] = ""        # Zustand wie nach parse_generic ohne erkannte Beträge
        pinv.totals[19.0] = ""
        assert pinv.complete_data_by_cli() is True
        assert pinv.vat[19.0] == 19.0 and pinv.totals[19.0] == 100.0
        assert pinv.supplier == "Prompt GmbH" and pinv.no == "P-1" and pinv.date == "2026-06-05"
        assert pinv.gross_total == 119.0
        assert pinv.e_items[0]["expense_account"] == pinv.company.leaf_accounts_for_credit[0]["name"]

    def test_complete_data_by_cli_prompts_with_known_amount(self, pinv, fake_api, monkeypatch):
        prompts = []

        def fake_input(prompt=""):
            prompts.append(prompt)
            return {"Lieferant: ": "Prompt GmbH", "Rechnungsnr.: ": "P-1", "Datum (TT.MM.JJJJ): ": "05.06.2026",
                    "Buchungskonto (Nummer oder Text): ": "0"}.get(prompt, "")
        monkeypatch.setattr("builtins.input", fake_input)
        pinv.cli_overrides = {}
        pinv.no = None
        pinv.totals[19.0] = ""     # Nettobetrag unbekannt, MWSt 0.0 gilt als bekannt
        assert pinv.complete_data_by_cli(amount=119.0) is True
        assert pinv.supplier == "Prompt GmbH" and pinv.no == "P-1" and pinv.date == "2026-06-05"
        assert "MWSt (19.0%): " not in prompts
        assert "Brutto [119.0]: " in prompts
        assert pinv.totals[19.0] == 119.0 and pinv.gross_total == 119.0
        assert pinv.e_items[0]["expense_account"] == pinv.company.leaf_accounts_for_credit[0]["name"]

    def test_complete_data_by_cli_gross_without_vat(self, pinv, fake_api):
        pinv.cli_overrides = {"betrag": 50.0, "lieferant": "L", "rechnungsnr": "N", "datum": "01.01.2026", "konto": "4210"}
        pinv.no = None
        assert pinv.complete_data_by_cli(account="4210 - Miete und Nebenkosten - SoMiKo") is True
        assert pinv.vat[19.0] == 0.0 and pinv.totals[19.0] == 50.0
        assert pinv.e_items[0]["expense_account"] == "4210 - Miete und Nebenkosten - SoMiKo"

    def test_complete_missing_data_without_check_dup(self, pinv, fake_api):
        pinv.no = None
        assert pinv.complete_missing_data(check_dup=False) is pinv
        assert (pinv.supplier, pinv.date, pinv.no) == ("???", "1970-01-01", "???")
        assert pinv.vat[19.0] == 0.0 and pinv.gross_total == 0.0

    def test_complete_missing_data_complete(self, pinv, fake_api):
        pinv.supplier, pinv.date, pinv.no = "S", "2026-01-01", "1"
        pinv.totals[19.0], pinv.vat[19.0], pinv.gross_total = 100.0, 19.0, 119.0
        assert pinv.complete_missing_data(account="4210 - Miete und Nebenkosten - SoMiKo") is pinv
        assert pinv.e_items[0]["expense_account"] == "4210 - Miete und Nebenkosten - SoMiKo"
        assert fake_api.calls == []

    def test_complete_missing_data_is_test_returns_silently(self, pinv, fake_api, capsys):
        pinv.no = None
        assert pinv.complete_missing_data(is_test=True) is pinv
        assert "nicht erkannt" not in capsys.readouterr().out

    def test_complete_missing_data_reports_and_completes(self, pinv, fake_api, capsys):
        pinv.no = None
        pinv.cli_overrides = {"lieferant": "L", "rechnungsnr": "N", "datum": "01.01.2026", "betrag": 119.0,
                              "mwst": 19.0, "konto": "4210"}
        assert pinv.complete_missing_data() is pinv
        out = capsys.readouterr().out
        for fehlt in ("Lieferant", "Datum", "Rechnungsnr.", "MWSt", "Nettobetrag", "Bruttobetrag"):
            assert fehlt + " nicht erkannt" in out
        assert "Rückfall auf manuelle Eingabe" in out
        assert (pinv.supplier, pinv.no, pinv.date, pinv.gross_total) == ("L", "N", "2026-01-01", 119.0)


class TestParseInvoice:
    def test_generic_pdf_is_test(self, pinv, generic_pdf, fake_api):
        result = pinv.parse_invoice(None, generic_pdf, is_test=True)
        assert result is pinv and pinv.parser == "generic"
        assert pinv.supplier == "Muster Solartechnik GmbH" and pinv.no == "2026-0815"
        assert pinv.date == "2026-09-03" and pinv.totals[19.0] == 100.0 and pinv.vat[19.0] == 19.0
        assert fake_api.calls == []

    def test_given_supplier_overrides_generic(self, pinv, generic_pdf):
        pinv.parse_invoice(None, generic_pdf, given_supplier="Vorgabe GmbH", is_test=True)
        assert pinv.supplier == "Vorgabe GmbH"

    def test_account_abbreviation_is_resolved(self, pinv, generic_pdf, fake_api):
        pinv.cli_overrides = {}
        pinv.parse_invoice(None, generic_pdf, account_abbrv="4985")
        assert pinv.e_items[0]["expense_account"] == "4985 - Werkzeuge und Kleingeräte - SoMiKo"

    def test_google_json_without_internal_parser(self, pinv, generic_pdf, monkeypatch):
        import purchase_invoice_google_parser as gp
        monkeypatch.setattr(gp, "find_date", lambda s: "2024-03-15")
        result = pinv.parse_invoice(F.google_invoice_json(), generic_pdf, given_supplier="Muster Solartechnik GmbH",
                                    is_test=True)
        assert result is pinv
        assert pinv.no == "RE2024-77" and pinv.order_id == "BEST-1"
        assert pinv.gross_total == 1190.0 and pinv.totals[19.0] == 1000.0 and pinv.vat[19.0] == 190.0
        assert pinv.date == "2024-03-15"

    def test_solarwatt_uses_generic_parser_headless(self, pinv, tmp_path, fake_api):
        pdf = F.write_pdf(tmp_path / "sw.pdf", ["SOLARWATT GmbH", "Rechnungsnummer: SW-1", "Rechnungsdatum 01.02.2026",
                                                  "Netto 100,00", "MwSt 19,00", "Brutto 119,00"])
        assert pinv.parse_invoice(None, pdf, is_test=True) is pinv
        assert pinv.parser == "generic" and pinv.no == "SW-1"
        assert pinv.supplier == "Solarwatt GmbH"          # konfigurierter Lieferantenname
        assert pinv.totals[19.0] == 100.0 and pinv.date == "2026-02-01"
        assert fake_api.calls == []


class TestReadPdfAndTransfer:
    def test_read_pdf_generic(self, pinv, generic_pdf, fake_api):
        pinv.cli_overrides = {"konto": "4210"}
        assert pinv.read_pdf(None, generic_pdf) is pinv
        assert pinv.infiles == [generic_pdf]
        assert pinv.e_items[0]["expense_account"] == "4210 - Miete und Nebenkosten - SoMiKo"
        assert pinv.taxes[0]["tax_amount"] == 19.0

    def test_read_pdf_duplicate(self, pinv, generic_pdf, fake_api, gui):
        fake_api.add("Purchase Invoice", bill_no="2026-0815", status="Unpaid")
        gui.answers["msgbox"] = None
        pinv.cli_overrides = {"konto": "4210"}
        # parse_generic erkennt das Duplikat bereits selbst
        assert pinv.read_pdf(None, generic_pdf) is pinv
        assert pinv.is_duplicate is True

    def test_read_pdf_aggregate_item(self, somiko, generic_pdf, fake_api):
        p = F.make_purchase_invoice(somiko, True, aggregate_item_code=settings.AGGREGATE_ITEMS["Elektro-Komponenten"])
        p.cli_overrides = {}
        assert p.read_pdf(None, generic_pdf, check_dup=False) is p
        assert p.e_items == [{"item_code": "000.100.302", "qty": 1.0, "rate": 100.0, "cost_center": "Haupt - SoMiKo"}]

    def test_read_and_transfer_chooses_aggregate_code(self, somiko, monkeypatch):
        seen = {}

        def fake_read_pdf(self, *a, **k):
            seen["code"] = self.aggregate_item_code
            return None
        monkeypatch.setattr(PurchaseInvoice, "read_pdf", fake_read_pdf)
        PurchaseInvoice.read_and_transfer(None, "x.pdf", True, pre_invoice={"nuruk": 1})
        assert seen["code"] == settings.AGGREGATE_ITEMS["default"]
        PurchaseInvoice.read_and_transfer(None, "x.pdf", True, pre_invoice={"nurelektromaterial": 1})
        assert seen["code"] == settings.AGGREGATE_ITEMS["Elektro-Komponenten"]
        PurchaseInvoice.read_and_transfer(None, "x.pdf", False, pre_invoice={"nuruk": 1})
        assert seen["code"] is None

    def test_read_and_transfer_reports_failure(self, somiko, monkeypatch, capsys):
        monkeypatch.setattr(PurchaseInvoice, "read_pdf", lambda self, *a, **k: None)
        assert PurchaseInvoice.read_and_transfer(None, "x.pdf", False) is None
        assert "Keine Einkaufsrechnung angelegt" in capsys.readouterr().out


class TestSendToErpnext:
    def _prepared(self, somiko, generic_pdf):
        p = F.make_purchase_invoice(somiko)
        p.cli_overrides = {"konto": "4210"}
        p.read_pdf(None, generic_pdf)
        return p

    def test_silent_creates_draft(self, somiko, generic_pdf, fake_api, capsys):
        p = self._prepared(somiko, generic_pdf)
        assert p.send_to_erpnext(silent=True) is p
        doc = fake_api.get_doc("Purchase Invoice", p.doc["name"])
        assert doc["docstatus"] == 0 and doc["grand_total"] == 119.0 and doc["total"] == 100.0
        assert doc["supplier"] == "Muster Solartechnik GmbH" and doc["bill_no"] == "2026-0815"
        assert doc["supplier_invoice"] == "/private/files/rechnung.pdf"
        assert fake_api.get_doc("Supplier", "Muster Solartechnik GmbH")
        assert somiko.purchase_invoices["Muster Solartechnik GmbH"][-1]["name"] == doc["name"]
        assert p.outstanding == 119.0 and p.reference == "2026-0815"
        assert "Keine Projekt-Lagerhaltung" in capsys.readouterr().out

    def test_insert_failure(self, somiko, generic_pdf, fake_api, monkeypatch):
        p = self._prepared(somiko, generic_pdf)
        monkeypatch.setattr(fake_api, "insert", lambda d: (_ for _ in ()).throw(RuntimeError("nein")))
        assert p.send_to_erpnext(silent=True) is None

    def test_later_booking(self, somiko, generic_pdf, fake_api, gui):
        p = self._prepared(somiko, generic_pdf)
        gui.answers["buttonbox"] = "Später buchen"
        assert p.send_to_erpnext() is p
        assert fake_api.get_doc("Purchase Invoice", p.doc["name"])["docstatus"] == 0
        msg, title, choices = gui.calls[-1][1]
        assert choices == ["Sofort buchen", "Später buchen"] and "Entwurf" in msg and title == "Rechnung 2026-0815"

    def test_immediate_booking_with_bank_transaction(self, somiko, generic_pdf, fake_api, gui):
        bacc = F.make_bank_account(fake_api, somiko)
        fake_api.add("Bank Transaction", **F.bank_transaction_doc(bacc.name, withdrawal=119.0,
                                                                  description="Rechnung 2026-0815 Muster"))
        p = self._prepared(somiko, generic_pdf)
        gui.answers["buttonbox"] = "Sofort buchen und zahlen"
        p.send_to_erpnext()
        assert gui.calls[-1][1][2][0] == "Sofort buchen und zahlen"
        assert "Zugehörige Bank-Transaktion gefunden" in gui.calls[-1][1][0]
        assert fake_api.get_doc("Purchase Invoice", p.doc["name"])["docstatus"] == 1
        pe = fake_api.get_doc("Payment Entry", fake_api.get_list("Payment Entry")[0]["name"])
        assert pe["docstatus"] == 1 and pe["paid_amount"] == 119.0
        assert fake_api.get_list("Bank Transaction", fields=["status"])[0]["status"] == "Reconciled"

    def test_immediate_booking_with_advance_payment(self, somiko, generic_pdf, fake_api, gui):
        fake_api.add("Payment Entry", company=somiko.name, party="Muster Solartechnik GmbH", docstatus=1,
                     unallocated_amount=119.0, paid_amount=119.0, remarks="Anzahlung", payment_type="Pay")
        p = self._prepared(somiko, generic_pdf)
        gui.answers["buttonbox"] = "Sofort buchen und zahlen"
        p.send_to_erpnext()
        assert "Zugehörige Anzahlung gefunden" in gui.calls[-1][1][0]
        doc = fake_api.get_doc("Purchase Invoice", p.doc["name"])
        assert doc["docstatus"] == 1
        assert doc["advances"][0]["allocated_amount"] == 119.0

    def test_stock_generic_asks_for_manual_items(self, somiko, generic_pdf, fake_api, gui):
        p = F.make_purchase_invoice(somiko, True)
        p.cli_overrides = {"konto": "4210"}
        p.read_pdf(None, generic_pdf, check_dup=False)
        p.update_stock = True    # read_pdf hat die Standardposition zugewiesen und update_stock zurückgesetzt
        gui.answers["msgbox"] = None
        assert p.send_to_erpnext() is p
        assert "Bitte Artikel in ERPNext manuell eintragen" in gui.calls[-1][1][0]
