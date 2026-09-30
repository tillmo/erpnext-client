"""Tests for prerechnung.py: preprocessing, transfer into purchase invoices, CLI selection."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from support import factories as F
from support.deps import skip_module_without_pdftotext
from support.fakes import FakeFrappeClient
from support.stubs import EasyguiStub, UserSettings

skip_module_without_pdftotext()

import prerechnung  # noqa: E402
import purchase_invoice  # noqa: E402
import utils  # noqa: E402
from company import Company  # noqa: E402


@pytest.fixture(autouse=True)
def no_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utils, "evince", lambda f: None)


@pytest.fixture
def pre(somiko: Company, fake_api: FakeFrappeClient, tmp_path: Path) -> dict[str, Any]:
    """PreRechnung with an uploaded generic PDF in the fake."""
    pdf = F.write_generic_invoice_pdf(tmp_path / "pre.pdf")
    with open(pdf, "rb") as f:
        fake_api.add_file("/private/files/pre.pdf", f.read())
    name = fake_api.add("PreRechnung", company=somiko.name, pdf="/private/files/pre.pdf", lager=False,
                        buchungskonto="4210", selbst_bezahlt=False, lieferant="Muster Solartechnik GmbH",
                        processed=False, eingepflegt=False, typ="Rechnung", datum="2026-09-03", chance=None,
                        balkonmodule=False, nuruk=False, nurelektromaterial=False)
    return fake_api.get_doc("PreRechnung", name)


class TestToPay:
    def test_sorted_with_running_sum(self, fake_api: FakeFrappeClient) -> None:
        c = F.COMPANY
        fake_api.add("PreRechnung", company=c, vom_konto_überwiesen=False, zu_zahlen_am="2026-09-20", betrag=30.0,
                     lieferant="B", typ="Rechnung", datum="2026-09-01", kommentar="", auftragsnr="")
        fake_api.add("PreRechnung", company=c, vom_konto_überwiesen=False, zu_zahlen_am="2026-09-10", betrag=100.0,
                     lieferant="A", typ="Rechnung", datum="2026-09-01", kommentar="", auftragsnr="")
        fake_api.add("PreRechnung", company=c, vom_konto_überwiesen=True, zu_zahlen_am="2026-09-05", betrag=999.0,
                     lieferant="C", typ="Rechnung", datum="2026-09-01")
        fake_api.add("PreRechnung", company=c, vom_konto_überwiesen=False, zu_zahlen_am=None, betrag=999.0,
                     lieferant="D", typ="Rechnung", datum="2026-09-01")
        fake_api.add("PreRechnung", company="Andere", vom_konto_überwiesen=False, zu_zahlen_am="2026-09-01", betrag=5.0)
        prs = prerechnung.to_pay(c)
        assert [(p["lieferant"], p["summe"]) for p in prs] == [("A", 100.0), ("B", 130.0)]

    def test_empty(self, fake_api: FakeFrappeClient) -> None:
        assert prerechnung.to_pay(F.COMPANY) == []


class TestProcessInv:
    def test_local_parser_marks_processed(self, pre: dict[str, Any], fake_api: FakeFrappeClient,
                                          capsys: pytest.CaptureFixture[str]) -> None:
        prerechnung.process_inv(pre)
        stored = fake_api.get_doc("PreRechnung", pre["name"])
        assert stored["processed"] is True
        assert pre["doctype"] == "PreRechnung"
        assert "Error" not in capsys.readouterr().out

    def test_local_parser_extracts_amount(self, pre: dict[str, Any], fake_api: FakeFrappeClient) -> None:
        prerechnung.process_inv(pre)
        stored = fake_api.get_doc("PreRechnung", pre["name"])
        assert stored["betrag"] == 119.0
        assert "auftragsnr" not in stored          # the generic parser knows no order number

    def test_process_all_unprocessed(self, pre: dict[str, Any], fake_api: FakeFrappeClient, somiko: Company,
                                     monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        fake_api.add("PreRechnung", company=somiko.name, processed=True, pdf="/private/files/pre.pdf")
        seen = []
        monkeypatch.setattr(prerechnung, "process_inv", lambda pr: seen.append(pr["name"]))
        prerechnung.process(somiko.name)
        assert seen == [pre["name"]]
        assert "Prerechnungen vorprozessiert" in capsys.readouterr().out


class TestReadAndTransfer:
    def test_creates_purchase_invoice_and_links_pre_invoice(self, pre: dict[str, Any], fake_api: FakeFrappeClient,
                                                            somiko: Company, gui: EasyguiStub,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
        pre["processed"] = True
        gui.answers["buttonbox"] = "Später buchen"
        pinv = prerechnung.read_and_transfer(pre, cli_overrides={})
        assert pinv is not None and pinv.is_duplicate is False
        doc = fake_api.get_doc("Purchase Invoice", pinv.doc["name"])
        assert doc["grand_total"] == 119.0 and doc["supplier"] == "Muster Solartechnik GmbH"
        assert doc["bill_no"] == "2026-0815" and doc["update_stock"] == 0
        assert doc["items"][0]["expense_account"] == "4210 - Miete und Nebenkosten - SoMiKo"
        assert doc["supplier_invoice"].startswith("/private/files/")
        stored = fake_api.get_doc("PreRechnung", pre["name"])
        assert stored["eingepflegt"] is True and stored["purchase_invoice"] == doc["name"]
        assert "Lese ein {} /private/files/pre.pdf".format(pre["name"]) in capsys.readouterr().out
        # temporary file is gone
        assert not os.path.exists(pinv.infiles[0])

    def test_unprocessed_pre_invoice_is_processed_first(self, pre: dict[str, Any], fake_api: FakeFrappeClient,
                                                        gui: EasyguiStub, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = []
        monkeypatch.setattr(prerechnung, "process_inv", lambda pr: seen.append(pr["name"]))
        gui.answers["buttonbox"] = "Später buchen"
        prerechnung.read_and_transfer(pre, cli_overrides={})
        assert seen == [pre["name"]]

    def test_duplicate_does_not_relink(self, pre: dict[str, Any], fake_api: FakeFrappeClient, somiko: Company,
                                       gui: EasyguiStub) -> None:
        pre["processed"] = True
        pre["purchase_invoice"] = "EK 2026-99999"
        fake_api.add("Purchase Invoice", name="EK 2026-99999", bill_no="2026-0815", status="Unpaid", supplier="M")
        gui.answers["msgbox"] = None
        pinv = prerechnung.read_and_transfer(pre, cli_overrides={})
        assert pinv.is_duplicate is True
        assert fake_api.calls_of("update") == []

    def test_stock_invoice_with_generic_parser_falls_back_to_default_item(self, pre: dict[str, Any],
                                                                          fake_api: FakeFrappeClient, somiko: Company,
                                                                          gui: EasyguiStub,
                                                                          capsys: pytest.CaptureFixture[str]) -> None:
        import settings
        fake_api.add("Project", name="PROJ-0001", project_type="Balkonmodule", project_name="B")
        pre["processed"] = True
        pre["chance"] = "PROJ-0001"
        pre["buchungskonto"] = "Herstellungskosten"
        gui.answers["buttonbox"] = "Später buchen"
        pinv = prerechnung.read_and_transfer(pre, cli_overrides={})
        # the generic parser knows no positions: default item on production costs, no stock
        doc = fake_api.get_doc("Purchase Invoice", pinv.doc["name"])
        assert doc["update_stock"] == 0 and doc["project"] == "PROJ-0001"
        assert doc["items"][0]["item_code"] == settings.DEFAULT_ITEM_CODE
        assert doc["items"][0]["expense_account"] == settings.SOMIKO_ACCOUNTS[19.0]
        assert fake_api.get_list("Stock Entry") == []
        assert "Keine Projekt-Lagerhaltung für Projekt PROJ-0001" in capsys.readouterr().out

class TestCli:
    def test_named_pre_invoice_with_overrides(self, pre: dict[str, Any], fake_api: FakeFrappeClient, somiko: Company,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}
        monkeypatch.setattr(prerechnung, "read_and_transfer", lambda inv, cli_overrides=None: seen.update(inv=inv, ov=cli_overrides))
        prerechnung.cli_read_and_transfer(name=pre["name"], overrides={"konto": "4985", "lieferant": "Neu", "projekt": "P",
                                                                       "selbst_bezahlt": True, "betrag": 5.0})
        assert seen["inv"]["name"] == pre["name"]
        assert seen["inv"]["buchungskonto"] == "4985" and seen["inv"]["lieferant"] == "Neu"
        assert seen["inv"]["chance"] == "P" and seen["inv"]["selbst_bezahlt"] is True
        assert seen["ov"]["betrag"] == 5.0

    def test_unknown_name(self, fake_api: FakeFrappeClient, somiko: Company, capsys: pytest.CaptureFixture[str]) -> None:
        assert prerechnung.cli_read_and_transfer(name="PreR99999") is None
        assert "nicht gefunden" in capsys.readouterr().out

    def test_no_company(self, fake_api: FakeFrappeClient, user_settings: UserSettings,
                        capsys: pytest.CaptureFixture[str]) -> None:
        user_settings["-company-"] = "gibt es nicht"
        assert prerechnung.cli_read_and_transfer() is None
        assert "Kein Bereich gefunden" in capsys.readouterr().out

    def test_interactive_selection(self, pre: dict[str, Any], fake_api: FakeFrappeClient, somiko: Company,
                                   monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        fake_api.add("PreRechnung", company=somiko.name, eingepflegt=False, typ="Rechnung", datum="2026-09-05",
                     lieferant="Zweite GmbH", pdf="/private/files/pre.pdf", processed=True)
        seen: dict[str, Any] = {}
        monkeypatch.setattr(prerechnung, "read_and_transfer", lambda inv, cli_overrides=None: seen.update(inv=inv))
        monkeypatch.setattr("builtins.input", lambda prompt="": "1")
        prerechnung.cli_read_and_transfer()
        out = capsys.readouterr().out
        assert "Offene Prerechnungen:" in out and "Zweite GmbH" in out
        assert seen["inv"]["lieferant"] == "Muster Solartechnik GmbH"   # newest first, index 1 = older

    def test_interactive_cancel_and_invalid(self, pre: dict[str, Any], fake_api: FakeFrappeClient, somiko: Company,
                                            monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr("builtins.input", lambda prompt="": "")
        assert prerechnung.cli_read_and_transfer() is None
        monkeypatch.setattr("builtins.input", lambda prompt="": "99")
        assert prerechnung.cli_read_and_transfer() is None
        assert "Ungültige Auswahl" in capsys.readouterr().out

    def test_no_open_pre_invoices(self, fake_api: FakeFrappeClient, somiko: Company, capsys: pytest.CaptureFixture[str]) -> None:
        assert prerechnung.cli_read_and_transfer(advance=True) is None
        assert "Keine offenen Anzahlungsrechnungen gefunden" in capsys.readouterr().out


class TestReadAndTransferPdf:
    def test_wires_init_and_transfer(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import args
        import company
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF")
        seen: dict[str, Any] = {}
        monkeypatch.setattr(args, "init", lambda: seen.setdefault("init", True))
        monkeypatch.setattr(company.Company, "init_companies", classmethod(lambda cls: seen.setdefault("companies", True)))
        monkeypatch.setattr(purchase_invoice.PurchaseInvoice, "read_and_transfer",
                            classmethod(lambda cls, *a, **k: seen.update(args=a, kwargs=k) or "PINV"))
        assert prerechnung.read_and_transfer_pdf(str(pdf), True, account="4210", supplier="S", project="P") == "PINV"
        assert seen["init"] and seen["companies"]
        assert seen["args"] == (str(pdf), True)          # the client decides itself: e-invoice, Claude or text parser
        assert seen["kwargs"] == {"account_abbrv": "4210", "paid_by_submitter": False, "project": "P", "supplier": "S",
                                  "check_dup": True}
