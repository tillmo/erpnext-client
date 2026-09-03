"""Integration tests across several modules - offline against the FakeFrappeClient.

These tests run through the client's workflows end-to-end:
PDF -> purchase invoice, bank statement -> bank transactions -> assignment -> posting,
PreRechnung with Google JSON -> stock invoice with item assignment.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from support import factories as F
from support.deps import skip_module_without_pdftotext
from support.fakes import FakeFrappeClient
from support.stubs import EasyguiStub, UserSettings

skip_module_without_pdftotext()

import bank  # noqa: E402
import menu  # noqa: E402
import prerechnung  # noqa: E402
import purchase_invoice_google_parser as gp  # noqa: E402
import utils  # noqa: E402
from api import Api  # noqa: E402
from company import Company  # noqa: E402
from purchase_invoice import PurchaseInvoice  # noqa: E402


@pytest.fixture
def erp(fake_api: FakeFrappeClient, user_settings: UserSettings) -> FakeFrappeClient:
    """An 'instance' with company, accounts and bank account, loaded as at program start."""
    F.seed_company_data(fake_api)
    fake_api.add("Bank Account", **F.bank_account_doc())
    user_settings["-company-"] = F.COMPANY
    menu.initial_loads()
    comp = Company.get_company(F.COMPANY)
    # cost_center etc. are not included by init_companies (get_list only returns name), see test_company
    comp.cost_center = "Haupt - SoMiKo"
    comp.payable_account = F.company_doc()["default_payable_account"]
    comp.receivable_account = F.company_doc()["default_receivable_account"]
    return fake_api


class TestInvoicePipeline:
    def test_pdf_to_draft_invoice_and_duplicate_detection(self, erp: FakeFrappeClient, tmp_path: Path,
                                                          gui: EasyguiStub, capsys: pytest.CaptureFixture[str]) -> None:
        pdf = F.write_generic_invoice_pdf(tmp_path / "r.pdf")
        gui.answers["buttonbox"] = "Später buchen"
        pinv = PurchaseInvoice.read_and_transfer(None, str(pdf), False, cli_overrides={"konto": "4210"})
        assert pinv and not pinv.is_duplicate
        doc = erp.get_doc("Purchase Invoice", pinv.doc["name"])
        assert (doc["supplier"], doc["bill_no"], doc["posting_date"]) == ("Muster Solartechnik GmbH", "2026-0815", "2026-09-03")
        assert (doc["total"], doc["total_taxes_and_charges"], doc["grand_total"]) == (100.0, 19.0, 119.0)
        assert doc["items"][0]["expense_account"] == "4210 - Miete und Nebenkosten - SoMiKo"
        assert doc["taxes"][0]["account_head"] == F.TAXES_SOMIKO[19.0]
        assert doc["supplier_invoice"] == "/private/files/r.pdf" and erp.files[doc["supplier_invoice"]].startswith(b"%PDF")
        assert erp.get_doc("Supplier", "Muster Solartechnik GmbH")["supplier_group"] == "Lieferant"
        # second run with the same invoice: duplicate, PDF is attached, no second invoice
        gui.answers["msgbox"] = None
        dup = PurchaseInvoice.read_and_transfer(None, str(pdf), False, cli_overrides={"konto": "4210"})
        assert dup.is_duplicate and dup.doc["name"] == doc["name"]
        assert len(erp.get_list("Purchase Invoice")) == 1
        # the duplicate attaches the PDF exactly once to the existing invoice
        assert len([a for a in erp.attachments if a[1] == doc["name"]]) == 2
        assert len(erp.get_list("Supplier")) == 1

    def test_duplicate_attaches_pdf_once(self, erp: FakeFrappeClient, tmp_path: Path, gui: EasyguiStub) -> None:
        pdf = F.write_generic_invoice_pdf(tmp_path / "r.pdf")
        gui.answers["buttonbox"] = "Später buchen"
        gui.answers["msgbox"] = None
        PurchaseInvoice.read_and_transfer(None, str(pdf), False, cli_overrides={"konto": "4210"})
        PurchaseInvoice.read_and_transfer(None, str(pdf), False, cli_overrides={"konto": "4210"})
        assert len(erp.attachments) == 2

    def test_pdf_to_booked_and_paid_invoice(self, erp: FakeFrappeClient, tmp_path: Path, gui: EasyguiStub) -> None:
        pdf = F.write_generic_invoice_pdf(tmp_path / "r.pdf")
        bacc = bank.BankAccount.baccounts_by_name["Sparkasse Bremen - SoMiKo"]
        erp.add("Bank Transaction", **F.bank_transaction_doc(bacc.name, withdrawal=119.0,
                                                             description="Muster Solartechnik Rechnung 2026-0815"))
        gui.answers["buttonbox"] = "Sofort buchen und zahlen"
        pinv = PurchaseInvoice.read_and_transfer(None, str(pdf), False, cli_overrides={"konto": "4210"})
        doc = erp.get_doc("Purchase Invoice", pinv.doc["name"])
        assert doc["docstatus"] == 1
        pe = erp.get_doc("Payment Entry", erp.get_list("Payment Entry")[0]["name"])
        assert pe["docstatus"] == 1 and pe["references"][0]["reference_name"] == doc["name"]
        bt = erp.get_list("Bank Transaction", fields=["status", "unallocated_amount", "payment_entries"])[0]
        assert bt["status"] == "Reconciled" and bt["unallocated_amount"] == 0
        assert bt["payment_entries"][0]["payment_entry"] == pe["name"]
        # afterwards the client sees no more open documents
        comp = Company.get_company(F.COMPANY)
        assert comp.open_bank_transactions() == [] and comp.unbooked_payment_entries() == []


class TestBankPipeline:
    def test_statement_to_journal_entries(self, erp: FakeFrappeClient, tmp_path: Path, gui: EasyguiStub,
                                          user_settings: UserSettings, capsys: pytest.CaptureFixture[str]) -> None:
        comp = Company.get_company(F.COMPANY)
        rows = [{"date": "15.08.26", "purpose": "Miete August", "partner": "Vermieter", "amount": "-500,00"},
                {"date": "16.08.26", "purpose": "Spende", "partner": "Foerderer", "amount": "100,00"}]
        fn = F.write_sparkasse_csv(tmp_path / "k.csv", rows)
        b = bank.BankStatement.process_file(fn)
        assert len(b.transactions) == 2
        assert len(comp.open_bank_transactions()) == 2

        def choose(msg: str, title: str, options: list[str]) -> str:
            if "Miete" in msg:
                return "4210 - Miete und Nebenkosten - SoMiKo"
            return "8401 - Selbstbauanlagen 19% - SoMiKo"
        gui.answers["choicebox"] = choose
        comp.reconcile_all()
        assert comp.open_bank_transactions() == []
        jes = [erp.get_doc("Journal Entry", j["name"]) for j in comp.open_journal_entries()]
        assert len(jes) == 2
        by_remark = {j["user_remark"]: j for j in jes}
        miete = by_remark["Miete August Vermieter"]
        assert miete["accounts"][0]["account"] == "Bank - SoMiKo" and miete["accounts"][0]["credit"] == 500.0
        assert miete["accounts"][1]["account"] == "4210 - Miete und Nebenkosten - SoMiKo"
        spende = by_remark["Spende Foerderer"]
        assert spende["accounts"][0]["debit"] == 100.0
        # submitting via the menu path 'Buchungssätze' -> submit_entry
        for j in jes:
            bank.BankTransaction.submit_entry(j["name"])
        assert comp.open_journal_entries() == []
        assert all(bt["docstatus"] == 1 for bt in erp.get_list("Bank Transaction", fields=["docstatus"]))
        assert b.baccount.balance == pytest.approx(-400.0)
        # ledger view: the bank account appears in comp.journal with the contra account
        assert {j["account"] for j in comp.journal} == {"4210 - Miete und Nebenkosten - SoMiKo",
                                                          "8401 - Selbstbauanlagen 19% - SoMiKo"}

    def test_statement_reimport_is_idempotent(self, erp: FakeFrappeClient, tmp_path: Path) -> None:
        rows = [{"date": "15.08.26", "purpose": "Miete", "partner": "V", "amount": "-500,00"}]
        fn = F.write_sparkasse_csv(tmp_path / "k.csv", rows)
        bank.BankStatement.process_file(fn)
        b = bank.BankStatement.process_file(fn)
        assert b.transactions == [] and len(erp.get_list("Bank Transaction")) == 1


class TestPreInvoicePipeline:
    def test_pre_invoice_with_google_json_to_stock_invoice(self, erp: FakeFrappeClient, tmp_path: Path,
                                                           gui: EasyguiStub, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(utils, "evince", lambda f: None)
        monkeypatch.setattr(gp, "find_date", lambda s: utils.convert_date4(s) if s else None)
        comp = Company.get_company(F.COMPANY)
        pdf = F.write_generic_invoice_pdf(tmp_path / "pre.pdf")
        erp.add_file("/private/files/pre.pdf", open(pdf, "rb").read())
        erp.add("Project", name="PROJ-0001", project_type="Balkonmodule", project_name="Balkon", status="Open")
        modul = {"name": "010.100.001", "item_code": "010.100.001", "item_name": "Solarmodul 400 Wp",
                 "item_group": "Solarmodul", "description": "Modul", "supplier_items": [],
                 "expense_account": "4996 - Herstellungskosten - SoMiKo"}
        erp.add("Item", **{k: v for k, v in modul.items() if k != "expense_account"})
        Api.items_by_code = {"010.100.001": modul}
        Api.item_code_translation = defaultdict(dict, {"Muster Solartechnik GmbH": {"M1": "010.100.001"}})
        items = [{"description": "Solarmodul 400", "code": "M1", "qty": "2 Stk", "rate": "100,00", "amount": "200,00"}]
        j = F.google_invoice_json(total="238,00", tax="38,00", net="200,00", items=items, bill_no="G-1")
        name = erp.add("PreRechnung", company=comp.name, pdf="/private/files/pre.pdf", lager=True,
                       buchungskonto="Herstellungskosten", selbst_bezahlt=False, lieferant="Muster Solartechnik GmbH",
                       processed=True, eingepflegt=False, typ="Rechnung", datum="2026-09-03", chance="PROJ-0001",
                       json=json.dumps(j), nuruk=False, nurelektromaterial=False)
        inv = comp.get_open_pre_invoices(False)[0]
        assert inv["name"] == name
        gui.answers["buttonbox"] = "Später buchen"
        pinv = prerechnung.read_and_transfer(inv)
        doc = erp.get_doc("Purchase Invoice", pinv.doc["name"])
        assert doc["update_stock"] == 1 and doc["project"] == "PROJ-0001"
        assert doc["items"][0]["item_code"] == "010.100.001" and doc["items"][0]["qty"] == 2.0
        assert doc["grand_total"] == 238.0 and doc["bill_no"] == "G-1"
        assert erp.get_doc("PreRechnung", name)["purchase_invoice"] == doc["name"]
        assert comp.get_open_pre_invoices(False) == []
        # an item price was created for the stock item
        assert erp.get_list("Item Price", fields=["item_code", "price_list_rate"]) == \
            [{"item_code": "010.100.001", "price_list_rate": 100.0}]
        # the item name appears in the summary
        assert "Solarmodul 400 Wp" in pinv.summary()

    def test_pre_invoice_with_aggregate_item(self, erp: FakeFrappeClient, tmp_path: Path, gui: EasyguiStub,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(utils, "evince", lambda f: None)
        comp = Company.get_company(F.COMPANY)
        pdf = F.write_generic_invoice_pdf(tmp_path / "pre.pdf")
        erp.add_file("/private/files/pre.pdf", open(pdf, "rb").read())
        erp.add("Project", name="PROJ-0002", project_type="Solaranlagenmaterial", project_name="Mat", status="Open")
        name = erp.add("PreRechnung", company=comp.name, pdf="/private/files/pre.pdf", lager=True,
                       buchungskonto="Herstellungskosten", selbst_bezahlt=False, lieferant="Muster Solartechnik GmbH",
                       processed=True, eingepflegt=False, typ="Rechnung", datum="2026-09-03", chance="PROJ-0002",
                       json=None, nuruk=True, nurelektromaterial=False)
        gui.answers["msgbox"] = None     # "Bitte Artikel in ERPNext manuell eintragen" (generic parser + stock)
        pinv = prerechnung.read_and_transfer(erp.get_doc("PreRechnung", name), cli_overrides={})
        doc = erp.get_doc("Purchase Invoice", pinv.doc["name"])
        assert "manuell eintragen" in gui.calls[-1][1][0]
        assert doc["update_stock"] == 1
        assert doc["items"] and doc["items"][0]["item_code"] == "000.100.301"
        assert doc["items"][0]["qty"] == 1.0 and doc["items"][0]["rate"] == 100.0
        assert doc["grand_total"] == 119.0
