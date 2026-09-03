"""Create a PreRechnung, preprocess it and transfer it into a purchase invoice."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import prerechnung
import utils
from api import Api
from support import factories as F
from support.deps import skip_module_without_pdftotext
from support.live import Cleanup, LiveState, tag
from support.stubs import EasyguiStub

skip_module_without_pdftotext()

PRE_FIELDS = ["datum", "name", "chance", "lieferant", "pdf", "json", "lager", "selbst_bezahlt", "vom_konto_überwiesen",
              "typ", "processed", "balkonmodule", "buchungskonto", "nuruk", "nurelektromaterial", "eingepflegt",
              "purchase_invoice", "betrag", "auftragsnr"]


@pytest.fixture(autouse=True)
def _need_doctype(live: LiveState, monkeypatch: pytest.MonkeyPatch) -> None:
    if not live.doctype_exists("PreRechnung"):
        pytest.skip("DocType PreRechnung fehlt auf der Instanz")
    monkeypatch.setattr(utils, "evince", lambda f: None)


# The server side (app bremer_solidarstrom) only allows fixed short names for buchungskonto
BUCHUNGSKONTO = "Werkzeuge und Kleingeräte"


@pytest.fixture
def konto(live: LiveState) -> str:
    accs = [a["name"] for a in live.company.leaf_accounts if BUCHUNGSKONTO in a["name"]]
    if not accs:
        pytest.skip("kein Konto '{}' fuer {}".format(BUCHUNGSKONTO, live.company_name))
    return accs[0]


@pytest.fixture
def pre(live: LiveState, api: Any, cleanup: Cleanup, test_supplier: str, konto: str, tmp_path: Path, today: str) -> tuple[dict[str, Any], str]:
    no = tag("PRE")
    pdf = F.write_generic_invoice_pdf(tmp_path / "pre.pdf", no=no)
    # 'pdf' is a mandatory field, but the file can only be attached to an existing document:
    # placeholder without file URL, then attach directly to the field (docfield sets 'pdf')
    doc = api.insert({"doctype": "PreRechnung", "company": live.company_name, "lieferant": test_supplier,
                      "typ": "Rechnung", "datum": today, "processed": 0, "eingepflegt": 0,
                      "buchungskonto": BUCHUNGSKONTO, "selbst_bezahlt": 0, "lager": 0,
                      "pdf": "pytest-platzhalter", "kommentar": "pytest " + no})
    cleanup.add("PreRechnung", doc["name"])
    api.read_and_attach_file("PreRechnung", doc["name"], pdf, True, docfield="pdf")
    rows = api.get_list("PreRechnung", filters={"name": doc["name"]}, fields=PRE_FIELDS, limit_page_length=1)
    assert rows[0]["pdf"].startswith("/private/files/")
    return rows[0], no


class TestProcessInv:
    def test_process_inv_marks_processed(self, api: Any, pre: tuple[dict[str, Any], str]) -> None:
        inv, no = pre
        prerechnung.process_inv(inv)
        stored = api.get_doc("PreRechnung", inv["name"])
        assert stored["processed"] == 1

    def test_process_inv_sets_amount(self, api: Any, pre: tuple[dict[str, Any], str]) -> None:
        inv, no = pre
        prerechnung.process_inv(inv)
        assert api.get_doc("PreRechnung", inv["name"])["betrag"] == pytest.approx(119.0)


class TestReadAndTransfer:
    def test_pre_invoice_to_purchase_invoice(self, live: LiveState, api: Any, cleanup: Cleanup,
                                             pre: tuple[dict[str, Any], str], gui: EasyguiStub) -> None:
        inv, no = pre
        inv["processed"] = 1
        gui.answers["buttonbox"] = "Später buchen"
        pinv = prerechnung.read_and_transfer(inv, cli_overrides={"rechnungsnr": no})
        assert pinv is not None and not pinv.is_duplicate
        cleanup.add("Purchase Invoice", pinv.doc["name"])
        doc = api.get_doc("Purchase Invoice", pinv.doc["name"])
        assert doc["supplier"] == inv["lieferant"] and doc["bill_no"] == no
        assert doc["grand_total"] == pytest.approx(119.0) and doc["update_stock"] == 0
        assert BUCHUNGSKONTO in doc["items"][0]["expense_account"]
        stored = api.get_doc("PreRechnung", inv["name"])
        assert stored["eingepflegt"] == 1 and stored["purchase_invoice"] == doc["name"]
        assert inv["name"] not in {p["name"] for p in live.company.get_open_pre_invoices(False)}

    def test_cli_selection_by_name(self, live: LiveState, api: Any, cleanup: Cleanup, pre: tuple[dict[str, Any], str],
                                   gui: EasyguiStub) -> None:
        inv, no = pre
        api.update({"doctype": "PreRechnung", "name": inv["name"], "processed": 1})
        gui.answers["buttonbox"] = "Später buchen"
        pinv = prerechnung.cli_read_and_transfer(name=inv["name"], overrides={"rechnungsnr": no})
        assert pinv is not None
        cleanup.add("Purchase Invoice", pinv.doc["name"])
        assert api.get_doc("PreRechnung", inv["name"])["purchase_invoice"] == pinv.doc["name"]
