"""Tests für journal.py: Buchungssätze, USt-Buchungen, Anzahlungs-Umbuchungen, Hauptbuch-Abfragen."""
from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

import journal
from company import Company
from settings import TAX_ACCOUNTS, INCOME_DIST_ACCOUNTS, PAYABLE_ACCOUNTS, RECEIVABLE_ACCOUNTS, INCOME_ACCOUNTS
from support import factories as F
from support.fakes import FakeFrappeClient
from support.stubs import UserSettings


def gl_handler(balances: dict[str, float], rows: list[dict[str, Any]] | None = None) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """General-Ledger-Report nachbilden: 'Total'-Saldo = Summe der Salden der gefilterten Konten."""
    def handler(filters: dict[str, Any]) -> dict[str, Any]:
        accounts = filters.get("account", [])
        total = sum(balances.get(a, 0.0) for a in accounts)
        result = [{"account": "'Opening'", "debit": 0, "credit": 0, "balance": 0, "posting_date": filters.get("from_date")}]
        result += [r for r in (rows or []) if r.get("account") in accounts or not accounts]
        result += [{"account": "'Total'", "debit": 0, "credit": 0, "balance": total},
                   {"account": "'Closing (Opening + Total)'", "debit": 0, "credit": 0, "balance": total,
                    "posting_date": filters.get("to_date")}]
        return {"columns": [{"fieldname": "account"}, {"fieldname": "balance"}], "result": result}
    return handler


def entry(api: FakeFrappeClient, name: str) -> dict[str, Any]:
    return api.get_doc("Journal Entry", name)


def strip_meta(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items() if k not in ("idx", "parent", "parenttype", "parentfield")} for r in rows]


