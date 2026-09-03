"""Tests for lead.py and sales_invoice.py."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

import invoice  # noqa: F401  (import order, see conftest)
import lead
import sales_invoice
from api import Api
from company import Company
from settings import EBAY_ACCOUNT, LEAD_OWNERS, LEAD_DNC_FIELD
from support import factories as F
from support.fakes import FakeFrappeClient
from support.stubs import EasyguiStub, GuiCalled


class TestLeadHelpers:
    def test_is_change_into_not_contact(self) -> None:
        v = {"data": json.dumps({"changed": [["status", "Open", "Do Not Contact"]]})}
        assert lead.is_change_into_not_contact(v) is True
        assert lead.is_change_into_not_contact({"data": json.dumps({"changed": [["status", "Open", "Replied"]]})}) is False
        assert lead.is_change_into_not_contact({}) is False

    def test_format(self) -> None:
        assert lead.format({"creation": "2026-01-02 10:00:00.1234"})["creation"] == "2026-01-02"

    def test_show_open_leads_needs_gui(self, fake_api: FakeFrappeClient) -> None:
        fake_api.add("Lead", name="L1", status="Open", lead_name="A", creation="2026-01-02 10:00:00")
        with pytest.raises(GuiCalled):
            lead.show_open_leads()


@pytest.fixture
def leads(fake_api: FakeFrappeClient) -> FakeFrappeClient:
    for owner in LEAD_OWNERS:
        fake_api.add("User", email=owner.lower() + "@example.org", first_name=owner)
    fake_api.add("Lead", name="L-NEU", status="Open", lead_name="Neu", _assign=None, email_id="neu@example.org",
                 first_name="Neu", last_name="")
    fake_api.add("Lead", name="L-ZUGEWIESEN", status="Open", lead_name="Alt", _assign='["x"]')
    fake_api.add("Lead", name="L-NICHT", status="Open", lead_name="Nicht", _assign=None)
    fake_api.add("Lead", name="L-FLAG", status="Open", lead_name="Flag", _assign=None, **{LEAD_DNC_FIELD: 1})
    fake_api.communications["L-NEU"] = [{"content": "<p>Ich möchte <b>Solar</b></p>"}]
    fake_api.versions["L-NICHT"] = [{"data": json.dumps({"changed": [["status", "Open", "Do Not Contact"]]})}]
    return fake_api


class TestProcessOpenLeads:
    def test_assigns_owner_and_resets_not_contact(self, leads: FakeFrappeClient, gui: EasyguiStub,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
        gui.answers["choicebox"] = lambda msg, title, choices: LEAD_OWNERS[0]
        lead.process_open_leads()
        assert leads.assignments == [("Lead", "L-NEU", [LEAD_OWNERS[0].lower() + "@example.org"])]
        for name in ("L-NICHT", "L-FLAG"):      # history resp. flag: closed again without asking
            doc = leads.get_doc("Lead", name)
            assert doc["status"] == "Do Not Contact" and doc[LEAD_DNC_FIELD] == 1
        assert leads.get_doc("Lead", "L-ZUGEWIESEN")["status"] == "Open"
        assert len(gui.calls) == 1
        msg, title, choices = gui.calls[0][1]
        assert "Ich möchte Solar" in msg and choices == LEAD_OWNERS + ["kein Lead", "überspringen"]
        out = capsys.readouterr().out
        assert "nicht kontaktieren" in out and "Leads fertig bearbeitet" in out

    def test_kein_lead_and_skip(self, leads: FakeFrappeClient, gui: EasyguiStub) -> None:
        gui.answers["choicebox"] = "kein Lead"
        lead.process_open_leads()
        doc = leads.get_doc("Lead", "L-NEU")
        assert doc["status"] == "Do Not Contact" and doc[LEAD_DNC_FIELD] == 1
        assert leads.assignments == []

    def test_cancel_stops(self, leads: FakeFrappeClient, gui: EasyguiStub, capsys: pytest.CaptureFixture[str]) -> None:
        gui.answers["choicebox"] = None
        lead.process_open_leads()
        assert "Lead-Bearbeitung abgebrochen" in capsys.readouterr().out
        assert leads.get_doc("Lead", "L-NEU")["status"] == "Open"

    def test_skip(self, leads: FakeFrappeClient, gui: EasyguiStub) -> None:
        gui.answers["choicebox"] = "überspringen"
        lead.process_open_leads()
        assert leads.assignments == [] and leads.get_doc("Lead", "L-NEU")["status"] == "Open"

    def test_mark_not_contact(self, fake_api: FakeFrappeClient) -> None:
        fake_api.add("Lead", name="L-1", status="Open", lead_name="Eins")
        lead.mark_not_contact("L-1")
        doc = fake_api.get_doc("Lead", "L-1")
        assert doc["status"] == "Do Not Contact" and doc[LEAD_DNC_FIELD] == 1

    def test_cleanup_leads(self, fake_api: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        fake_api.add("Lead", name="L-BSS", status="Open", first_name="Bremer", last_name="SolidarStrom",
                     email_id="kunde@example.org")
        fake_api.add("Lead", name="L-OK", status="Open", first_name="Anna", last_name="B", email_id="a@example.org")
        lead.cleanup_leads()
        doc = fake_api.get_doc("Lead", "L-BSS")
        assert doc["first_name"] == "kunde@example.org" and doc["last_name"] == ""
        assert fake_api.get_doc("Lead", "L-OK")["first_name"] == "Anna"
        assert "L-BSS heißt nun kunde@example.org" in capsys.readouterr().out


class TestSalesInvoiceItems:
    def test_get_items_aggregates(self, fake_api: FakeFrappeClient) -> None:
        Api.items_by_code = {"A": {"item_code": "A", "item_name": "Neuer Name"}, "B": {"item_code": "B", "item_name": "B"}}
        fake_api.add("Sales Invoice", name="R-1", items=[{"item_code": "A", "qty": 2.0}, {"item_code": "B", "qty": 1}])
        fake_api.add("Sales Invoice", name="R-2", items=[{"item_code": "A", "qty": 1.5}])   # int() -> 1
        items = sales_invoice.get_items([{"name": "R-1"}, {"name": "R-2"}])
        assert sorted(items, key=lambda i: i["item_code"]) == [{"item_name": "Neuer Name", "item_code": "A", "qty": 3},
                                                              {"item_name": "B", "item_code": "B", "qty": 1}]

    def test_get_items_loads_disabled_items(self, fake_api: FakeFrappeClient) -> None:
        Api.items_by_code = {"A": {"item_code": "A", "item_name": "A"}}
        fake_api.add("Item", item_code="ALT", item_name="Alter Artikel", disabled=1)
        fake_api.add("Sales Invoice", name="R-1", items=[{"item_code": "ALT", "qty": 2}])
        assert sales_invoice.get_items([{"name": "R-1"}]) == [{"item_name": "Alter Artikel", "item_code": "ALT", "qty": 2}]


class TestGetSalesInvoices:
    def test_writes_csv_and_pdfs(self, fake_api: FakeFrappeClient, in_tmp_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
        fake_api.add("Print Format", name="Rechnung DE", doc_type="Sales Invoice")
        fake_api.add("Sales Invoice", name="R 2026-00001", company=F.COMPANY, posting_date="2026-04-10", status="Paid",
                     taxes_and_charges="Germany VAT 19% - SoMiKo", total_taxes_and_charges=19.0, total=100.0)
        fake_api.add("Sales Invoice", name="R 2026-00002", company=F.COMPANY, posting_date="2026-05-10", status="Paid",
                     taxes_and_charges="Germany VAT 0% - SoMiKo", total_taxes_and_charges=0.0, total=50.0)
        fake_api.add("Sales Invoice", name="R 2026-00003", company=F.COMPANY, posting_date="2026-05-11", status="Cancelled",
                     taxes_and_charges="Germany VAT 19% - SoMiKo", total_taxes_and_charges=9.0, total=9.0)
        fake_api.add("Sales Invoice", name="R 2026-00004", company=F.COMPANY, posting_date="2026-07-01", status="Paid",
                     taxes_and_charges="Germany VAT 19% - SoMiKo", total_taxes_and_charges=1.0, total=1.0)
        d = sales_invoice.get_sales_invoices(F.COMPANY, "2026-02")
        assert d == "EK-Rechnungen-Bremer_SolidarStrom-2026-02"
        rows = list(csv.reader(open(in_tmp_cwd / d / "EK-Rechnungen-Bremer_SolidarStrom-2026-02.csv"), delimiter=";"))
        assert rows == [["Datum", "Rechnungsnr.", "Steuersatz", "Netto", "USt."],
                        ["2026-04-10", "R_2026-00001", "19", "100,0", "19,0"],
                        ["2026-05-10", "R_2026-00002", "0", "50,0", "0,0"],
                        ["Summe", "", "19,0", "150,0"]]
        assert sorted(f for f in os.listdir(in_tmp_cwd / d) if f.endswith(".pdf")) == ["R_2026-00001.pdf", "R_2026-00002.pdf"]
        assert fake_api.calls_of("get_pdf")[0][1] == ("Sales Invoice", "R 2026-00001", "Rechnung DE")

    def test_tax_rate_filter(self, fake_api: FakeFrappeClient, in_tmp_cwd: Path) -> None:
        fake_api.add("Print Format", name="Rechnung DE", doc_type="Sales Invoice")
        fake_api.add("Sales Invoice", name="R 2026-00001", company=F.COMPANY, posting_date="2026-04-10", status="Paid",
                     taxes_and_charges="Germany VAT 19% - SoMiKo", total_taxes_and_charges=19.0, total=100.0)
        fake_api.add("Sales Invoice", name="R 2026-00002", company=F.COMPANY, posting_date="2026-05-10", status="Paid",
                     taxes_and_charges="Germany VAT 0% - SoMiKo", total_taxes_and_charges=0.0, total=50.0)
        d = sales_invoice.get_sales_invoices(F.COMPANY, "2026-02", tax_rates=[0])
        rows = list(csv.reader(open(in_tmp_cwd / d / "EK-Rechnungen-Bremer_SolidarStrom-2026-02.csv"), delimiter=";"))
        assert [r[1] for r in rows[1:-1]] == ["R_2026-00002"]


class TestEbaySales:
    def _seed(self, fake_api: FakeFrappeClient, comp: Company) -> None:
        fake_api.add("Sales Invoice", name="R-EBAY", company=comp, outstanding_amount=50.0, custom_ebay=1, status="Unpaid",
                     total=42.0, posting_date="2026-03-01", grand_total=50.0, customer="Käufer")
        fake_api.add("Sales Invoice", name="R-KLEIN", company=comp, outstanding_amount=1.5, custom_ebay=1, status="Unpaid",
                     total=1.0, posting_date="2026-03-01", grand_total=1.5, customer="K")
        fake_api.add("Sales Invoice", name="R-NORMAL", company=comp, outstanding_amount=50.0, custom_ebay=0, status="Unpaid",
                     total=42.0, posting_date="2026-03-01", grand_total=50.0, customer="K")

    def test_creates_payments(self, somiko: Company, fake_api: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        self._seed(fake_api, somiko.name)
        sales_invoice.ebay_sales(somiko.name)
        pes = fake_api.get_list("Payment Entry", fields=["paid_to", "paid_amount", "docstatus", "references"])
        assert len(pes) == 1
        assert pes[0]["paid_to"] == EBAY_ACCOUNT and pes[0]["paid_amount"] == 50.0 and pes[0]["docstatus"] == 0
        assert pes[0]["references"][0]["reference_name"] == "R-EBAY"
        assert "Bitte noch buchen" in capsys.readouterr().out

    def test_submit(self, somiko: Company, fake_api: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        self._seed(fake_api, somiko.name)
        sales_invoice.ebay_sales(somiko.name, submit=True)
        assert fake_api.get_list("Payment Entry", fields=["docstatus"]) == [{"docstatus": 1}]
        assert "Bitte noch buchen" not in capsys.readouterr().out
