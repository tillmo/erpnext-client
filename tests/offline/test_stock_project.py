"""Tests for stock.py and project.py (project stock keeping)."""
from __future__ import annotations

from typing import Any

import pytest

import project
import stock
from settings import PROJECT_WAREHOUSE, PROJECT_ITEM_GROUP, PROJECT_UNIT, SOMIKO_ACCOUNTS, LUMP_SUM_STOCK_PROJECT_TYPES
from support import factories as F
from support.fakes import FakeFrappeClient
from frappeclient import FrappeException


def strip_meta(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items() if k not in ("idx", "parent", "parenttype", "parentfield")} for r in rows]


class TestDocBuilders:
    def test_stock_reconciliation(self, fake_api: FakeFrappeClient) -> None:
        doc = stock.stock_reconciliation_for_item("F", "2026-01-01", "I", "Lager", 3, 10.0, "Konto", "EK 1")
        assert doc["doctype"] == "Stock Reconciliation" and doc["purpose"] == "Stock Reconciliation"
        assert doc["company"] == "F" and doc["posting_date"] == "2026-01-01" and doc["set_posting_time"] == 1
        assert doc["expense_account"] == "Konto" and doc["purchase_invoice"] == "EK 1"
        assert strip_meta(doc["items"]) == [{"item_code": "I", "warehouse": "Lager", "qty": 3, "valuation_rate": 10.0}]
        doc2 = stock.stock_reconciliation_for_item("F", "2026-01-01", "I", "Lager", 3, 10.0, "Konto")
        assert "purchase_invoice" not in doc2

    def test_stock_entry_ingoing(self, fake_api: FakeFrappeClient) -> None:
        doc = stock.stock_entry_for_item("F", "2026-01-01", "I", "Lager", True, 500.0, "Konto", "EK 1", "PROJ-1")
        assert doc["stock_entry_type"] == "Material Receipt"
        assert doc["posting_date"] == "2026-01-01" and doc["set_posting_time"] == 1
        assert doc["purchase_invoice"] == "EK 1" and doc["project"] == "PROJ-1"
        assert strip_meta(doc["items"]) == [{"item_code": "I", "expense_account": "Konto", "qty": 500.0, "basic_rate": 1,
                                             "t_warehouse": "Lager"}]

    def test_stock_entry_outgoing(self, fake_api: FakeFrappeClient) -> None:
        doc = stock.stock_entry_for_item("F", "2026-01-01", "I", "Lager", False, 500.0, "Konto")
        assert doc["stock_entry_type"] == "Material Issue"
        assert "posting_date" not in doc and "purchase_invoice" not in doc and "project" not in doc
        assert doc["items"][0]["s_warehouse"] == "Lager" and "t_warehouse" not in doc["items"][0]


@pytest.fixture
def stock_project(fake_api: FakeFrappeClient) -> FakeFrappeClient:
    fake_api.add("Project", name="PROJ-0007", project_type="Solaranlage", project_name="Haus Meier", status="Open")
    fake_api.add("Project", name="PROJ-0008", project_type="Balkonmodule", project_name="Balkon", status="Open")
    fake_api.add("Purchase Invoice", name="EK 2026-00001", company=F.COMPANY, project="PROJ-0007", total=500.0,
                 posting_date="2026-02-01", status="Unpaid")
    fake_api.add("Purchase Invoice", name="EK 2026-00002", company=F.COMPANY, project="PROJ-0007", total=200.0,
                 posting_date="2026-02-02", status="Cancelled")
    fake_api.add("Purchase Invoice", name="EK 2026-00003", company=F.COMPANY, project="PROJ-0008", total=200.0,
                 posting_date="2026-02-03", status="Unpaid")
    fake_api.add("Purchase Invoice", name="EK 2026-00004", company=F.COMPANY, project=None, total=200.0,
                 posting_date="2026-02-04", status="Unpaid")
    return fake_api