class TestJournalEntry:
    def test_mirrored_accounts(self, somiko: Company, fake_api: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        j = journal.journal_entry(somiko, "Bank - SoMiKo", "4210 - Miete und Nebenkosten - SoMiKo", 0, 500.0,
                                  "Miete", "Miete August", "2026-08-01")
        assert j["doctype"] == "Journal Entry"
        assert j["voucher_type"] == "Journal Entry"
        assert j["company"] == somiko.name
        assert j["posting_date"] == "2026-08-01"
        assert j["user_remark"] == "Miete August" and j["title"] == "Miete"
        assert "cheque_no" not in j
        assert strip_meta(j["accounts"]) == [
            {"account": "Bank - SoMiKo", "cost_center": "Haupt - SoMiKo", "debit": 0, "debit_in_account_currency": 0,
             "credit": 500.0, "credit_in_account_currency": 500.0},
            {"account": "4210 - Miete und Nebenkosten - SoMiKo", "cost_center": "Haupt - SoMiKo", "debit": 500.0,
             "debit_in_account_currency": 500.0, "credit": 0, "credit_in_account_currency": 0}]
        assert j["total_debit"] == j["total_credit"] == 500.0
        assert "Buchungssatz {} erstellt".format(j["name"]) in capsys.readouterr().out

    def test_cheque_no(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        j = journal.journal_entry(somiko, "A", "B", 1.0, 0, "t", "r", "2026-01-01", cheque_no="ACC-PAY-1")
        assert j["cheque_no"] == "ACC-PAY-1" and j["cheque_date"] == "2026-01-01"

    def test_journal_entry3_positive(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        j = journal.journal_entry3(somiko, "K", "G1", "G2", 1000.0, 190.0, "t", "r", "2026-01-01")
        accs = strip_meta(j["accounts"])
        assert (accs[0]["debit"], accs[0]["credit"]) == (1190.0, 0)
        assert (accs[1]["debit"], accs[1]["credit"]) == (0, 1000.0)
        assert (accs[2]["debit"], accs[2]["credit"]) == (0, 190.0)
        assert j["total_debit"] == 1190.0

    def test_journal_entry3_negative(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        j = journal.journal_entry3(somiko, "K", "G1", "G2", -1000.0, -190.0, "t", "r", "2026-01-01")
        accs = strip_meta(j["accounts"])
        assert (accs[0]["debit"], accs[0]["credit"]) == (0, 1190.0)
        assert (accs[1]["debit"], accs[1]["credit"]) == (1000.0, 0)
        assert (accs[2]["debit"], accs[2]["credit"]) == (190.0, 0)


class TestAddParty:
    def test_string_account_unchanged(self) -> None:
        e = {"account": "Bank", "debit": 1}
        assert journal.add_party_acc(e) is e

    def test_dict_account_adds_party(self) -> None:
        e = {"account": {"account": "1600 - Verb.", "party_type": "Supplier", "party": "L"}, "debit": 10, "credit": 0}
        out = journal.add_party_acc(e)
        assert out["account"] == "1600 - Verb."
        assert out["party_type"] == "Supplier" and out["party"] == "L"
        assert "reference_type" not in out

    @pytest.mark.parametrize("ptype, debit, credit, expect_ref", [
        ("Pay", 10, 0, True), ("Pay", 0, 10, False), ("Receive", 0, 10, True), ("Receive", 10, 0, False)])
    def test_reference_to_journal_entry(self, ptype: str, debit: int, credit: int, expect_ref: bool) -> None:
        e = {"account": {"account": "A", "party_type": "Supplier", "party": "L"}, "debit": debit, "credit": credit}
        out = journal.add_party_acc(e, ("ACC-JV-1", ptype))
        if expect_ref:
            assert out["reference_type"] == "Journal Entry"
            assert out["reference_name"] == "ACC-JV-1"
            assert out["is_advance"] == "Yes"
        else:
            assert "reference_type" not in out

    def test_add_party_list(self) -> None:
        out = journal.add_party([{"account": "A"}, {"account": {"account": "B", "party_type": "C", "party": "P"}}])
        assert out[0] == {"account": "A"} and out[1]["party"] == "P"


class TestGeneralLedger:
    def test_get_gl_passes_filters(self, fake_api: FakeFrappeClient) -> None:
        fake_api.set_report("General ledger", gl_handler({"K": 5.0}))
        rows = journal.get_gl("Firma", "2026-01-01", "2026-03-31", ["K"], voucher_no="EK 1")
        assert rows[-2]["balance"] == 5.0
        filters = fake_api.calls_of("query_report")[0][1][1]
        assert filters == {"company": "Firma", "account": ["K"], "from_date": "2026-01-01", "to_date": "2026-03-31",
                           "include_default_book_entries": True, "group_by": "Group by Voucher (Consolidated)",
                           "voucher_no": "EK 1"}

    def test_get_gl_total(self, fake_api: FakeFrappeClient) -> None:
        fake_api.set_report("General ledger", gl_handler({"A": 5.0, "B": 7.0}))
        assert journal.get_gl_total("F", "2026-01-01", "2026-03-31", ["A", "B"]) == 12.0

    def test_get_gl_total_accepts_summe(self, fake_api: FakeFrappeClient) -> None:
        fake_api.set_report("General ledger", {"result": [{"account": "'Summe'", "balance": 3.0}]})
        assert journal.get_gl_total("F", "a", "b", ["A"]) == 3.0

    def test_get_gl_propagates_errors(self, fake_api: FakeFrappeClient) -> None:
        with pytest.raises(Exception):
            journal.get_gl("F", "a", "b", ["A"])

    def test_invoice_for_payment(self, fake_api: FakeFrappeClient) -> None:
        fake_api.add("Purchase Invoice", name="EK 1", posting_date="2026-02-01")
        fake_api.add("Payment Entry", name="PAY-1", references=[{"reference_doctype": "Purchase Invoice", "reference_name": "EK 1"}])
        fake_api.add("Payment Entry", name="PAY-2", references=[])
        assert journal.invoice_for_payment("PAY-1")["name"] == "EK 1"
        assert journal.invoice_for_payment("PAY-2") is None


class TestTaxJournalEntries:
    def test_creates_vorsteuer_and_umsatzsteuer(self, somiko: Company, fake_api: FakeFrappeClient,
                                                capsys: pytest.CaptureFixture[str]) -> None:
        accs = TAX_ACCOUNTS[somiko.name]
        fake_api.set_report("General ledger", gl_handler({accs["pre_tax_accounts"][0]: 190.0,
                                                          accs["tax_accounts"][0]: -380.0}))
        journal.create_tax_journal_entries(somiko.name, "2026-02")
        jes = [entry(fake_api, j["name"]) for j in fake_api.get_list("Journal Entry")]
        assert len(jes) == 2
        vst, ust = jes
        assert vst["title"] == "USt-Anmeldung 2026-02 Vorsteuer"
        assert vst["posting_date"] == "2026-06-30"
        assert vst["accounts"][0]["account"] == accs["tax_pay_account"]
        assert vst["accounts"][0]["debit"] == 190.0
        assert vst["accounts"][1]["account"] == accs["pre_tax_accounts"][0]
        assert vst["accounts"][1]["credit"] == 190.0
        assert ust["title"] == "USt-Anmeldung 2026-02 Verkaufssteuer"
        assert ust["accounts"][0]["account"] == accs["tax_accounts"][0]
        assert ust["accounts"][0]["debit"] == 380.0
        assert ust["accounts"][1]["account"] == accs["tax_pay_account"]

    def test_zero_balances_create_nothing(self, somiko: Company, fake_api: FakeFrappeClient,
                                          capsys: pytest.CaptureFixture[str]) -> None:
        fake_api.set_report("General ledger", gl_handler({}))
        journal.create_tax_journal_entries(somiko.name, "2026-02")
        assert fake_api.get_list("Journal Entry") == []
        out = capsys.readouterr().out
        assert "Keine Vorsteuer zu buchen" in out and "Keine Umsatzsteuer zu buchen" in out

    def test_unknown_company(self, fake_api: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        journal.create_tax_journal_entries("Unbekannt", "2026-02")
        assert "Keine Steuerkonten" in capsys.readouterr().out


class TestIncomeDistribution:
    def test_distribution_by_expense_ratio(self, laden: Company, fake_api: FakeFrappeClient,
                                           capsys: pytest.CaptureFixture[str]) -> None:
        d = INCOME_DIST_ACCOUNTS["Laden"]
        balances = {d["expense"][7]: 300.0, d["expense"][19]: 700.0, d["income"][0]["unclear"]: -1000.0}
        fake_api.set_report("General ledger", gl_handler(balances))
        entries = journal.create_income_dist_journal_entries("Laden", "2026-02")
        assert len(entries) == 4
        full = [entry(fake_api, e["name"]) for e in entries]
        amounts = [(e["accounts"][0]["account"], e["accounts"][1]["account"], e["accounts"][0]["debit"]) for e in full]
        assert amounts == [
            (d["income"][0]["unclear"], d["income"][0][7], 280.37),
            (d["income"][0]["unclear"], d["tax"][7], 19.63),
            (d["income"][0]["unclear"], d["income"][0][19], 588.24),
            (d["income"][0]["unclear"], d["tax"][19], 111.76)]
        assert sum(a[2] for a in amounts) == pytest.approx(1000.0)
        assert all(e["posting_date"] == "2026-06-30" for e in full)
        assert full[0]["title"] == "Aufteilung nach Steuersätzen 2026-02"
        assert "7% USt: 30.0000% Anteil" in full[0]["user_remark"]
        assert "19% USt: 70.0000% Anteil" in capsys.readouterr().out

    def test_unknown_company(self, fake_api: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        assert journal.create_income_dist_journal_entries("Firma X", "2026-01") is None
        assert "Keine Umverteilungskonten" in capsys.readouterr().out


def add_advance_payment(fake_api: FakeFrappeClient, somiko: Company, references: Iterable[dict[str, str]] = ()) -> str:
    return fake_api.add("Payment Entry", name="ACC-PAY-2026-00001", paid_amount=1190.0, company=somiko.name,
                        party_type="Supplier", party="Lieferant L", payment_type="Pay", posting_date="2026-05-01",
                        docstatus=1, references=list(references))


@pytest.fixture
def advance_payment(somiko: Company, fake_api: FakeFrappeClient) -> str:
    return add_advance_payment(fake_api, somiko)


@pytest.fixture
def advance_payment_with_invoice(somiko: Company, fake_api: FakeFrappeClient) -> str:
    fake_api.add("Purchase Invoice", name="EK 2026-00009", posting_date="2026-07-15", company=somiko.name)
    return add_advance_payment(fake_api, somiko,
                               [{"reference_doctype": "Purchase Invoice", "reference_name": "EK 2026-00009"}])


class TestAdvancePaymentJournalEntry:
    def test_umbuchung_pay(self, somiko: Company, fake_api: FakeFrappeClient, advance_payment: str,
                           capsys: pytest.CaptureFixture[str]) -> None:
        journal.create_advance_payment_journal_entry(advance_payment, 19)
        jes = fake_api.get_list("Journal Entry", fields=["name"])
        assert len(jes) == 1
        j = entry(fake_api, jes[0]["name"])
        accs = PAYABLE_ACCOUNTS[somiko.name]
        assert j["title"] == "Umbuchung Anzahlung ACC-PAY-2026-00001"
        assert j["cheque_no"] == "ACC-PAY-2026-00001" and j["cheque_date"] == "2026-05-01"
        assert j["posting_date"] == "2026-05-01"
        a = j["accounts"]
        assert a[0]["account"] == accs["post"] and a[0]["party"] == "Lieferant L" and a[0]["party_type"] == "Supplier"
        assert (a[0]["debit"], a[0]["credit"]) == (0, 1190.0)
        assert a[1]["account"] == accs["advance"] and (a[1]["debit"], a[1]["credit"]) == (1000.0, 0)
        assert a[2]["account"] == TAX_ACCOUNTS[somiko.name]["pre_tax_accounts"][0]
        assert (a[2]["debit"], a[2]["credit"]) == (190.0, 0)
        assert "reference_type" not in a[0]
        assert "Erstelle Umbuchungssatz" in capsys.readouterr().out

    def test_umbuchung_is_idempotent(self, somiko: Company, fake_api: FakeFrappeClient, advance_payment: str,
                                     capsys: pytest.CaptureFixture[str]) -> None:
        journal.create_advance_payment_journal_entry(advance_payment, 19)
        journal.create_advance_payment_journal_entry(advance_payment, 19)
        assert len(fake_api.get_list("Journal Entry")) == 1
        assert "existiert schon" in capsys.readouterr().out

    def test_umbuchung_receive(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        name = fake_api.add("Payment Entry", paid_amount=238.0, company=somiko.name, party_type="Customer",
                            party="Kunde", payment_type="Receive", posting_date="2026-05-02", docstatus=1)
        journal.create_advance_payment_journal_entry(name, 19)
        j = entry(fake_api, fake_api.get_list("Journal Entry")[0]["name"])
        accs = RECEIVABLE_ACCOUNTS[somiko.name]
        a = j["accounts"]
        assert a[0]["account"] == accs["post"] and (a[0]["debit"], a[0]["credit"]) == (238.0, 0)
        assert a[1]["account"] == accs["advance"] and (a[1]["debit"], a[1]["credit"]) == (0, 200.0)
        assert a[2]["account"] == TAX_ACCOUNTS[somiko.name]["tax_accounts"][0]
        assert (a[2]["debit"], a[2]["credit"]) == (0, 38.0)

    def test_rueckbuchung(self, somiko: Company, fake_api: FakeFrappeClient, advance_payment_with_invoice: str) -> None:
        advance_payment = advance_payment_with_invoice
        journal.create_advance_payment_journal_entry(advance_payment, 19)          # Umbuchung
        journal.create_advance_payment_journal_entry(advance_payment, 19, True)    # Rückbuchung
        jes = [entry(fake_api, j["name"]) for j in fake_api.get_list("Journal Entry")]
        assert len(jes) == 2
        um, rueck = jes
        assert rueck["title"] == "Rückbuchung Anzahlung ACC-PAY-2026-00001"
        assert rueck["posting_date"] == "2026-07-15"           # Datum der Rechnung
        assert rueck["cheque_no"] == advance_payment and rueck["cheque_date"] == "2026-07-15"
        a = rueck["accounts"]
        assert (a[0]["debit"], a[0]["credit"]) == (1190.0, 0)  # Vorzeichen gedreht
        assert a[0]["reference_type"] == "Journal Entry" and a[0]["reference_name"] == um["name"]
        assert a[0]["is_advance"] == "Yes"
        assert (a[1]["debit"], a[1]["credit"]) == (0, 1000.0) and "reference_type" not in a[1]
        assert (a[2]["debit"], a[2]["credit"]) == (0, 190.0)

    def test_rueckbuchung_without_invoice(self, somiko: Company, fake_api: FakeFrappeClient, advance_payment: str,
                                          capsys: pytest.CaptureFixture[str]) -> None:
        journal.create_advance_payment_journal_entry(advance_payment, 19, True)
        assert fake_api.get_list("Journal Entry") == []
        assert "Keine zugehörige Rechnung" in capsys.readouterr().out

    def test_rueckbuchung_without_umbuchung(self, somiko: Company, fake_api: FakeFrappeClient,
                                            advance_payment_with_invoice: str, capsys: pytest.CaptureFixture[str]) -> None:
        journal.create_advance_payment_journal_entry(advance_payment_with_invoice, 19, True)
        assert fake_api.get_list("Journal Entry") == []
        assert "Keine zugehörige Umbuchung" in capsys.readouterr().out


class TestAdvancePaymentJournalEntries:
    def _seed(self, fake_api: FakeFrappeClient, somiko: Company) -> None:
        fake_api.add("Purchase Invoice", name="EK 2026-1", posting_date="2027-01-15", company=somiko.name)
        fake_api.add("Purchase Invoice", name="EK 2026-2", posting_date="2026-03-15", company=somiko.name)
        # ohne Rechnung -> Umbuchung
        fake_api.add("Payment Entry", name="P-OHNE", paid_amount=119.0, company=somiko.name, party_type="Supplier",
                     party="L", payment_type="Pay", posting_date="2026-02-01", docstatus=1, references=[])
        # Rechnung im Folgejahr -> Umbuchung + Rückbuchung
        fake_api.add("Payment Entry", name="P-SPAET", paid_amount=119.0, company=somiko.name, party_type="Supplier",
                     party="L", payment_type="Pay", posting_date="2026-02-02", docstatus=1,
                     references=[{"reference_doctype": "Purchase Invoice", "reference_name": "EK 2026-1"}])
        # Rechnung im selben Jahr -> nichts
        fake_api.add("Payment Entry", name="P-GLEICH", paid_amount=119.0, company=somiko.name, party_type="Supplier",
                     party="L", payment_type="Pay", posting_date="2026-02-03", docstatus=1,
                     references=[{"reference_doctype": "Purchase Invoice", "reference_name": "EK 2026-2"}])
        # Entwurf -> ignoriert
        fake_api.add("Payment Entry", name="P-DRAFT", paid_amount=119.0, company=somiko.name, party_type="Supplier",
                     party="L", payment_type="Pay", posting_date="2026-02-04", docstatus=0, references=[])

    def test_year_run(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        self._seed(fake_api, somiko)
        journal.create_advance_payment_journal_entries(somiko.name, 2026)
        titles = sorted(entry(fake_api, j["name"])["title"] for j in fake_api.get_list("Journal Entry"))
        assert titles == ["Rückbuchung Anzahlung P-SPAET", "Umbuchung Anzahlung P-OHNE", "Umbuchung Anzahlung P-SPAET"]

    def test_previous_year_payments_are_ignored(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        fake_api.add("Payment Entry", name="P-ALT", paid_amount=119.0, company=somiko.name, party_type="Supplier",
                     party="L", payment_type="Pay", posting_date="2024-02-01", docstatus=1, references=[])
        journal.create_advance_payment_journal_entries(somiko.name, 2026)
        assert fake_api.get_list("Journal Entry") == []


class TestVatFunctions:
    def test_income_and_pretax(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        accs = INCOME_ACCOUNTS[somiko.name]
        balances = {accs[0][0]: -100.0, accs[0][1]: -50.0, accs[19][0]: -1000.0,
                    TAX_ACCOUNTS[somiko.name]["pre_tax_accounts"][0]: 190.0}
        fake_api.set_report("General ledger", gl_handler(balances))
        assert journal.income(somiko.name, "2026-04-01", "2026-06-30") == {0: 150.0, 19: 1000.0}
        assert journal.pretax(somiko.name, "2026-04-01", "2026-06-30") == 190.0

    def test_unconfigured_company(self, fake_api: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        assert journal.income("Colab-neu", "a", "b") == {}
        assert journal.pretax("Colab-neu", "a", "b") == 0.0
        assert journal.pretax("Soli e.V.", "a", "b") == 0.0          # konfiguriert, aber ohne Vorsteuerkonten
        assert "Keine Ertragskonten für Colab-neu" in capsys.readouterr().out
        assert fake_api.calls_of("query_report") == []

    def test_vat_declaration_skips_unconfigured_descendants(self, somiko: Company, fake_api: FakeFrappeClient,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
        fake_api.add("Company", **F.company_doc())
        fake_api.add("Company", **dict(F.company_doc("Colab-neu", "CN"), parent_company=somiko.name))
        Company(F.company_doc("Colab-neu", "CN"))     # somiko ist schon registriert, init_companies lädt nicht mehr
        fake_api.set_report("General ledger", gl_handler({INCOME_ACCOUNTS[somiko.name][19][0]: -500.0}))
        journal.vat_declaration(somiko.name, "2026-02")
        out = capsys.readouterr().out
        assert "Keine Ertragskonten für Colab-neu" in out and "19 : 500.00" in out

    def test_pretax_details_only_purchase_invoices(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        acc = TAX_ACCOUNTS[somiko.name]["pre_tax_accounts"][0]
        rows = [{"account": acc, "voucher_type": "Purchase Invoice", "voucher_no": "EK 1", "debit": 19.0, "credit": 0},
                {"account": acc, "voucher_type": "Journal Entry", "voucher_no": "JV 1", "debit": 5.0, "credit": 0},
                {"account": acc, "voucher_type": "Purchase Invoice", "voucher_no": "EK 2", "debit": 0, "credit": 3.8}]
        fake_api.set_report("General ledger", gl_handler({}, rows))
        assert journal.pretax_details(somiko.name, "a", "b") == [("EK 1", acc, 19.0), ("EK 2", acc, -3.8)]

    def test_save_pretax_details(self, somiko: Company, fake_api: FakeFrappeClient, in_tmp_cwd: Path) -> None:
        acc = TAX_ACCOUNTS[somiko.name]["pre_tax_accounts"][0]
        rows = [{"account": acc, "voucher_type": "Purchase Invoice", "voucher_no": "EK 2026-00001", "debit": 19.0, "credit": 0}]
        fake_api.set_report("General ledger", gl_handler({}, rows))
        fake_api.add("Purchase Invoice", name="EK 2026-00001", supplier_invoice="/private/files/r.pdf")
        fake_api.add_file("/private/files/r.pdf", b"%PDF-1.4 test")
        d = journal.save_pretax_details(somiko.name, "2026-02")
        assert d == "Vorsteuer-Bremer_SolidarStrom-2026-02"
        csv_text = (in_tmp_cwd / d / "EK-Rechnungen-Bremer_SolidarStrom-2026-02.csv").read_text()
        assert csv_text.splitlines()[0] == "Rechnungsnr.;Steuersatz;Vorsteuer"
        assert "EK_2026-00001;19;19,0" in csv_text
        assert csv_text.splitlines()[-1] == "Summe;;19,0"
        assert (in_tmp_cwd / d / "EK_2026-00001.pdf").read_bytes() == b"%PDF-1.4 test"

    def test_vat_declaration_prints_summary(self, somiko: Company, fake_api: FakeFrappeClient,
                                            capsys: pytest.CaptureFixture[str]) -> None:
        fake_api.add("Company", **F.company_doc())
        fake_api.set_report("General ledger", gl_handler({INCOME_ACCOUNTS[somiko.name][19][0]: -1000.0,
                                                          TAX_ACCOUNTS[somiko.name]["pre_tax_accounts"][0]: 42.0}))
        journal.vat_declaration(somiko.name, "2026-02")
        out = capsys.readouterr().out
        assert "Umsätze" in out and "Vorsteuer" in out
        assert "19 : 1000.00" in out
        assert "Summe : 42.00" in out

    def test_save_purchase_invoices(self, somiko: Company, fake_api: FakeFrappeClient, in_tmp_cwd: Path,
                                    user_settings: UserSettings, capsys: pytest.CaptureFixture[str]) -> None:
        user_settings["-year-"] = 2026
        acc = "4210 - Miete und Nebenkosten - SoMiKo"
        rows = [{"account": acc, "voucher_type": "Purchase Invoice", "voucher_no": "EK 2026-00001"},
                {"account": acc, "voucher_type": "Purchase Invoice", "voucher_no": "EK 2026-00002"},
                {"account": acc, "voucher_type": "Journal Entry", "voucher_no": "ACC-JV-1"}]
        fake_api.set_report("General ledger", gl_handler({}, rows))
        fake_api.add("Purchase Invoice", name="EK 2026-00001", supplier_invoice="/private/files/r.pdf")
        fake_api.add("Purchase Invoice", name="EK 2026-00002")   # ohne PDF -> Fehler wird gemeldet
        fake_api.add_file("/private/files/r.pdf", b"%PDF-1.4 test")
        d = journal.save_purchase_invoices(somiko.name, acc)
        assert d == "EK-Rechnungen-Bremer_SolidarStrom-2026-4210"
        assert sorted(os.listdir(in_tmp_cwd / d)) == ["EK_2026-00001.pdf"]
        out = capsys.readouterr().out
        assert "supplier_invoice" in out           # KeyError der zweiten Rechnung wird ausgegeben
        assert "Expoertiert nach " + d in out
