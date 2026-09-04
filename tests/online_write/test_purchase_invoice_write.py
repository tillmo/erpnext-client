"""Create a purchase invoice from a PDF - end-to-end against the test instance."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from api import Api, LIMIT
from frappeclient import FrappeException
from support import factories as F
from support.deps import skip_module_without_pdftotext
from support.live import Cleanup, LiveState, tag
from support.stubs import EasyguiStub, UserSettings

skip_module_without_pdftotext()

from purchase_invoice import PurchaseInvoice  # noqa: E402


def attachments(api: Any, name: str) -> list[dict[str, Any]]:
    return api.get_list("File", filters={"attached_to_doctype": "Purchase Invoice", "attached_to_name": name},
                        fields=["name", "file_url", "is_private", "attached_to_field"], limit_page_length=LIMIT)


@pytest.fixture
def invoice_pdf(tmp_path: Path) -> tuple[str, str]:
    no = tag("RE")
    return no, F.write_generic_invoice_pdf(tmp_path / "rechnung.pdf", no=no)


class TestReadAndTransfer:
    def test_draft_invoice_from_pdf(self, live: LiveState, api: Any, cleanup: Cleanup, test_supplier: str,
                                    invoice_pdf: tuple[str, str], gui: EasyguiStub, user_settings: UserSettings) -> None:
        if not live.company.taxes:
            pytest.skip("Firma ohne Vorsteuer-Vorlage: create_taxes hätte nichts zu tun")
        no, pdf = invoice_pdf
        gui.answers["buttonbox"] = "Später buchen"
        pinv = PurchaseInvoice.read_and_transfer(None, pdf, False,
                                                 cli_overrides={"konto": live.expense_leaf(), "lieferant": test_supplier,
                                                                "rechnungsnr": no})
        assert pinv is not None and not pinv.is_duplicate
        name = pinv.doc["name"]
        cleanup.add("Purchase Invoice", name)
        doc = api.get_doc("Purchase Invoice", name)
        assert doc["docstatus"] == 0 and doc["company"] == live.company_name
        assert doc["supplier"] == test_supplier and doc["bill_no"] == no
        assert doc["posting_date"] == "2026-09-03"
        assert doc["total"] == pytest.approx(100.0) and doc["grand_total"] == pytest.approx(119.0)
        assert doc["update_stock"] == 0
        assert doc["items"][0]["expense_account"] == live.expense_leaf()
        assert doc["taxes"] and doc["taxes"][0]["account_head"] == live.company.taxes[19.0]
        assert doc["supplier_invoice"] and api.get_file(doc["supplier_invoice"])[:4] == b"%PDF"
        files = attachments(api, name)
        assert len(files) == 1, files
        # exactly one private file, bound to the field (no public copy by Frappe)
        assert files[0]["is_private"] == 1 and files[0]["attached_to_field"] == "supplier_invoice"
        assert files[0]["file_url"] == doc["supplier_invoice"] and doc["supplier_invoice"].startswith("/private/")
        # visible as an open purchase invoice (draft)
        assert name in {inv.name for inv in live.company.get_purchase_invoices(True)}
        assert "Später buchen" in gui.calls[-1][1][2]

    def test_duplicate_is_detected(self, live: LiveState, api: Any, cleanup: Cleanup, test_supplier: str,
                                   invoice_pdf: tuple[str, str], gui: EasyguiStub) -> None:
        no, pdf = invoice_pdf
        gui.answers["buttonbox"] = "Später buchen"
        gui.answers["msgbox"] = None
        first = PurchaseInvoice.read_and_transfer(None, pdf, False,
                                                  cli_overrides={"konto": live.expense_leaf(), "lieferant": test_supplier,
                                                                 "rechnungsnr": no})
        cleanup.add("Purchase Invoice", first.doc["name"])
        second = PurchaseInvoice.read_and_transfer(None, pdf, False,
                                                   cli_overrides={"konto": live.expense_leaf(), "lieferant": test_supplier,
                                                                  "rechnungsnr": no})
        assert second.is_duplicate and second.doc["name"] == first.doc["name"]
        assert "schon als {}".format(first.doc["name"]) in gui.calls[-1][1][0]
        assert len(api.get_list("Purchase Invoice", filters={"bill_no": no})) == 1
        assert len(attachments(api, first.doc["name"])) >= 2

    def test_silent_transfer_without_dialogs(self, live: LiveState, api: Any, cleanup: Cleanup, test_supplier: str,
                                             invoice_pdf: tuple[str, str], gui: EasyguiStub) -> None:
        no, pdf = invoice_pdf
        pinv = PurchaseInvoice.read_and_transfer(None, pdf, False, check_dup=False,
                                                 cli_overrides={"konto": live.expense_leaf(), "lieferant": test_supplier,
                                                                "rechnungsnr": no})
        cleanup.add("Purchase Invoice", pinv.doc["name"])
        assert gui.calls == []
        assert api.get_doc("Purchase Invoice", pinv.doc["name"])["bill_no"] == no

    def test_delete_removes_attachments(self, live: LiveState, api: Any, cleanup: Cleanup, test_supplier: str,
                                        invoice_pdf: tuple[str, str], gui: EasyguiStub) -> None:
        no, pdf = invoice_pdf
        gui.answers["buttonbox"] = "Später buchen"
        pinv = PurchaseInvoice.read_and_transfer(None, pdf, False,
                                                 cli_overrides={"konto": live.expense_leaf(), "lieferant": test_supplier,
                                                                "rechnungsnr": no})
        name = pinv.doc["name"]
        api.delete("Purchase Invoice", name)
        with pytest.raises(FrappeException):
            api.get_doc("Purchase Invoice", name)
        assert attachments(api, name) == []


class TestEinvoice:
    def test_draft_from_embedded_xml(self, live: LiveState, api: Any, cleanup: Cleanup, test_supplier: str, tmp_path: Path,
                                     gui: EasyguiStub) -> None:
        pytest.importorskip("pypdf")
        from offline.test_einvoice import CII
        if not live.company.taxes:
            pytest.skip("Firma ohne Vorsteuer-Vorlage")
        no = tag("EINV")
        xml = (CII.replace("Krannich Solar GmbH &amp; Co. KG", test_supplier.replace("&", "&amp;"))
               .replace("2106-4076249", no).replace("DE814994131", "DE000000000"))
        pdf = F.write_einvoice_pdf(tmp_path / "einvoice.pdf", xml)
        gui.answers["buttonbox"] = "Später buchen"
        pinv = PurchaseInvoice.read_and_transfer(None, pdf, False, cli_overrides={"konto": live.expense_leaf()})
        assert pinv is not None and not pinv.is_duplicate and pinv.parser == "einvoice"
        name = pinv.doc["name"]
        cleanup.add("Purchase Invoice", name)
        doc = api.get_doc("Purchase Invoice", name)
        assert doc["supplier"] == test_supplier and doc["bill_no"] == no and doc["posting_date"] == "2026-08-21"
        # net incl. shipping 900 + 19 % = 1071; 3 % Skonto from the payment terms as discount
        assert doc["grand_total"] == pytest.approx(1071.0) or doc["grand_total"] == pytest.approx(1071.0 - 32.13)
        assert doc.get("discount_amount") == pytest.approx(32.13)
        assert doc["taxes"] and doc["taxes"][0]["account_head"] == live.company.taxes[19.0]
        assert api.get_file(doc["supplier_invoice"])[:4] == b"%PDF"


class TestSubmit:
    def test_book_immediately(self, live: LiveState, api: Any, cleanup: Cleanup, test_supplier: str,
                              invoice_pdf: tuple[str, str], gui: EasyguiStub, submit_allowed: bool) -> None:
        no, pdf = invoice_pdf
        gui.answers["buttonbox"] = "Sofort buchen"
        pinv = PurchaseInvoice.read_and_transfer(None, pdf, False,
                                                 cli_overrides={"konto": live.expense_leaf(), "lieferant": test_supplier,
                                                                "rechnungsnr": no})
        cleanup.add("Purchase Invoice", pinv.doc["name"])
        doc = api.get_doc("Purchase Invoice", pinv.doc["name"])
        assert doc["docstatus"] == 1
        assert doc["outstanding_amount"] == pytest.approx(119.0)
        assert doc["status"] in ("Unpaid", "Overdue")