class TestPurchaseInvoiceIntoStock:
    def test_creates_item_and_material_receipt(self, stock_project: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        stock.purchase_invoice_into_stock("EK 2026-00001")
        item = stock_project.get_doc("Item", "000.900.007")
        assert item["item_name"] == item["description"] == "Material Projekt 7 Haus Meier"
        assert item["item_group"] == PROJECT_ITEM_GROUP and item["stock_uom"] == PROJECT_UNIT
        assert item["item_defaults"][0]["company"] == F.COMPANY
        assert item["item_defaults"][0]["default_warehouse"] == PROJECT_WAREHOUSE
        entries = stock_project.get_list("Stock Entry", fields=["*"])
        assert len(entries) == 1
        e = entries[0]
        assert e["stock_entry_type"] == "Material Receipt" and e["posting_date"] == "2026-02-01"
        assert e["purchase_invoice"] == "EK 2026-00001" and e["project"] == "PROJ-0007"
        assert e["items"][0]["item_code"] == "000.900.007" and e["items"][0]["qty"] == 500.0
        assert e["items"][0]["t_warehouse"] == PROJECT_WAREHOUSE
        assert e["items"][0]["expense_account"] == list(SOMIKO_ACCOUNTS.values())[0]
        out = capsys.readouterr().out
        assert "Artikel 000.900.007" in out and "Lagerbuchung" in out and "Bitte noch buchen" in out

    def test_existing_entry_prevents_duplicate(self, stock_project: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        stock.purchase_invoice_into_stock("EK 2026-00001")
        stock.purchase_invoice_into_stock("EK 2026-00001")
        assert len(stock_project.get_list("Stock Entry")) == 1
        assert "existiert schon eine Lagerbuchung" in capsys.readouterr().out
        assert len(stock_project.get_list("Item")) == 1

    def test_outgoing_ignores_existing_receipt(self, stock_project: FakeFrappeClient) -> None:
        stock.purchase_invoice_into_stock("EK 2026-00001")
        stock.purchase_invoice_into_stock("EK 2026-00001", ingoing=False)
        entries = stock_project.get_list("Stock Entry", fields=["stock_entry_type", "items"])
        assert sorted(e["stock_entry_type"] for e in entries) == ["Material Issue", "Material Receipt"]
        issue = [e for e in entries if e["stock_entry_type"] == "Material Issue"][0]
        assert issue["items"][0]["s_warehouse"] == PROJECT_WAREHOUSE

    def test_without_project(self, stock_project: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        stock.purchase_invoice_into_stock("EK 2026-00004")
        assert stock_project.get_list("Stock Entry") == []
        assert "kein Projekt" in capsys.readouterr().out

    def test_non_stock_project_type(self, stock_project: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        stock.purchase_invoice_into_stock("EK 2026-00003")
        assert stock_project.get_list("Stock Entry") == []
        assert "Keine Projekt-Lagerhaltung für Projekt PROJ-0008" in capsys.readouterr().out

    def test_failed_insert_is_reported(self, stock_project: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
        def failing_insert(doc: dict[str, Any]) -> None:
            raise FrappeException("FrappeClient Request Failed\n\nValidationError")
        monkeypatch.setattr(stock_project, "insert", failing_insert)
        stock.purchase_invoice_into_stock("EK 2026-00001")
        assert stock_project.get_list("Stock Entry") == []
        assert "konnte nicht angelegt werden" in capsys.readouterr().out

    def test_project_into_stock_skips_cancelled(self, stock_project: FakeFrappeClient) -> None:
        stock.project_into_stock("PROJ-0007")
        entries = stock_project.get_list("Stock Entry", fields=["purchase_invoice"])
        assert [e["purchase_invoice"] for e in entries] == ["EK 2026-00001"]


class TestProject:
    def test_is_stock_and_type(self, stock_project: FakeFrappeClient) -> None:
        assert project.project_type("PROJ-0007") == "Solaranlage"
        assert project.is_stock({"project_type": LUMP_SUM_STOCK_PROJECT_TYPES[0]}) is True
        assert project.is_stock({"project_type": "Balkonmodule"}) is False
        assert project.is_stock({}) is False

    def test_complete_stock_project_issues_material(self, stock_project: FakeFrappeClient) -> None:
        project.complete_project("PROJ-0007")
        assert stock_project.get_doc("Project", "PROJ-0007")["status"] == "Completed"
        entries = stock_project.get_list("Stock Entry", fields=["stock_entry_type", "purchase_invoice"])
        assert entries == [{"stock_entry_type": "Material Issue", "purchase_invoice": "EK 2026-00001"}]

    def test_complete_non_stock_project(self, stock_project: FakeFrappeClient) -> None:
        project.complete_project("PROJ-0008")
        assert stock_project.get_doc("Project", "PROJ-0008")["status"] == "Completed"
        assert stock_project.get_list("Stock Entry") == []
