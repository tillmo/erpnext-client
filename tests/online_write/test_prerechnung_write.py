"""PreRechnung anlegen, vorprozessieren und in eine Einkaufsrechnung überführen."""
import pytest

import prerechnung
import utils
from api import Api
from support import factories as F
from support.deps import skip_module_without_pdftotext
from support.live import tag

skip_module_without_pdftotext()

PRE_FIELDS = ["datum", "name", "chance", "lieferant", "pdf", "json", "lager", "selbst_bezahlt", "vom_konto_überwiesen",
              "typ", "processed", "balkonmodule", "buchungskonto", "nuruk", "nurelektromaterial", "eingepflegt",
              "purchase_invoice", "betrag", "auftragsnr"]


@pytest.fixture(autouse=True)
def _need_doctype(live, monkeypatch):
    if not live.doctype_exists("PreRechnung"):
        pytest.skip("DocType PreRechnung fehlt auf der Instanz")
    monkeypatch.setattr(utils, "evince", lambda f: None)


@pytest.fixture
def pre(live, api, cleanup, test_supplier, tmp_path, today):
    no = tag("PRE")
    pdf = F.write_generic_invoice_pdf(tmp_path / "pre.pdf", no=no)
    doc = api.insert({"doctype": "PreRechnung", "company": live.company_name, "lieferant": test_supplier,
                      "typ": "Rechnung", "datum": today, "processed": 0, "eingepflegt": 0,
                      "buchungskonto": live.expense_leaf(), "selbst_bezahlt": 0, "lager": 0,
                      "kommentar": "pytest " + no})
    cleanup.add("PreRechnung", doc["name"])
    upload = api.read_and_attach_file("PreRechnung", doc["name"], pdf, True)
    api.update({"doctype": "PreRechnung", "name": doc["name"], "pdf": upload["file_url"]})
    rows = api.get_list("PreRechnung", filters={"name": doc["name"]}, fields=PRE_FIELDS, limit_page_length=1)
    return rows[0], no


class TestProcessInv:
    def test_process_inv_marks_processed(self, api, pre):
        inv, no = pre
        prerechnung.process_inv(inv)
        stored = api.get_doc("PreRechnung", inv["name"])
        assert stored["processed"] == 1

    def test_process_inv_sets_amount(self, api, pre):
        inv, no = pre
        prerechnung.process_inv(inv)
        assert api.get_doc("PreRechnung", inv["name"])["betrag"] == pytest.approx(119.0)


class TestReadAndTransfer:
    def test_pre_invoice_to_purchase_invoice(self, live, api, cleanup, pre, gui):
        inv, no = pre
        inv["processed"] = 1
        gui.answers["buttonbox"] = "Später buchen"
        pinv = prerechnung.read_and_transfer(inv, cli_overrides={"rechnungsnr": no})
        assert pinv is not None and not pinv.is_duplicate
        cleanup.add("Purchase Invoice", pinv.doc["name"])
        doc = api.get_doc("Purchase Invoice", pinv.doc["name"])
        assert doc["supplier"] == inv["lieferant"] and doc["bill_no"] == no
        assert doc["grand_total"] == pytest.approx(119.0) and doc["update_stock"] == 0
        assert doc["items"][0]["expense_account"] == live.expense_leaf()
        stored = api.get_doc("PreRechnung", inv["name"])
        assert stored["eingepflegt"] == 1 and stored["purchase_invoice"] == doc["name"]
        assert inv["name"] not in {p["name"] for p in live.company.get_open_pre_invoices(False)}

    def test_cli_selection_by_name(self, live, api, cleanup, pre, gui):
        inv, no = pre
        api.update({"doctype": "PreRechnung", "name": inv["name"], "processed": 1})
        gui.answers["buttonbox"] = "Später buchen"
        pinv = prerechnung.cli_read_and_transfer(name=inv["name"], overrides={"rechnungsnr": no})
        assert pinv is not None
        cleanup.add("Purchase Invoice", pinv.doc["name"])
        assert api.get_doc("PreRechnung", inv["name"])["purchase_invoice"] == pinv.doc["name"]
