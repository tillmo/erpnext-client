"""PreRechnungen, leads and item master - read-only."""
from __future__ import annotations

from typing import Any

import pytest

import lead
import prerechnung
import utils
from api import Api, LIMIT
from support.live import LiveState, ReadOnlyViolation


class TestPreRechnung:
    @pytest.fixture(autouse=True)
    def _need_doctype(self, live: LiveState) -> None:
        if not live.doctype_exists("PreRechnung"):
            pytest.skip("DocType PreRechnung fehlt auf der Instanz")

    def test_field_names_used_by_client(self, api: Any, live: LiveState) -> None:
        fields = ["datum", "name", "chance", "lieferant", "pdf", "json", "lager", "selbst_bezahlt",
                  "vom_konto_überwiesen", "typ", "processed", "balkonmodule", "buchungskonto", "nuruk",
                  "nurelektromaterial", "eingepflegt", "purchase_invoice", "zu_zahlen_am", "betrag", "auftragsnr",
                  "kommentar", "company"]
        rows = api.get_list("PreRechnung", fields=fields, limit_page_length=2)
        for r in rows:
            assert set(r) == set(fields)

    def test_to_pay(self, live: LiveState) -> None:
        prs = prerechnung.to_pay(live.company_name)
        dates = [pr["zu_zahlen_am"] for pr in prs]
        assert dates == sorted(dates)
        running = 0.0
        for pr in prs:
            running += pr["betrag"]
            assert pr["summe"] == pytest.approx(running)

    def test_pre_invoice_pdfs_are_downloadable(self, api: Any, live: LiveState) -> None:
        rows = api.get_list("PreRechnung", filters={"company": live.company_name, "pdf": ["is", "set"]},
                            fields=["name", "pdf"], limit_page_length=1)
        if not rows:
            pytest.skip("keine PreRechnung mit PDF")
        content = api.get_file(rows[0]["pdf"])
        assert content[:4] == b"%PDF"


class TestLeads:
    def test_open_leads(self, api: Any) -> None:
        leads = api.get_list("Lead", filters={"status": "Open"}, fields=["name", "status", "lead_name", "creation"],
                             limit_page_length=5)
        for l in leads:
            assert lead.format(l)["creation"].count("-") == 2

    def test_load_doc_and_communications(self, api: Any) -> None:
        leads = api.get_list("Lead", limit_page_length=1)
        if not leads:
            pytest.skip("keine Leads")
        res = api.load_doc("Lead", leads[0]["name"])
        assert res["docs"][0]["name"] == leads[0]["name"]
        comms = res["docinfo"]["communications"]
        for c in comms[:2]:
            assert isinstance(utils.html_to_text(c["content"]), str)

    def test_unassigned_filter_is_accepted(self, api: Any) -> None:
        rows = api.get_list("Lead", filters={"status": "Open", "_assign": ["like", None]},
                            fields=["name", "status", "lead_name"], limit_page_length=3)
        assert isinstance(rows, list)


class TestItems:
    def test_load_item_data(self, live: LiveState, api: Any, capsys: pytest.CaptureFixture[str]) -> None:
        Api.items_by_code = {}
        Api.item_code_translation = []
        Api.load_item_data()
        assert Api.items_by_code, "keine Artikel geladen"
        for code, item in list(Api.items_by_code.items())[:50]:
            assert item["item_code"] == code
            assert isinstance(item["supplier_items"], list)
        for supplier, trans in Api.item_code_translation.items():
            for part_no, code in trans.items():
                assert code in Api.items_by_code
        # load_item_data would have created items without item_defaults - this is blocked in read-only mode
        blocked = [b for b in api.blocked if b[0] == "update"]
        if blocked:
            print("{} Artikel ohne item_defaults für {} (würden beim Start ergänzt): {}".format(
                len(blocked), live.company_name, [b[1][0]["name"] for b in blocked][:10]))

    def test_load_account_data(self, live: LiveState) -> None:
        Api.accounts_by_company = {}
        Api.load_account_data()
        assert set(Api.accounts_by_company) >= set(live.companies)
        for c, accs in Api.accounts_by_company.items():
            assert all(a["company"] == c for a in accs)

    def test_default_items_are_enabled(self, api: Any) -> None:
        import settings
        rows = api.get_list("Item", filters={"name": ["in", settings.DEFAULT_ITEMS + [settings.DEFAULT_ITEM_CODE]]},
                            fields=["name", "disabled"], limit_page_length=LIMIT)
        assert rows and all(r["disabled"] == 0 for r in rows), rows
