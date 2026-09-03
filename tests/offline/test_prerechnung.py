"""Tests for prerechnung.py: preprocessing, transfer into purchase invoices, CLI selection."""
from __future__ import annotations

import json
import os
import types
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NoReturn

import pytest
from jsonschema import validate, ValidationError

from support import factories as F
from support.deps import skip_module_without_pdftotext
from support.fakes import FakeFrappeClient
from support.stubs import EasyguiStub, UserSettings

skip_module_without_pdftotext()

import prerechnung  # noqa: E402
import purchase_invoice  # noqa: E402
import purchase_invoice_google_parser as gp  # noqa: E402
import utils  # noqa: E402
from api import Api  # noqa: E402
from company import Company  # noqa: E402


@pytest.fixture(autouse=True)
def no_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utils, "evince", lambda f: None)
    monkeypatch.setattr(gp, "find_date", lambda s: utils.convert_date4(s) if s else None)


@pytest.fixture
def pre(somiko: Company, fake_api: FakeFrappeClient, tmp_path: Path) -> dict[str, Any]:
    """PreRechnung with an uploaded generic PDF in the fake."""
    pdf = F.write_generic_invoice_pdf(tmp_path / "pre.pdf")
    with open(pdf, "rb") as f:
        fake_api.add_file("/private/files/pre.pdf", f.read())
    name = fake_api.add("PreRechnung", company=somiko.name, pdf="/private/files/pre.pdf", lager=False,
                        buchungskonto="4210", selbst_bezahlt=False, lieferant="Muster Solartechnik GmbH",
                        processed=False, eingepflegt=False, typ="Rechnung", datum="2026-09-03", chance=None,
                        json=None, balkonmodule=False, nuruk=False, nurelektromaterial=False)
    return fake_api.get_doc("PreRechnung", name)


