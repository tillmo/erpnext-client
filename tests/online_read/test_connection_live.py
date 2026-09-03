"""Verbindung und Grundverhalten der REST-API - prüft auch die Annahmen des Offline-Fakes."""
import pytest

from api import Api
from frappeclient import FrappeException
from support.live import ReadOnlyViolation


class TestConnection:
    def test_initialize_returns_companies(self, live, user_settings):
        companies = Api.initialize()
        assert live.company_name in [c["name"] for c in companies]
        live.install(read_only=True)   # Api.initialize hat den ungeschützten Client eingesetzt

    def test_initialize_with_settings_marks_setup_done(self, live, user_settings):
        Api.initialize_with_settings()
        assert user_settings["-setup-"] is False
        live.install(read_only=True)

    def test_read_only_guard(self, api):
        with pytest.raises(ReadOnlyViolation):
            api.insert({"doctype": "Supplier", "supplier_name": "darf nicht"})


class TestGetListSemantics:
    """Diese Eigenschaften bildet support.fakes.FakeFrappeClient nach; hier werden sie am Server verifiziert."""

    def test_default_fields_are_name_only(self, api):
        rows = api.get_list("Company")
        assert rows and all(set(r) == {"name"} for r in rows)

    def test_requested_fields_only(self, api, live):
        rows = api.get_list("Company", fields=["name", "abbr"], filters={"name": live.company_name})
        assert rows == [{"name": live.company_name, "abbr": rows[0]["abbr"]}]

    def test_default_page_length_is_20(self, api):
        accounts = api.get_list("Account")
        all_accounts = api.get_list("Account", limit_page_length=100000)
        if len(all_accounts) <= 20:
            pytest.skip("weniger als 21 Konten")
        assert len(accounts) == 20

    def test_limit_and_order(self, api):
        rows = api.get_list("Account", fields=["name", "creation"], limit_page_length=3, order_by="creation desc")
        assert len(rows) == 3
        assert rows == sorted(rows, key=lambda r: r["creation"], reverse=True)

    def test_filters_operators(self, api, live):
        eq = api.get_list("Account", filters={"company": live.company_name, "is_group": 1}, fields=["name", "is_group"],
                          limit_page_length=5)
        assert all(r["is_group"] == 1 for r in eq)
        inop = api.get_list("Account", filters={"root_type": ["in", ["Income", "Expense"]], "company": live.company_name},
                            fields=["root_type"], limit_page_length=50)
        assert set(r["root_type"] for r in inop) <= {"Income", "Expense"}
        like = api.get_list("Account", filters={"name": ["like", "%" + live.company.leaf_accounts[0]["name"][:6] + "%"]},
                            limit_page_length=5)
        assert like
        assert api.get_list("Account", filters={"name": "gibt es ganz sicher nicht"}) == []

    def test_child_table_join(self, api, live):
        rows = api.get_list("Purchase Invoice", filters={"company": live.company_name},
                            fields=["name", "supplier", "`tabPurchase Invoice Item`.expense_account as expense_account"],
                            limit_page_length=5)
        if not rows:
            pytest.skip("keine Einkaufsrechnungen")
        assert all(set(r) == {"name", "supplier", "expense_account"} for r in rows)

    def test_child_table_filter(self, api, live):
        # Filter über Kindtabelle wie in bank.BankTransaction.submit_entry
        rows = api.get_list("Bank Transaction", fields=["name"],
                            filters=[["Bank Transaction Payments", "payment_entry", "like", "%ACC%"]], limit_page_length=2)
        assert isinstance(rows, list)


