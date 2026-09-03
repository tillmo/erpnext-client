"""Tests für company.Company mit FakeFrappeClient."""
import pytest

import bank
import company
from api import Api
from company import Company
from support import factories as F


class TestRegistry:
    def test_init_registers_and_reads_defaults(self, fake_api):
        comp = Company(F.company_doc())
        assert Company.get_company(F.COMPANY) is comp
        assert Company.all() == [F.COMPANY]
        assert comp.cost_center == "Haupt - SoMiKo"
        assert comp.payable_account.startswith("1600")
        assert comp.receivable_account.startswith("1400")
        assert comp.expense_account.startswith("4996")
        assert comp.default_finance_book is None
        assert comp.taxes == {} and comp.default_vat is None
        assert comp.data_loaded is False
        assert comp.erpnext is True

    def test_get_company_unknown(self, fake_api):
        assert Company.get_company("gibt es nicht") is None

    def test_clear(self, fake_api):
        Company(F.company_doc())
        Company.clear_companies()
        assert Company.all() == []

    def test_init_companies_from_server(self, fake_api):
        fake_api.add("Company", **F.company_doc("A", "A"))
        fake_api.add("Company", **F.company_doc("B", "B"))
        Company.init_companies()
        assert set(Company.all()) == {"A", "B"}
        Company.init_companies()  # zweiter Aufruf lädt nicht erneut
        assert len(fake_api.calls_of("get_list")) == 1

    def test_init_companies_fills_accounts(self, fake_api):
        F.seed_company_data(fake_api)
        Company.init_companies()
        comp = Company.get_company(F.COMPANY)
        assert comp.cost_center == "Haupt - SoMiKo"          # schon aus get_list(fields=Company.FIELDS)
        assert comp.payable_account.startswith("1600") and comp.receivable_account.startswith("1400")
        comp.load_data()
        assert comp.cost_center == "Haupt - SoMiKo" and comp.expense_account.startswith("4996")


class TestLeafAccounts:
    def test_starting_with_root_type_puts_that_type_first(self, somiko):
        debit = somiko.leaf_accounts_for_debit
        credit = somiko.leaf_accounts_for_credit
        assert debit[0]["root_type"] == "Income"
        assert credit[0]["root_type"] == "Expense"
        assert len(debit) == len(credit) == len(somiko.leaf_accounts)
        assert all(acc["is_group"] == 0 for acc in debit)
        assert {a["name"] for a in debit} == {a["name"] for a in credit}


@pytest.fixture
def seeded(fake_api):
    F.seed_company_data(fake_api)
    year = fake_api.year
    fake_api.add("Journal Entry", company=F.COMPANY, posting_date="2026-08-01", user_remark="Miete August",
                 title="Miete", total_debit=500.0, total_credit=500.0, docstatus=1,
                 accounts=[{"account": "Bank - SoMiKo", "credit_in_account_currency": 500.0, "debit_in_account_currency": 0.0,
                            "cost_center": "Haupt - SoMiKo"},
                           {"account": "4210 - Miete und Nebenkosten - SoMiKo", "debit_in_account_currency": 500.0,
                            "credit_in_account_currency": 0.0, "cost_center": "Haupt - SoMiKo"}])
    fake_api.add("Journal Entry", company="Andere", posting_date="2026-08-02", user_remark="fremd",
                 accounts=[{"account": "X"}, {"account": "Y"}])
    fake_api.add("Purchase Invoice", company=F.COMPANY, supplier="Krannich Solar GmbH & Co KG", posting_date="2026-07-01",
                 bill_no="41234567", grand_total=1309.0, total=1100.0, status="Paid", outstanding_amount=0.0,
                 items=[{"item_code": "000.000.000", "expense_account": "4996 - Herstellungskosten - SoMiKo"},
                        {"item_code": "000.000.000", "expense_account": "3800 - Bezugsnebenkosten - SoMiKo"}])
    fake_api.add("Purchase Invoice", company=F.COMPANY, supplier="Heckert Solar GmbH", posting_date="2026-07-02",
                 bill_no="RE-1", grand_total=100.0, total=84.03, status="Unpaid", outstanding_amount=100.0,
                 items=[{"item_code": "000.000.000", "expense_account": "4996 - Herstellungskosten - SoMiKo"}])
    return fake_api