class TestSchema:
    def test_entities_schema(self) -> None:
        ok = {"total_amount": "1,00", "items": [{"item-description": "a", "item-amount": "1,00"}]}
        validate(ok, prerechnung.ENTITIES_DATA_SCHEMA)
        with pytest.raises(ValidationError):
            validate({"supplier": "x"}, prerechnung.ENTITIES_DATA_SCHEMA)
        with pytest.raises(ValidationError):
            validate({"total_amount": "1", "items": []}, prerechnung.ENTITIES_DATA_SCHEMA)


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

    def test_google_parser_path(self, pre: dict[str, Any], fake_api: FakeFrappeClient, user_settings: UserSettings,
                                monkeypatch: pytest.MonkeyPatch) -> None:
        user_settings["-google-credentials-"] = {"project_id": "p"}
        monkeypatch.setattr(prerechnung, "extract_invoice_info", lambda content: F.google_invoice_json())
        prerechnung.process_inv(pre)
        stored = fake_api.get_doc("PreRechnung", pre["name"])
        assert stored["processed"] is True
        assert json.loads(stored["json"])["entities"]
        assert stored["auftragsnr"] == "BEST-1"
        assert stored["betrag"] == "1.190,00 EUR"     # raw value from the JSON, not a number

    def test_google_parser_error_is_reported(self, pre: dict[str, Any], fake_api: FakeFrappeClient,
                                             user_settings: UserSettings, monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]) -> None:
        user_settings["-google-credentials-"] = {"project_id": "p"}

        def boom(content: bytes) -> NoReturn:
            raise RuntimeError("Quota")
        monkeypatch.setattr(prerechnung, "extract_invoice_info", boom)
        prerechnung.process_inv(pre)
        assert fake_api.get_doc("PreRechnung", pre["name"])["processed"] is False
        assert "Quota" in capsys.readouterr().out

    def test_process_all_unprocessed(self, pre: dict[str, Any], fake_api: FakeFrappeClient, somiko: Company,
                                     monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        fake_api.add("PreRechnung", company=somiko.name, processed=True, pdf="/private/files/pre.pdf")
        seen = []
        monkeypatch.setattr(prerechnung, "process_inv", lambda pr: seen.append(pr["name"]))
        prerechnung.process(somiko.name)
        assert seen == [pre["name"]]
        assert "Prerechnungen vorprozessiert" in capsys.readouterr().out


def _ns(**kw: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(**kw)


def _entity(type_: str, text: str, confidence: float = 0.9, props: Iterable[tuple[str, str, float]] = (),
            page: int = 0, start: int = 0) -> types.SimpleNamespace:
    return _ns(type_=type_, mention_text=text, confidence=confidence,
               normalized_value=_ns(text=""),
               text_anchor=_ns(content="", text_segments=[_ns(start_index=start)]),
               page_anchor=_ns(page_refs=[_ns(page=page)]),
               properties=[_ns(type_=t, confidence=c, normalized_value=_ns(text=""), text_anchor=_ns(content=""),
                               mention_text=v) for t, v, c in props])


class TestExtractInvoiceInfo:
    def test_entity_grouping(self, user_settings: UserSettings, monkeypatch: pytest.MonkeyPatch) -> None:
        user_settings["-google-credentials-"] = {"project_id": "proj"}
        user_settings["-invoice-processor-"] = "proc"
        entities = [
            _entity("supplier", "Muster GmbH", 0.95, start=10),
            _entity("supplier", "Rausch", 0.1, start=11),                 # too uncertain
            _entity("item", "Modul", 0.9, [("item-description", "Modul", 0.9), ("item-quantity", "2", 0.8),
                                           ("item-amount", "200,00", 0.1)], start=100),   # last property too uncertain
            _entity("item", "", 0.9, [("item-amount", "200,00", 0.9)], start=120),   # belongs to the first position
            _entity("item", "Kabel", 0.9, [("item-description", "Kabel", 0.9)], start=130),  # type repeated -> new position
            _entity("item", "", 0.9, [], start=131),                       # without properties -> ignored
            _entity("total_amount", "238,00 EUR", 0.9, start=200),
        ]
        captured = {}

        class Client:
            def __init__(self, client_options: Any = None) -> None:
                captured["endpoint"] = client_options.api_endpoint

            def process_document(self, request: Any) -> types.SimpleNamespace:
                captured["request"] = request
                return _ns(document=_ns(text="Volltext", entities=entities))
        monkeypatch.setattr(prerechnung.documentai, "DocumentProcessorServiceClient", Client)
        result = prerechnung.extract_invoice_info(b"%PDF")
        assert captured["endpoint"] == "eu-documentai.googleapis.com"
        assert captured["request"]["name"] == "projects/proj/locations/eu/processors/proc"
        assert captured["request"]["document"] == {"content": b"%PDF", "mime_type": "application/pdf"}
        assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == "google-credentials.json"
        assert result["document_text"] == "Volltext"
        types_ = [e["type"] for e in result["entities"]]
        assert types_ == ["supplier", "item", "total_amount"]
        item = result["entities"][1]
        assert sorted(p["type"] for p in item["properties"]) == ["item-amount", "item-description", "item-quantity"]
        assert item["value"] == "Modul" and item["line_number"] == 100
        # the second position ('Kabel') has only one property and is therefore discarded
        assert result["entities"][2]["value"] == "238,00 EUR"


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

    def test_google_json_stock_invoice(self, pre: dict[str, Any], fake_api: FakeFrappeClient, somiko: Company,
                                       gui: EasyguiStub) -> None:
        from collections import defaultdict
        fake_api.add("Project", name="PROJ-0001", project_type="Balkonmodule", project_name="B")
        modul = {"name": "010.100.001", "item_code": "010.100.001", "item_name": "Solarmodul 400 Wp",
                 "item_group": "Solarmodul", "description": "Modul", "supplier_items": [],
                 "expense_account": "4996 - Herstellungskosten - SoMiKo"}
        Api.items_by_code = {"010.100.001": modul}
        Api.item_code_translation = defaultdict(dict, {"Muster Solartechnik GmbH": {"M1": "010.100.001"}})
        items = [{"description": "Solarmodul 400", "code": "M1", "qty": "2 Stk", "rate": "100,00", "amount": "200,00"}]
        pre.update(processed=True, chance="PROJ-0001", buchungskonto="Herstellungskosten",
                   json=json.dumps(F.google_invoice_json(total="238,00", tax="38,00", net="200,00", items=items,
                                                         bill_no="G-1")))
        gui.answers["buttonbox"] = "Später buchen"
        pinv = prerechnung.read_and_transfer(pre)
        doc = fake_api.get_doc("Purchase Invoice", pinv.doc["name"])
        assert doc["update_stock"] == 1 and doc["project"] == "PROJ-0001"
        assert doc["items"][0]["item_code"] == "010.100.001" and doc["items"][0]["qty"] == 2.0
        assert doc["items"][0]["rate"] == 100.0 and doc["grand_total"] == 238.0
        assert doc["bill_no"] == "G-1" and doc["order_id"] == "BEST-1"
        assert len(fake_api.get_list("Item Price")) == 1


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
    def test_wires_google_and_transfer(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import args
        import company
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF")
        seen: dict[str, Any] = {}
        monkeypatch.setattr(args, "init", lambda: seen.setdefault("init", True))
        monkeypatch.setattr(company.Company, "init_companies", classmethod(lambda cls: seen.setdefault("companies", True)))
        monkeypatch.setattr(prerechnung, "extract_invoice_info", lambda c: {"entities": [], "content": c})
        monkeypatch.setattr(purchase_invoice.PurchaseInvoice, "read_and_transfer",
                            classmethod(lambda cls, *a, **k: seen.update(args=a, kwargs=k) or "PINV"))
        assert prerechnung.read_and_transfer_pdf(str(pdf), True, account="4210", supplier="S", project="P") == "PINV"
        assert seen["init"] and seen["companies"]
        assert seen["args"] == ({"entities": [], "content": b"%PDF"}, str(pdf), True)
        assert seen["kwargs"] == {"account_abbrv": "4210", "paid_by_submitter": False, "project": "P", "supplier": "S",
                                  "check_dup": True}