class TestDocuments:
    def test_get_doc_company(self, api, live):
        doc = api.get_doc("Company", live.company_name)
        assert doc["name"] == live.company_name
        assert "abbr" in doc and "default_currency" in doc
        assert doc["doctype"] == "Company"

    def test_get_doc_missing_raises(self, api):
        with pytest.raises(FrappeException):
            api.get_doc("Company", "gibt es ganz sicher nicht")

    def test_get_doc_quoted_name(self, api, live):
        import urllib.parse
        templates = live.company.pre_tax_templates()
        if not templates:
            pytest.skip("keine Vorsteuer-Vorlagen")
        doc = api.get_doc("Purchase Taxes and Charges Template", urllib.parse.quote(templates[0]["name"]))
        assert doc["name"] == templates[0]["name"] and "taxes" in doc

    def test_get_value(self, api, live):
        assert api.get_value("Company", "abbr", {"name": live.company_name})["abbr"]

    def test_load_doc_has_docinfo(self, api, live):
        res = api.load_doc("Company", live.company_name)
        assert res["docs"][0]["name"] == live.company_name
        assert "docinfo" in res

    def test_background_jobs(self, api):
        assert isinstance(api.get_background_jobs(), list)


class TestReports:
    @pytest.mark.parametrize("name", ["General ledger", "General Ledger"])
    def test_general_ledger_report_name_is_case_insensitive(self, api, live, name):
        acc = live.company.leaf_accounts[0]["name"]
        year = __import__("datetime").date.today().year
        rep = api.query_report(report_name=name, filters={"company": live.company_name, "account": [acc],
                                                          "from_date": "{}-01-01".format(year),
                                                          "to_date": "{}-12-31".format(year),
                                                          "group_by": "Group by Voucher (Consolidated)"})
        assert "result" in rep and "columns" in rep
        assert any(r.get("account") in ("'Total'", "'Summe'") for r in rep["result"])

    def test_profit_and_loss_report(self, api, live):
        year = __import__("datetime").date.today().year
        rep = api.query_report(report_name="Profit and Loss Statement",
                               filters={"company": live.company_name, "period_start_date": "{}-01-01".format(year),
                                        "period_end_date": "{}-12-31".format(year), "periodicity": "Yearly",
                                        "accumulated_in_group_company": True, "report": "Profit and Loss Statement"})
        assert rep["columns"] and isinstance(rep["result"], list)
        if not rep["result"]:
            pytest.skip("Firma {} hat keine Buchungen".format(live.company_name))
        assert any("account_name" in r for r in rep["result"])

    def test_consolidated_statement_is_synchronous(self, api, live):
        year = __import__("datetime").date.today().year
        filters = {"company": live.company_name, "period_start_date": "{}-01-01".format(year),
                   "period_end_date": "{}-12-31".format(year), "accumulated_in_group_company": True,
                   "report": "Profit and Loss Statement"}
        rep = api.query_report(report_name="Consolidated Financial Statement", filters=filters,
                               ignore_prepared_report=True)
        assert "columns" in rep and "result" in rep, sorted(rep)


class TestFiles:
    def test_get_file_of_purchase_invoice(self, api, live):
        rows = api.get_list("Purchase Invoice", filters={"company": live.company_name, "supplier_invoice": ["is", "set"]},
                            fields=["name", "supplier_invoice"], limit_page_length=1, order_by="posting_date desc")
        if not rows:
            pytest.skip("keine Einkaufsrechnung mit PDF")
        content = api.get_file(rows[0]["supplier_invoice"])
        assert isinstance(content, bytes) and content[:4] == b"%PDF"

    def test_get_pdf_of_sales_invoice(self, api, live):
        rows = api.get_list("Sales Invoice", filters={"company": live.company_name, "docstatus": 1},
                            fields=["name"], limit_page_length=1, order_by="posting_date desc")
        if not rows:
            pytest.skip("keine gebuchte Verkaufsrechnung")
        pf = api.get_list("Print Format", filters={"doc_type": "Sales Invoice"})
        fmt = pf[0]["name"] if pf else "Standard"
        out = api.get_pdf("Sales Invoice", rows[0]["name"], fmt)
        data = out.read()
        assert data[:4] == b"%PDF", data[:200]