class TestLoadData:
    def test_load_data(self, seeded, capsys):
        Company.init_companies()
        comp = Company.get_company(F.COMPANY)
        comp.load_data()
        assert comp.taxes == F.TAXES_SOMIKO
        assert comp.default_vat == 19.0
        assert comp.data_loaded is True
        assert {a["company"] for a in comp.accounts} == {F.COMPANY}
        assert all(a["is_group"] == 0 for a in comp.leaf_accounts)
        assert "Income" in comp.leaf_accounts_by_root_type
        assert comp.leaf_accounts_for_debit[0]["root_type"] == "Income"
        assert comp.leaf_accounts_for_credit[0]["root_type"] == "Expense"
        # Journal: nur die zweite Kontozeile (idx 2) jedes Buchungssatzes, nur eigene Firma
        assert [j["account"] for j in comp.journal] == ["4210 - Miete und Nebenkosten - SoMiKo"]
        assert comp.journal[0]["user_remark"] == "Miete August"
        # Einkaufsrechnungen nach Lieferant gruppiert, eine Zeile pro Artikelzeile (JOIN)
        assert set(comp.purchase_invoices) == {"Krannich Solar GmbH & Co KG", "Heckert Solar GmbH"}
        assert len(comp.purchase_invoices["Krannich Solar GmbH & Co KG"]) == 2
        assert {pi["expense_account"] for pi in comp.purchase_invoices["Krannich Solar GmbH & Co KG"]} == \
            {"4996 - Herstellungskosten - SoMiKo", "3800 - Bezugsnebenkosten - SoMiKo"}
        assert "Lade Daten für " + F.COMPANY in capsys.readouterr().out

    def test_load_data_only_once(self, seeded):
        Company.init_companies()
        comp = Company.get_company(F.COMPANY)
        comp.load_data()
        n = len(seeded.calls)
        comp.load_data()
        assert len(seeded.calls) == n

    def test_current_load_data_uses_setting(self, seeded, user_settings):
        Company.init_companies()
        user_settings["-company-"] = F.COMPANY
        Company.current_load_data()
        assert Company.get_company(F.COMPANY).data_loaded is True

    def test_current_load_data_without_company(self, seeded, user_settings):
        Company.init_companies()
        user_settings["-company-"] = None
        Company.current_load_data()
        assert Company.get_company(F.COMPANY).data_loaded is False


class TestQueries:
    def test_get_invoices_of_type(self, somiko, fake_api):
        fake_api.add("Purchase Invoice", company=somiko.name, supplier="A", bill_no="1", status="Unpaid",
                     posting_date="2026-01-01", grand_total=100.0, outstanding_amount=100.0, is_return=0)
        fake_api.add("Purchase Invoice", company=somiko.name, supplier="B", bill_no="2", status="Overdue",
                     posting_date="2026-01-02", grand_total=50.0, outstanding_amount=0.0, is_return=0)
        fake_api.add("Purchase Invoice", company=somiko.name, supplier="C", bill_no="3", status="Paid",
                     posting_date="2026-01-03", grand_total=70.0, outstanding_amount=0.0, is_return=0)
        fake_api.add("Purchase Invoice", company="Andere", supplier="D", bill_no="4", status="Unpaid",
                     posting_date="2026-01-04", grand_total=70.0, outstanding_amount=70.0, is_return=0)
        fake_api.add("Sales Invoice", company=somiko.name, customer="K", status="Unpaid", custom_ebay=0,
                     posting_date="2026-01-05", grand_total=200.0, outstanding_amount=200.0, is_return=0)
        open_p = somiko.get_purchase_invoices(True)
        assert [inv.reference for inv in open_p] == ["1"]   # offene ohne ausstehenden Betrag fallen weg
        assert open_p[0].amount == -100.0 and open_p[0].party == "A"
        paid = somiko.get_purchase_invoices(False)
        assert [inv.reference for inv in paid] == ["3"]
        sales = somiko.get_sales_invoices(True)
        assert [inv.party for inv in sales] == ["K"]
        assert sales[0].reference == sales[0].name
        assert len(somiko.get_invoices(True)) == 2

    def test_open_pre_invoices(self, somiko, fake_api):
        fake_api.add("PreRechnung", company=somiko.name, eingepflegt=False, typ="Rechnung", datum="2026-01-01",
                     lieferant="A", pdf="/private/files/a.pdf")
        fake_api.add("PreRechnung", company=somiko.name, eingepflegt=False, typ="Anzahlungsrechnung", datum="2026-01-02")
        fake_api.add("PreRechnung", company=somiko.name, eingepflegt=True, typ="Rechnung", datum="2026-01-03")
        fake_api.add("PreRechnung", company="Andere", eingepflegt=False, typ="Rechnung", datum="2026-01-04")
        pre = somiko.get_open_pre_invoices(False)
        assert len(pre) == 1 and pre[0]["lieferant"] == "A"
        assert set(pre[0]) >= {"datum", "name", "chance", "lieferant", "pdf", "json", "lager", "selbst_bezahlt",
                               "vom_konto_überwiesen", "typ", "processed", "balkonmodule", "buchungskonto",
                               "nuruk", "nurelektromaterial"}
        assert len(somiko.get_open_pre_invoices(True)) == 1

    def test_open_documents(self, somiko, fake_api):
        fake_api.add("Bank Transaction", company=somiko.name, status="Pending", unallocated_amount=10.0,
                     deposit=10.0, withdrawal=0.0, date="2026-01-01", bank_account="B", description="x")
        fake_api.add("Bank Transaction", company=somiko.name, status="Pending", unallocated_amount=0.0,
                     deposit=10.0, withdrawal=0.0, date="2026-01-01", bank_account="B", description="voll")
        fake_api.add("Bank Transaction", company=somiko.name, status="Reconciled", unallocated_amount=5.0,
                     deposit=10.0, withdrawal=0.0, date="2026-01-01", bank_account="B", description="y")
        fake_api.add("Journal Entry", company=somiko.name, docstatus=0, accounts=[])
        fake_api.add("Journal Entry", company=somiko.name, docstatus=1, accounts=[])
        fake_api.add("Payment Entry", company=somiko.name, docstatus=0, payment_type="Pay", paid_amount=1.0,
                     unallocated_amount=1.0, party="P", posting_date="2026-01-01")
        fake_api.add("Payment Entry", company=somiko.name, docstatus=1, payment_type="Pay", paid_amount=1.0,
                     unallocated_amount=1.0, party="P", posting_date="2026-01-01")
        fake_api.add("Payment Entry", company=somiko.name, docstatus=1, payment_type="Pay", paid_amount=1.0,
                     unallocated_amount=0.0, party="P", posting_date="2026-01-01")
        fake_api.add("Purchase Taxes and Charges Template", name="T1", company=somiko.name)
        assert [bt["description"] for bt in somiko.open_bank_transactions()] == ["x"]
        assert len(somiko.open_journal_entries()) == 1
        assert len(somiko.unbooked_payment_entries()) == 1
        unassigned = somiko.unassigned_payment_entries()
        assert len(unassigned) == 1 and unassigned[0]["unallocated_amount"] == 1.0
        assert somiko.pre_tax_templates() == [{"name": "T1"}]

    def test_descendants(self, fake_api):
        fake_api.add("Company", **F.company_doc("Mutter", "M"))
        fake_api.add("Company", **dict(F.company_doc("Kind", "K"), parent_company="Mutter"))
        fake_api.add("Company", **dict(F.company_doc("Enkel", "E"), parent_company="Kind"))
        fake_api.add("Company", **F.company_doc("Fremd", "F"))
        Company.init_companies()
        assert Company.descendants_by_name("Mutter") == ["Mutter", "Kind", "Enkel"]
        assert Company.descendants_by_name("Fremd") == ["Fremd"]


