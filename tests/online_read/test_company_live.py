"""company.Company gegen echte Daten: Stammdaten, offene Dokumente, Rechnungslisten."""
import pytest

from company import Company
from frappeclient import FrappeException
from invoice import Invoice


class TestCompanyData:
    def test_companies_loaded(self, live):
        assert set(Company.all()) == set(live.companies)
        assert Company.get_company(live.company_name) is live.company

    def test_load_data_taxes(self, comp):
        if not comp.pre_tax_templates():
            pytest.skip("Firma hat keine Vorsteuer-Vorlagen")
        assert comp.taxes, "keine Steuersätze aus den Vorsteuer-Vorlagen gelesen"
        assert comp.default_vat in comp.taxes
        assert all(isinstance(rate, (int, float)) for rate in comp.taxes)
        assert all(acc.endswith(" - " + comp.doc["abbr"]) for acc in comp.taxes.values())

    def test_accounts(self, comp):
        assert comp.accounts and all(a["company"] == comp.name for a in comp.accounts)
        assert all(a["is_group"] == 0 for a in comp.leaf_accounts)
        assert set(comp.leaf_accounts_by_root_type) <= {"Asset", "Liability", "Equity", "Income", "Expense"}
        assert len(comp.leaf_accounts_for_debit) == len(comp.leaf_accounts) == len(comp.leaf_accounts_for_credit)
        if "Income" in comp.leaf_accounts_by_root_type:
            assert comp.leaf_accounts_for_debit[0]["root_type"] == "Income"
        if "Expense" in comp.leaf_accounts_by_root_type:
            assert comp.leaf_accounts_for_credit[0]["root_type"] == "Expense"

    def test_company_attributes_from_full_doc(self, comp):
        # Dokumentiert den Befund aus test_company.py: init_companies liefert nur 'name'
        full = comp.doc
        assert full["name"] == comp.name
        if comp.cost_center is None:
            pytest.xfail("cost_center/payable_account werden aus get_list('Company') nicht befüllt (nur 'name')")

    def test_journal_rows(self, comp):
        for je in comp.journal:
            assert je["idx"] == 2 and je["company"] == comp.name and "account" in je

    def test_purchase_invoices_grouped_by_supplier(self, comp):
        for supplier, pis in comp.purchase_invoices.items():
            assert all(pi["supplier"] == supplier and pi["company"] == comp.name for pi in pis)

    def test_descendants(self, comp):
        names = Company.descendants_by_name(comp.name)
        assert names[0] == comp.name and set(names) <= set(Company.all())


class TestInvoiceLists:
    def test_open_purchase_invoices(self, comp):
        invs = comp.get_purchase_invoices(True)
        for inv in invs:
            assert isinstance(inv, Invoice) and not inv.is_sales
            assert inv.outstanding != 0 and inv.company_name == comp.name
            assert inv.status in ("Draft", "Unpaid", "Overdue", "Partly Paid", "Return")
            assert inv.party_type == "Supplier"

    def test_paid_sales_invoices(self, comp):
        invs = comp.get_sales_invoices(False)
        for inv in invs[:50]:
            assert inv.status == "Paid" and inv.is_sales and inv.party_type == "Customer"
            assert inv.reference == inv.name

    def test_get_invoices_combines(self, comp):
        both = comp.get_invoices(True)
        assert len(both) == len(comp.get_purchase_invoices(True)) + len(comp.get_sales_invoices(True))


class TestOpenDocuments:
    def test_open_bank_transactions(self, comp):
        for bt in comp.open_bank_transactions():
            assert bt["status"] == "Pending" and bt["unallocated_amount"] > 0 and bt["company"] == comp.name
            assert set(bt) >= {"name", "deposit", "withdrawal", "date", "description", "bank_account"}

    def test_open_journal_entries(self, comp, api):
        jes = comp.open_journal_entries()
        for je in jes[:3]:
            assert api.get_doc("Journal Entry", je["name"])["docstatus"] == 0

    def test_payment_entries(self, comp):
        for pe in comp.unbooked_payment_entries():
            assert set(pe) >= {"name", "payment_type", "unallocated_amount", "paid_amount", "party", "posting_date"}
        for pe in comp.unassigned_payment_entries():
            assert pe["unallocated_amount"] > 0

    def test_pre_tax_templates(self, comp, api):
        for t in comp.pre_tax_templates():
            assert api.get_doc("Purchase Taxes and Charges Template", t["name"])["company"] == comp.name

    def test_open_pre_invoices(self, comp, live):
        if not live.doctype_exists("PreRechnung"):
            pytest.skip("DocType PreRechnung fehlt auf der Instanz")
        for advance in (False, True):
            pres = comp.get_open_pre_invoices(advance)
            assert pres is not None, "Feldliste von get_open_pre_invoices passt nicht zum DocType PreRechnung"
            for pr in pres:
                assert pr["eingepflegt"] == 0 and pr["company"] == comp.name if "company" in pr else True
                assert pr["typ"] == ("Anzahlungsrechnung" if advance else "Rechnung")
