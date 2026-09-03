"""Smoke test: all project modules can be imported under the stubs."""
from __future__ import annotations

import importlib

import pytest

from support.deps import HAVE_PDFTOTEXT
from support.fakes import FakeFrappeClient

MODULES = ["version", "frappe", "frappeclient", "api_wrapper", "api", "settings", "utils", "doc",
           "company", "invoice", "payment", "journal", "bank", "stock", "project", "supplier_item",
           "table", "report", "lead", "sales_invoice", "compute_tests",
           "purchase_invoice_parser", "purchase_invoice_google_parser"]
PDF_MODULES = ["purchase_invoice", "prerechnung", "args", "menu"]


@pytest.mark.parametrize("name", MODULES)
def test_module_importable(name: str) -> None:
    assert importlib.import_module(name)


@pytest.mark.parametrize("name", PDF_MODULES)
def test_pdf_module_importable(name: str) -> None:
    if not HAVE_PDFTOTEXT:
        pytest.skip("pdftotext fehlt")
    assert importlib.import_module(name)


def test_no_real_gui_modules_loaded() -> None:
    import PySimpleGUI, easygui
    assert PySimpleGUI.UserSettings.__module__ == "support.stubs"
    assert type(easygui).__name__ == "EasyguiStub"


def test_fake_api_roundtrip(fake_api: FakeFrappeClient) -> None:
    from api import Api
    name = Api.api.insert({"doctype": "Supplier", "supplier_name": "Test"})["name"]
    assert name == "Test"
    assert Api.api.get_list("Supplier") == [{"name": "Test"}]
    assert Api.api.get_doc("Supplier", "Test")["doctype"] == "Supplier"


@pytest.mark.parametrize("name", MODULES + PDF_MODULES)
def test_module_importable_as_first_import(name: str) -> None:
    """No module may depend on a particular import order (import cycles)."""
    import subprocess, sys, os
    if name in PDF_MODULES and not HAVE_PDFTOTEXT:
        pytest.skip("pdftotext fehlt")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code = ("import sys; sys.path[:0] = [%r, %r]; from support import stubs; stubs.install(); import %s"
            % (os.path.join(root, "tests"), root, name))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root)
    assert r.returncode == 0, r.stderr[-600:]