class TestReconcile:
    def test_reconcile_all_only_pending_without_payments(self, somiko, fake_api, monkeypatch):
        bacc = F.make_bank_account(fake_api, somiko)
        fake_api.add("Bank Transaction", **F.bank_transaction_doc(bacc.name, deposit=10.0, description="offen"))
        fake_api.add("Bank Transaction", **F.bank_transaction_doc(bacc.name, deposit=10.0, description="verknüpft",
                                                                  payment_entries=[{"payment_entry": "X"}]))
        fake_api.add("Bank Transaction", **F.bank_transaction_doc(bacc.name, deposit=10.0, description="fertig",
                                                                  status="Reconciled"))
        seen = []
        monkeypatch.setattr(bank.BankTransaction, "transfer", lambda self, s, p: seen.append(self.description))
        somiko.reconcile_all()
        assert seen == ["offen"]

    def test_reconcile_swaps_return_invoices(self, somiko, fake_api, monkeypatch):
        bacc = F.make_bank_account(fake_api, somiko)
        name = fake_api.add("Bank Transaction", **F.bank_transaction_doc(bacc.name, deposit=10.0))
        fake_api.add("Purchase Invoice", company=somiko.name, supplier="A", bill_no="1", status="Return",
                     posting_date="2026-01-01", grand_total=-100.0, outstanding_amount=-100.0, is_return=1)
        fake_api.add("Sales Invoice", company=somiko.name, customer="K", status="Unpaid", custom_ebay=0,
                     posting_date="2026-01-05", grand_total=200.0, outstanding_amount=200.0, is_return=0)
        seen = {}

        def transfer(self, sinvs, pinvs):
            seen["s"] = [i.reference for i in sinvs]
            seen["p"] = [i.reference for i in pinvs]
        monkeypatch.setattr(bank.BankTransaction, "transfer", transfer)
        somiko.reconcile({"name": name})
        # die Einkaufs-Gutschrift wandert auf die Verkaufsseite
        assert seen["s"] == [fake_api.get_list("Sales Invoice")[0]["name"], "1"]
        assert seen["p"] == []
