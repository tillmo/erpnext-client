"""Rauchtest: alle Projektmodule sind unter den Stubs importierbar."""
import importlib

import pytest

from support.deps import HAVE_PDFTOTEXT

MODULES = ["version", "frappe", "frappeclient", "api_wrapper", "api", "settings", "utils", "doc",
           "company", "invoice", "payment", "journal", "bank", "stock", "project", "supplier_item",
           "table", "report", "lead", "sales_invoice", "compute_tests",
           "purchase_invoice_parser", "purchase_invoice_google_parser"]
PDF_MODULES = ["purchase_invoice", "prerechnung", "args", "menu"]


@pytest.mark.parametrize("name", MODULES)
def test_module_importable(name):
    assert importlib.import_module(name)


@pytest.mark.parametrize("name", PDF_MODULES)
def test_pdf_module_importable(name):
    if not HAVE_PDFTOTEXT:
        pytest.skip("pdftotext fehlt")
    assert importlib.import_module(name)


def test_no_real_gui_modules_loaded():
    import PySimpleGUI, easygui
    assert PySimpleGUI.UserSettings.__module__ == "support.stubs"
    assert type(easygui).__name__ == "EasyguiStub"


def test_fake_api_roundtrip(fake_api):
    from api import Api
    name = Api.api.insert({"doctype": "Supplier", "supplier_name": "Test"})["name"]
    assert name == "Test"
    assert Api.api.get_list("Supplier") == [{"name": "Test"}]
    assert Api.api.get_doc("Supplier", "Test")["doctype"] == "Supplier"


@pytest.mark.xfail(strict=True, reason="Importzyklus company -> invoice -> company: 'import invoice' als erster "
                                       "Import schlägt fehl; das Programm importiert immer zuerst company")
def test_invoice_importable_standalone():
    import subprocess, sys, os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code = ("import sys; sys.path[:0] = [%r, %r]; from support import stubs; stubs.install(); import invoice"
            % (os.path.join(root, "tests"), root))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root)
    assert r.returncode == 0, r.stderr[-500:]
