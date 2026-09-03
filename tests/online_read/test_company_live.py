"""company.Company against real data: master data, open documents, invoice lists."""
from __future__ import annotations

from typing import Any

import pytest

from company import Company
from frappeclient import FrappeException
from invoice import Invoice
from support.live import LiveState


class TestCompanyData:
    def test_companies_loaded(self, live: LiveState) -> None:
        assert set(Company.all()) == set(live.companies)
        assert Company.get_company(live.company_name) is live.company

    def test_load_data_taxes(self, comp: Company) -> None:
        if not comp.pre_tax_templates():
            pytest.skip("Firma hat keine Vorsteuer-Vorlagen")
        assert comp.taxes, "keine Steuersätze aus den Vorsteuer-Vorlagen gelesen"
        assert comp.default_vat in comp.taxes
        assert all(isinstance(rate, (int, float)) for rate in comp.taxes)
        assert all(acc.endswith(" - " + comp.doc["abbr"]) for acc in comp.taxes.values())

    def test_accounts(self, comp: Company) -> None:
        assert comp.accounts and all(a["company"] == comp.name for a in comp.accounts)
        assert all(a["is_group"] == 0 for a in comp.leaf_accounts)
        assert set(comp.leaf_accounts_by_root_type) <= {"Asset", "Liability", "Equity", "Income", "Expense"}
        assert len(comp.leaf_accounts_for_debit) == len(comp.leaf_accounts) == len(comp.leaf_accounts_for_credit)
        if "Income" in comp.leaf_accounts_by_root_type:
            assert comp.leaf_accounts_for_debit[0]["root_type"] == "Income"
        if "Expense" in comp.leaf_accounts_by_root_type:
            assert comp.leaf_accounts_for_credit[0]["root_type"] == "Expense"

    def test_company_attributes_from_full_doc(self, comp: Company) -> None:
        full = comp.doc
        assert full["name"] == comp.name
        assert comp.payable_account == full["default_payable_account"]
        assert comp.receivable_account == full["default_receivable_account"]
        assert comp.cost_center == full.get("cost_center")
        assert comp.payable_account and comp.receivable_account, "Firma ohne Standard-Verbindlichkeiten-/Forderungskonto"

    def test_journal_rows(self, comp: Company) -> None:
        for je in comp.journal:
            assert je["idx"] == 2 and je["company"] == comp.name and "account" in je

    def test_purchase_invoices_grouped_by_supplier(self, comp: Company) -> None:
        for supplier, pis in comp.purchase_invoices.items():
            assert all(pi["supplier"] == supplier and pi["company"] == comp.name for pi in pis)

    def test_descendants(self, comp: Company) -> None:
        names = Company.descendants_by_name(comp.name)
        assert names[0] == comp.name and set(names) <= set(Company.all())


class TestInvoiceLists:
    def test_open_purchase_invoices(self, comp: Company) -> None:
        invs = comp.get_purchase_invoices(True)
        for inv in invs:
            assert isinstance(inv, Invoice) and not inv.is_sales
            assert inv.outstanding != 0 and inv.company_name == comp.name
            assert inv.status in ("Draft", "Unpaid", "Overdue", "Partly Paid", "Return")
            assert inv.party_type == "Supplier"

    def test_paid_sales_invoices(self, comp: Company) -> None:
        invs = comp.get_sales_invoices(False)
        for inv in invs[:50]:
            assert inv.status == "Paid" and inv.is_sales and inv.party_type == "Customer"
            assert inv.reference == inv.name

    def test_get_invoices_combines(self, comp: Company) -> None:
        both = comp.get_invoices(True)
        assert len(both) == len(comp.get_purchase_invoices(True)) + len(comp.get_sales_invoices(True))


class TestOpenDocuments:
    def test_open_bank_transactions(self, comp: Company) -> None:
        for bt in comp.open_bank_transactions():
            assert bt["status"] == "Pending" and bt["unallocated_amount"] > 0 and bt["company"] == comp.name
            assert set(bt) >= {"name", "deposit", "withdrawal", "date", "description", "bank_account"}

    def test_open_journal_entries(self, comp: Company, api: Any) -> None:
        jes = comp.open_journal_entries()
        for je in jes[:3]:
            assert api.get_doc("Journal Entry", je["name"])["docstatus"] == 0

    def test_payment_entries(self, comp: Company) -> None:
        for pe in comp.unbooked_payment_entries():
            assert set(pe) >= {"name", "payment_type", "unallocated_amount", "paid_amount", "party", "posting_date"}
        for pe in comp.unassigned_payment_entries():
            assert pe["unallocated_amount"] > 0

    def test_pre_tax_templates(self, comp: Company, api: Any) -> None:
        for t in comp.pre_tax_templates():
            assert api.get_doc("Purchase Taxes and Charges Template", t["name"])["company"] == comp.name

    def test_open_pre_invoices(self, comp: Company, live: LiveState) -> None:
        if not live.doctype_exists("PreRechnung"):
            pytest.skip("DocType PreRechnung fehlt auf der Instanz")
        for advance in (False, True):
            pres = comp.get_open_pre_invoices(advance)
            assert pres is not None, "Feldliste von get_open_pre_invoices passt nicht zum DocType PreRechnung"
            for pr in pres:
                assert pr["eingepflegt"] == 0 and pr["company"] == comp.name if "company" in pr else True
                assert pr["typ"] == ("Anzahlungsrechnung" if advance else "Rechnung")
