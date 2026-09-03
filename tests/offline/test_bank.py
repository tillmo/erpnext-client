"""Tests for bank.py: bank accounts, bank transactions, bank statement import (offline)."""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import pytest

import bank
import invoice
import utils
from company import Company
from support import factories as F
from support.fakes import FakeFrappeClient
from support.stubs import EasyguiStub, GuiCalled, UserSettings


@pytest.fixture
def bacc(somiko: Company, fake_api: FakeFrappeClient) -> bank.BankAccount:
    return F.make_bank_account(fake_api, somiko)


def add_bt(fake_api: FakeFrappeClient, bacc: bank.BankAccount, **kw: Any) -> dict[str, Any]:
    name = fake_api.add("Bank Transaction", **F.bank_transaction_doc(bacc.name, company=bacc.company.name, **kw))
    return fake_api.get_doc("Bank Transaction", name)


class TestBankAccount:
    def test_init_registers_and_computes_balance(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        fake_api.add("Bank Transaction", **F.bank_transaction_doc("Sparkasse Bremen - SoMiKo", deposit=100.0))
        fake_api.add("Bank Transaction", **F.bank_transaction_doc("Sparkasse Bremen - SoMiKo", withdrawal=30.0))
        fake_api.add("Bank Transaction", **F.bank_transaction_doc("Sparkasse Bremen - SoMiKo", withdrawal=999.0,
                                                                  status="Cancelled"))
        fake_api.add("Bank Transaction", **F.bank_transaction_doc("Sparkasse Bremen - SoMiKo", withdrawal=999.0,
                                                                  docstatus=2))
        fake_api.add("Bank Transaction", **F.bank_transaction_doc("Anderes Konto", withdrawal=999.0))
        b = F.make_bank_account(fake_api, somiko)
        assert b.balance == 70.0
        assert b.blz() == "29050101"
        assert b.e_account == "Bank - SoMiKo"
        assert b.company is somiko
        assert b.statement_balance is None
        assert bank.BankAccount.baccounts_by_iban[F.IBAN_SPARKASSE] is b
        assert bank.BankAccount.baccounts_by_name[b.name] is b
        assert bank.BankAccount.baccounts_by_company[somiko.name] == [b]

    def test_init_baccounts_from_server(self, somiko: Company, fake_api: FakeFrappeClient, user_settings: UserSettings) -> None:
        fake_api.add("Bank Account", **F.bank_account_doc())
        fake_api.add("Bank Account", **F.bank_account_doc(name="Sparda - SoMiKo", iban=F.IBAN_SPARDA))
        bank.BankAccount.init_baccounts()
        assert set(bank.BankAccount.baccounts_by_name) == {"Sparkasse Bremen - SoMiKo", "Sparda - SoMiKo"}
        assert sorted(bank.BankAccount.get_baccount_names()) == ["Sparda - SoMiKo", "Sparkasse Bremen - SoMiKo"]
        bank.BankAccount.init_baccounts()      # no second load
        assert len(fake_api.calls_of("get_list")) == 3   # 1x accounts, 2x balances

    def test_init_baccounts_skipped_during_setup(self, fake_api: FakeFrappeClient, user_settings: UserSettings) -> None:
        user_settings["-setup-"] = True
        fake_api.add("Bank Account", **F.bank_account_doc())
        bank.BankAccount.init_baccounts()
        assert bank.BankAccount.baccounts_by_name == {}

    def test_clear(self, bacc: bank.BankAccount) -> None:
        bank.BankAccount.clear_baccounts()
        assert bank.BankAccount.baccounts_by_iban == {}
        assert bank.BankAccount.baccounts_by_company["x"] == []


class TestBankTransactionBasics:
    def test_init_deposit(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient) -> None:
        doc = add_bt(fake_api, bacc, deposit=100.0, description="Kunde zahlt")
        bt = bank.BankTransaction(doc)
        assert bt.amount == 100.0 and bt.deposit == 100.0 and bt.withdrawal == 0.0
        assert bt.baccount is bacc and bt.company is bacc.company
        assert bt.description == "Kunde zahlt"
        assert bt.show() == "{} 15.08.2026\nKunde zahlt\n100.00€".format(doc["name"])

    def test_init_withdrawal_without_description(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient) -> None:
        doc = add_bt(fake_api, bacc, withdrawal=25.5)
        del doc["description"]
        bt = bank.BankTransaction(doc)
        assert bt.amount == -25.5 and bt.description == ""

    def test_link_to(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient) -> None:
        doc = add_bt(fake_api, bacc, deposit=100.0)
        del doc["payment_entries"]
        bt = bank.BankTransaction(doc)
        bt.link_to("Journal Entry", "JV-1", 40.0)
        assert bt.doc["payment_entries"] == [{"payment_document": "Journal Entry", "payment_entry": "JV-1",
                                              "allocated_amount": 40.0}]
        assert bt.doc["unallocated_amount"] == 60.0 and bt.doc["allocated_amount"] == 40.0
        assert bt.doc["status"] == "Pending"
        bt.link_to("Payment Entry", "PAY-1", 60.0)
        assert bt.doc["status"] == "Reconciled"
        assert len(bt.doc["payment_entries"]) == 2


class TestBankTransactionBooking:
    def test_journal_entry_against_account(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient,
                                           user_settings: UserSettings) -> None:
        doc = add_bt(fake_api, bacc, deposit=100.0, description="Spende")
        bt = bank.BankTransaction(doc)
        bt.journal_entry("8401 - Selbstbauanlagen 19% - SoMiKo", False)
        jes = fake_api.get_list("Journal Entry", fields=["name", "docstatus"])
        assert len(jes) == 1 and jes[0]["docstatus"] == 0
        j = fake_api.get_doc("Journal Entry", jes[0]["name"])
        assert j["accounts"][0]["account"] == "Bank - SoMiKo" and j["accounts"][0]["debit"] == 100.0
        assert j["accounts"][1]["account"] == "8401 - Selbstbauanlagen 19% - SoMiKo" and j["accounts"][1]["credit"] == 100.0
        assert j["user_remark"] == "Spende" and j["posting_date"] == "2026-08-15"
        stored = fake_api.get_doc("Bank Transaction", doc["name"])
        assert stored["status"] == "Reconciled" and stored["unallocated_amount"] == 0
        assert stored["payment_entries"][0]["payment_entry"] == jes[0]["name"]
        assert bacc.company.journal[-1]["account"] == "8401 - Selbstbauanlagen 19% - SoMiKo"

    def test_journal_entry_withdrawal_with_buchen(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient,
                                                  user_settings: UserSettings, capsys: pytest.CaptureFixture[str]) -> None:
        user_settings["-buchen-"] = True
        doc = add_bt(fake_api, bacc, withdrawal=50.0, description="Miete")
        bank.BankTransaction(doc).journal_entry("4210 - Miete und Nebenkosten - SoMiKo", False)
        j = fake_api.get_doc("Journal Entry", fake_api.get_list("Journal Entry")[0]["name"])
        assert j["docstatus"] == 1
        assert j["accounts"][0]["credit"] == 50.0 and j["accounts"][1]["debit"] == 50.0
        assert "gebucht" in capsys.readouterr().out

    def test_journal_entry_between_bank_accounts(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient,
                                                 somiko: Company) -> None:
        other = F.make_bank_account(fake_api, somiko, name="Sparda - SoMiKo", iban=F.IBAN_SPARDA, account="Bank2 - SoMiKo")
        doc = add_bt(fake_api, bacc, withdrawal=200.0, description="Umbuchung")
        other_doc = add_bt(fake_api, other, deposit=200.0, description="Umbuchung")
        bank.BankTransaction(doc).journal_entry(other_doc, True)
        j = fake_api.get_doc("Journal Entry", fake_api.get_list("Journal Entry")[0]["name"])
        assert j["accounts"][0]["account"] == "Bank - SoMiKo" and j["accounts"][0]["credit"] == 200.0
        assert j["accounts"][1]["account"] == "Bank2 - SoMiKo" and j["accounts"][1]["debit"] == 200.0
        for name in (doc["name"], other_doc["name"]):
            stored = fake_api.get_doc("Bank Transaction", name)
            assert stored["status"] == "Reconciled"
            assert stored["payment_entries"][0]["payment_entry"] == j["name"]

    def test_payment_for_invoice_limits_to_outstanding(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient,
                                                       somiko: Company) -> None:
        doc = add_bt(fake_api, bacc, withdrawal=500.0, description="Rechnung 4711")
        pinv = fake_api.add("Purchase Invoice", company=somiko.name, supplier="L", bill_no="4711", status="Unpaid",
                            posting_date="2026-08-01", grand_total=300.0, outstanding_amount=300.0, docstatus=1)
        inv = invoice.Invoice(fake_api.get_doc("Purchase Invoice", pinv), False)
        p = bank.BankTransaction(doc).payment(inv)
        assert p["paid_amount"] == 300.0 and p["payment_type"] == "Pay"
        stored = fake_api.get_doc("Bank Transaction", doc["name"])
        assert stored["unallocated_amount"] == 200.0 and stored["status"] == "Pending"

    def test_advance_payment_without_invoice(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient) -> None:
        doc = add_bt(fake_api, bacc, deposit=100.0, description="Anzahlung Auftrag 12345")
        p = bank.BankTransaction(doc).payment(None, is_recv=True, party="Kunde K", party_type="Customer")
        assert p["payment_type"] == "Receive" and p["party"] == "Kunde K"
        assert p["reference_no"] == "12345" and p["references"] == []
        assert fake_api.get_doc("Bank Transaction", doc["name"])["status"] == "Reconciled"

    def test_payment_failure_returns_none(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
        doc = add_bt(fake_api, bacc, deposit=100.0)
        monkeypatch.setattr(fake_api, "insert", lambda d: (_ for _ in ()).throw(RuntimeError("weg")))
        assert bank.BankTransaction(doc).payment(None, True, "K", "Customer") is None
        assert fake_api.get_doc("Bank Transaction", doc["name"])["status"] == "Pending"


class TestTransfer:
    def _open_invoices(self, fake_api: FakeFrappeClient, somiko: Company) -> tuple[list[invoice.Invoice], list[invoice.Invoice]]:
        fake_api.add("Sales Invoice", company=somiko.name, customer="Kunde K", status="Unpaid", custom_ebay=0,
                     posting_date="2026-08-01", grand_total=100.0, outstanding_amount=100.0, is_return=0)
        fake_api.add("Purchase Invoice", company=somiko.name, supplier="Lief", bill_no="RE-9", status="Unpaid",
                     posting_date="2026-08-01", grand_total=80.0, outstanding_amount=80.0, is_return=0)
        return somiko.get_sales_invoices(True), somiko.get_purchase_invoices(True)

    def test_options_offered(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, somiko: Company, gui: EasyguiStub) -> None:
        somiko.journal.append({"account": "8403 - Balkonmodule 19% - SoMiKo", "user_remark": "Balkonmodul Zahlung Meier"})
        somiko.journal.append({"account": "8401 - Selbstbauanlagen 19% - SoMiKo", "user_remark": "ganz anders"})
        other = F.make_bank_account(fake_api, somiko, name="Sparda - SoMiKo", iban=F.IBAN_SPARDA, account="Bank2 - SoMiKo")
        add_bt(fake_api, other, withdrawal=100.0, description="Gegenbuchung")
        add_bt(fake_api, other, withdrawal=55.0, description="anderer Betrag")
        sinvs, pinvs = self._open_invoices(fake_api, somiko)
        doc = add_bt(fake_api, bacc, deposit=100.0, description="Balkonmodul Zahlung Meier")
        gui.answers["choicebox"] = None
        bank.BankTransaction(doc).transfer(sinvs, pinvs)
        msg, title, options = gui.calls[0][1]
        assert options[0] == "Anzahlung"
        assert options[1].startswith(fake_api.get_list("Bank Transaction", filters={"description": "Gegenbuchung"})[0]["name"])
        assert "-100.0" in options[1]
        assert options[2].startswith(sinvs[0].name) and "Kunde K" in options[2]
        # accounts from similar journal entries first, then income accounts
        assert options[3] in ("8403 - Balkonmodule 19% - SoMiKo", "8401 - Selbstbauanlagen 19% - SoMiKo")
        income_names = [a["name"] for a in somiko.leaf_accounts_for_debit]
        assert set(options[3:]) == set(income_names)
        assert len(options) == 3 + len(income_names)
        assert "Bankbuchung:" in msg
        assert fake_api.calls_of("insert") == []

    def test_choose_account_creates_journal_entry(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient,
                                                  somiko: Company, gui: EasyguiStub) -> None:
        sinvs, pinvs = self._open_invoices(fake_api, somiko)
        doc = add_bt(fake_api, bacc, withdrawal=42.0, description="Werkzeug")
        gui.answers["choicebox"] = "4985 - Werkzeuge und Kleingeräte - SoMiKo"
        bank.BankTransaction(doc).transfer(sinvs, pinvs)
        j = fake_api.get_doc("Journal Entry", fake_api.get_list("Journal Entry")[0]["name"])
        assert j["accounts"][1]["account"] == "4985 - Werkzeuge und Kleingeräte - SoMiKo"
        assert j["accounts"][1]["debit"] == 42.0
        # withdrawal -> expense accounts are offered (alphabetically, without matching journal entries)
        options = gui.calls[0][1][2]
        assert options[1 + len(pinvs):] == sorted(a["name"] for a in somiko.leaf_accounts_for_credit)

    def test_choose_invoice_creates_payment(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, somiko: Company,
                                            gui: EasyguiStub) -> None:
        sinvs, pinvs = self._open_invoices(fake_api, somiko)
        doc = add_bt(fake_api, bacc, deposit=100.0, description="Zahlung Kunde")
        gui.answers["choicebox"] = lambda msg, title, options: options[1]
        bank.BankTransaction(doc).transfer(sinvs, pinvs)
        pe = fake_api.get_doc("Payment Entry", fake_api.get_list("Payment Entry")[0]["name"])
        assert pe["payment_type"] == "Receive" and pe["party"] == "Kunde K" and pe["paid_amount"] == 100.0
        assert pe["references"][0]["reference_name"] == sinvs[0].name

    def test_choose_advance(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, somiko: Company, gui: EasyguiStub) -> None:
        fake_api.add("Supplier", supplier_name="zeta GmbH")
        fake_api.add("Supplier", supplier_name="Alpha AG")
        doc = add_bt(fake_api, bacc, withdrawal=100.0, description="Vorkasse 998877")
        answers = iter(["Anzahlung", "Alpha AG"])
        gui.answers["choicebox"] = lambda msg, title, options: next(answers)
        bank.BankTransaction(doc).transfer([], [])
        assert gui.calls[1][1][2] == ["Alpha AG", "zeta GmbH"]     # sorted by casefold
        pe = fake_api.get_doc("Payment Entry", fake_api.get_list("Payment Entry")[0]["name"])
        assert pe["payment_type"] == "Pay" and pe["party_type"] == "Supplier" and pe["party"] == "Alpha AG"
        assert pe["reference_no"] == "998877"

    def test_choose_other_bank_transaction(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, somiko: Company,
                                           gui: EasyguiStub) -> None:
        other = F.make_bank_account(fake_api, somiko, name="Sparda - SoMiKo", iban=F.IBAN_SPARDA, account="Bank2 - SoMiKo")
        other_doc = add_bt(fake_api, other, withdrawal=100.0, description="Gegenbuchung")
        doc = add_bt(fake_api, bacc, deposit=100.0, description="Umbuchung")
        gui.answers["choicebox"] = lambda msg, title, options: options[1]
        bank.BankTransaction(doc).transfer([], [])
        assert fake_api.get_doc("Bank Transaction", other_doc["name"])["status"] == "Reconciled"
        assert fake_api.get_doc("Bank Transaction", doc["name"])["status"] == "Reconciled"

    def test_cancel_does_nothing(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, somiko: Company,
                                 gui: EasyguiStub) -> None:
        doc = add_bt(fake_api, bacc, deposit=100.0)
        gui.answers["choicebox"] = None
        bank.BankTransaction(doc).transfer([], [])
        assert fake_api.calls_of("insert") == [] and fake_api.calls_of("update") == []

    def test_unanswered_dialog_is_detected(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient) -> None:
        doc = add_bt(fake_api, bacc, deposit=100.0)
        with pytest.raises(GuiCalled):
            bank.BankTransaction(doc).transfer([], [])


class TestSubmitAndDelete:
    def _linked(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient) -> bank.BankTransaction:
        doc = add_bt(fake_api, bacc, deposit=100.0, description="Spende")
        bt = bank.BankTransaction(doc)
        bt.journal_entry("8401 - Selbstbauanlagen 19% - SoMiKo", False)
        je = fake_api.get_list("Journal Entry")[0]["name"]
        return doc["name"], je

    def test_submit_entry_submits_bank_transaction_and_journal(self, bacc: bank.BankAccount,
                                                               fake_api: FakeFrappeClient,
                                                               capsys: pytest.CaptureFixture[str]) -> None:
        bt_name, je = self._linked(bacc, fake_api)
        bank.BankTransaction.submit_entry(je)
        assert fake_api.get_doc("Journal Entry", je)["docstatus"] == 1
        assert fake_api.get_doc("Bank Transaction", bt_name)["docstatus"] == 1
        out = capsys.readouterr().out
        assert "Banktransaktion {} gebucht".format(bt_name) in out
        assert "Buchungssatz {} gebucht".format(je) in out

    def test_submit_entry_leaves_partially_allocated_bt_open(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient) -> None:
        doc = add_bt(fake_api, bacc, deposit=100.0)
        bt = bank.BankTransaction(doc)
        bt.link_to("Journal Entry", "X", 40.0)
        bt.update()
        je = fake_api.add("Journal Entry", name="X", accounts=[])
        bank.BankTransaction.submit_entry("X")
        assert fake_api.get_doc("Bank Transaction", doc["name"])["docstatus"] == 0
        assert fake_api.get_doc("Journal Entry", "X")["docstatus"] == 1

    def test_delete_entry_resets_bank_transaction(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
        bt_name, je = self._linked(bacc, fake_api)
        bank.BankTransaction.delete_entry(je)
        stored = fake_api.get_doc("Bank Transaction", bt_name)
        assert stored["status"] == "Pending"
        assert stored["unallocated_amount"] == 100.0 and stored["allocated_amount"] == 0
        assert stored["payment_entries"] == []
        assert fake_api.get_list("Journal Entry") == []
        assert "Banktransaktion {} angepasst".format(bt_name) in capsys.readouterr().out

    def test_delete_entry_without_bank_transaction(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
        je = fake_api.add("Journal Entry", accounts=[])
        bank.BankTransaction.delete_entry(je)
        assert fake_api.get_list("Journal Entry") == []
        assert "nicht in Banktransaktionen gefunden" in capsys.readouterr().out

    def test_delete_entry_payment(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, somiko: Company) -> None:
        doc = add_bt(fake_api, bacc, deposit=100.0)
        p = bank.BankTransaction(doc).payment(None, True, "K", "Customer")
        bank.BankTransaction.delete_entry(p["name"], is_journal=False)
        assert fake_api.get_list("Payment Entry") == []
        assert fake_api.get_doc("Bank Transaction", doc["name"])["status"] == "Pending"

    def test_cancelled_entry_only_resets(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient) -> None:
        bt_name, je = self._linked(bacc, fake_api)
        fake_api.cancel("Journal Entry", je)
        bank.BankTransaction.delete_entry(je, cancelled=True)
        assert fake_api.get_doc("Bank Transaction", bt_name)["status"] == "Pending"
        assert fake_api.get_doc("Journal Entry", je)["docstatus"] == 2   # not deleted

    def test_cancelled_entry_with_amendment_is_skipped(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient) -> None:
        bt_name, je = self._linked(bacc, fake_api)
        fake_api.cancel("Journal Entry", je)
        fake_api.add("Journal Entry", amended_from=je, accounts=[])
        bank.BankTransaction.delete_entry(je, cancelled=True)
        assert fake_api.get_doc("Bank Transaction", bt_name)["status"] == "Reconciled"

    def test_unreconcile_for_cancelled_links(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, somiko: Company) -> None:
        bt_name, je = self._linked(bacc, fake_api)
        doc2 = add_bt(fake_api, bacc, deposit=50.0)
        p = bank.BankTransaction(doc2).payment(None, True, "K", "Customer")
        fake_api.cancel("Journal Entry", je)
        fake_api.cancel("Payment Entry", p["name"])
        bank.BankTransaction.unreconcile_for_cancelled_links()
        assert fake_api.get_doc("Bank Transaction", bt_name)["status"] == "Pending"
        assert fake_api.get_doc("Bank Transaction", doc2["name"])["status"] == "Pending"


class TestFindBankTransaction:
    def test_finds_unique_match(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, somiko: Company) -> None:
        doc = add_bt(fake_api, bacc, withdrawal=119.0, description="Rechnung RE-4711 Solar")
        add_bt(fake_api, bacc, withdrawal=119.0, description="anderer Text")
        bt = bank.BankTransaction.find_bank_transaction(somiko.name, -119.0, "RE-4711")
        assert bt.name == doc["name"]

    def test_deposit_for_positive_total(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, somiko: Company) -> None:
        doc = add_bt(fake_api, bacc, deposit=50.0, description="Gutschrift G-1")
        assert bank.BankTransaction.find_bank_transaction(somiko.name, 50.0, "G-1").name == doc["name"]

    def test_ambiguous_or_missing(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, somiko: Company) -> None:
        add_bt(fake_api, bacc, withdrawal=10.0, description="RE-1 a")
        add_bt(fake_api, bacc, withdrawal=10.0, description="RE-1 b")
        n0 = len(fake_api.calls_of("get_list"))
        assert bank.BankTransaction.find_bank_transaction(somiko.name, -10.0, "RE-1") is None
        assert bank.BankTransaction.find_bank_transaction(somiko.name, -10.0, "RE-2") is None
        assert bank.BankTransaction.find_bank_transaction(somiko.name, -10.0, "") is None
        assert len(fake_api.calls_of("get_list")) == n0 + 2   # an empty bill_no does not even query

    def test_reconciled_transactions_are_ignored(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient,
                                                 somiko: Company) -> None:
        add_bt(fake_api, bacc, withdrawal=10.0, description="RE-1", status="Reconciled")
        assert bank.BankTransaction.find_bank_transaction(somiko.name, -10.0, "RE-1") is None


class TestReconcilePreInvoice:
    def _pre(self, fake_api: FakeFrappeClient, somiko: Company, pi_status: str = "Unpaid", docstatus: int = 1) -> str:
        pi = fake_api.add("Purchase Invoice", company=somiko.name, supplier="L", bill_no="B-1", status=pi_status,
                          posting_date="2026-08-01", grand_total=119.0, outstanding_amount=119.0, docstatus=docstatus)
        fake_api.add("PreRechnung", name="PreR00042", typ="Rechnung", purchase_invoice=pi)
        return pi

    def test_pays_linked_purchase_invoice(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, somiko: Company,
                                          capsys: pytest.CaptureFixture[str]) -> None:
        pi = self._pre(fake_api, somiko)
        doc = add_bt(fake_api, bacc, withdrawal=119.0, description="Pre42 Lieferant")
        bank.BankTransaction(doc).reconcile_pre_invoice()
        pe = fake_api.get_doc("Payment Entry", fake_api.get_list("Payment Entry")[0]["name"])
        assert pe["references"][0]["reference_name"] == pi and pe["paid_amount"] == 119.0
        assert fake_api.get_doc("Bank Transaction", doc["name"])["status"] == "Reconciled"
        assert "Zahle Rechnung" in capsys.readouterr().out

    def test_cancelled_invoice(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, somiko: Company,
                               capsys: pytest.CaptureFixture[str]) -> None:
        self._pre(fake_api, somiko, "Cancelled", 2)
        doc = add_bt(fake_api, bacc, withdrawal=119.0, description="Pre42")
        bank.BankTransaction(doc).reconcile_pre_invoice()
        assert fake_api.get_list("Payment Entry") == []
        assert "ist abgebrochen" in capsys.readouterr().out

    def test_missing_pre_invoice_and_link(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, somiko: Company,
                                          capsys: pytest.CaptureFixture[str]) -> None:
        bank.BankTransaction(add_bt(fake_api, bacc, withdrawal=1.0, description="Pre7")).reconcile_pre_invoice()
        fake_api.add("PreRechnung", name="PreR00008", typ="Rechnung")
        bank.BankTransaction(add_bt(fake_api, bacc, withdrawal=1.0, description="Pre8")).reconcile_pre_invoice()
        bank.BankTransaction(add_bt(fake_api, bacc, withdrawal=1.0, description="ohne Nummer")).reconcile_pre_invoice()
        out = capsys.readouterr().out
        assert "PreRechnung PreR00007 nicht gefunden" in out
        assert "PreRechnung PreR00008 hat keinen Eingangsrechnungs-Namen" in out
        assert fake_api.get_list("Payment Entry") == []

    def test_reconcile_pre_invoices_selects_pre_descriptions(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient,
                                                             somiko: Company) -> None:
        pi = self._pre(fake_api, somiko)
        add_bt(fake_api, bacc, withdrawal=119.0, description="Pre42 x")
        add_bt(fake_api, bacc, withdrawal=119.0, description="Nichts")
        bank.BankTransaction.reconcile_pre_invoices()
        assert len(fake_api.get_list("Payment Entry")) == 1


class TestBankStatementEntry:
    def test_bank_transaction_dict(self, bacc: bank.BankAccount) -> None:
        stmt = bank.BankStatement(bacc)
        be = bank.BankStatementEntry(stmt)
        be.posting_date, be.purpose, be.partner, be.amount = "2026-08-15", "  Zweck   A ", " Partner ", -12.5
        be.cleanup()
        assert (be.purpose, be.partner) == ("Zweck A", "Partner")
        assert be.bank_transaction() == {"doctype": "Bank Transaction", "date": "2026-08-15",
                                         "bank_account": bacc.name, "description": "Zweck A Partner", "currency": "EUR",
                                         "unallocated_amount": 12.5, "withdrawal": 12.5, "deposit": 0}
        be.amount = 30.0
        bt = be.bank_transaction()
        assert (bt["deposit"], bt["withdrawal"], bt["unallocated_amount"]) == (30.0, 0, 30.0)
        assert be.show() == "15.08.2026\nZweck A\nPartner\n30.00€"


ROWS_SPARKASSE = [
    {"date": "15.08.26", "purpose": "Rechnung  4711   Danke", "partner": "Kunde   K", "amount": "1.234,56"},
    {"date": "16.08.26", "purpose": "Miete August", "partner": "Vermieter", "amount": "-500,00"},
]
ROWS_SPARDA = [
    {"date": "16.08.2026", "partner": "Vermieter", "purpose": "Miete", "amount": "-500,00", "balance": "734,56"},
    {"date": "15.08.2026", "partner": "Kunde K", "purpose": "Rechnung 4711", "amount": "1.234,56", "balance": "1.234,56"},
]


class TestBankStatementReaders:
    def test_read_sparkasse_bremen(self, bacc: bank.BankAccount, tmp_path: Path) -> None:
        fn = F.write_sparkasse_csv(tmp_path / "spk.csv", ROWS_SPARKASSE)
        b = bank.BankStatement(bacc)
        b.read_sparkasse_bremen(fn)
        assert b.iban == F.IBAN_SPARKASSE
        assert [(e.posting_date, e.purpose, e.partner, e.amount) for e in b.entries] == [
            ("2026-08-15", "Rechnung 4711 Danke", "Kunde K", 1234.56),
            ("2026-08-16", "Miete August", "Vermieter", -500.0)]
        assert b.entries[0].partner_iban == F.IBAN_FREMD
        assert b.sbal is None and b.ebal is None

    def test_read_sparda_ethik(self, bacc: bank.BankAccount, tmp_path: Path) -> None:
        fn = F.write_sparda_csv(tmp_path / "sparda.csv", ROWS_SPARDA)
        b = bank.BankStatement(bacc)
        b.read_sparda_ethik(fn)
        assert [(e.posting_date, e.purpose, e.partner, e.amount) for e in b.entries] == [
            ("2026-08-16", "Miete", "Vermieter", -500.0), ("2026-08-15", "Rechnung 4711", "Kunde K", 1234.56)]
        assert b.ebal == 734.56       # first row = closing balance
        assert b.sbal == 1234.56      # last row

    def test_get_baccount_from_iban_column(self, bacc: bank.BankAccount, tmp_path: Path) -> None:
        fn = F.write_sparkasse_csv(tmp_path / "spk.csv", ROWS_SPARKASSE)
        assert bank.BankStatement.get_baccount(fn) == (bacc, F.IBAN_SPARKASSE)

    def test_get_baccount_from_second_column(self, bacc: bank.BankAccount, somiko: Company,
                                             fake_api: FakeFrappeClient, tmp_path: Path) -> None:
        sparda = F.make_bank_account(fake_api, somiko, name="Sparda - SoMiKo", iban=F.IBAN_SPARDA)
        fn = F.write_sparda_csv(tmp_path / "sparda.csv", ROWS_SPARDA)
        assert bank.BankStatement.get_baccount(fn) == (sparda, F.IBAN_SPARDA)

    def test_get_baccount_from_blz_and_konto(self, somiko: Company, fake_api: FakeFrappeClient, tmp_path: Path) -> None:
        acc = F.make_bank_account(fake_api, somiko, iban=F.iban_de(37040044, 532013000))
        p = tmp_path / "alt.csv"
        p.write_text("BLZ:;37040044\nKonto:;532013000\nBuchung;x\n", encoding="iso-8859-4")
        assert bank.BankStatement.get_baccount(str(p)) == (acc, "DE89370400440532013000")

    def test_get_baccount_unknown(self, bacc: bank.BankAccount, tmp_path: Path) -> None:
        fn = F.write_sparkasse_csv(tmp_path / "spk.csv", ROWS_SPARKASSE, iban=F.IBAN_FREMD)
        assert bank.BankStatement.get_baccount(fn) == (None, F.IBAN_FREMD)

    def test_read_statement_dispatch(self, somiko: Company, fake_api: FakeFrappeClient, tmp_path: Path, gui: EasyguiStub) -> None:
        spk = F.make_bank_account(fake_api, somiko)
        sparda = F.make_bank_account(fake_api, somiko, name="Sparda - SoMiKo", iban=F.IBAN_SPARDA)
        ethik = F.make_bank_account(fake_api, somiko, name="Ethik - SoMiKo", iban=F.iban_de(F.BLZ_ETHIK, 55))
        fremd = F.make_bank_account(fake_api, somiko, name="Fremd - SoMiKo", iban=F.IBAN_FREMD)
        b = bank.BankStatement.read_statement(F.write_sparkasse_csv(tmp_path / "a.csv", ROWS_SPARKASSE))
        assert b.baccount is spk and len(b.entries) == 2
        b = bank.BankStatement.read_statement(F.write_sparda_csv(tmp_path / "b.csv", ROWS_SPARDA))
        assert b.baccount is sparda and b.ebal == 734.56
        b = bank.BankStatement.read_statement(F.write_sparda_csv(tmp_path / "c.csv", ROWS_SPARDA, iban=ethik.iban))
        assert b.baccount is ethik
        gui.answers["msgbox"] = None
        assert bank.BankStatement.read_statement(F.write_sparda_csv(tmp_path / "d.csv", ROWS_SPARDA, iban=fremd.iban)) is None
        assert "Keine Importmöglichkeit für BLZ 20050550" in gui.calls[-1][1][0]

    def test_read_statement_unknown_account(self, bacc: bank.BankAccount, tmp_path: Path, gui: EasyguiStub) -> None:
        gui.answers["msgbox"] = None
        fn = F.write_sparkasse_csv(tmp_path / "x.csv", ROWS_SPARKASSE, iban=F.IBAN_FREMD)
        assert bank.BankStatement.read_statement(fn) is None
        assert "Konto unbekannt" in gui.calls[-1][1][0]


class TestProcessFile:
    def test_imports_new_transactions_and_deduplicates(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient,
                                                       tmp_path: Path) -> None:
        fn = F.write_sparkasse_csv(tmp_path / "spk.csv", ROWS_SPARKASSE)
        b = bank.BankStatement.process_file(fn)
        assert len(b.entries) == 2 and len(b.transactions) == 2
        bts = fake_api.get_list("Bank Transaction", fields=["date", "deposit", "withdrawal", "description", "status",
                                                              "unallocated_amount", "bank_account", "currency"])
        assert sorted(bts, key=lambda x: x["date"]) == [
            {"date": "2026-08-15", "deposit": 1234.56, "withdrawal": 0, "description": "Rechnung 4711 Danke Kunde K",
             "status": "Pending", "unallocated_amount": 1234.56, "bank_account": bacc.name, "currency": "EUR"},
            {"date": "2026-08-16", "deposit": 0, "withdrawal": 500.0, "description": "Miete August Vermieter",
             "status": "Pending", "unallocated_amount": 500.0, "bank_account": bacc.name, "currency": "EUR"}]
        assert bacc.balance == pytest.approx(734.56)
        today = datetime.date.today().strftime("%Y-%m-%d")
        assert fake_api.get_doc("Bank Account", bacc.name)["last_integration_date"] == today
        assert bacc.doc["last_integration_date"] == today
        # a second import of the same file creates nothing new
        b2 = bank.BankStatement.process_file(fn)
        assert len(b2.entries) == 2 and b2.transactions == []
        assert len(fake_api.get_list("Bank Transaction")) == 2

    def test_cancelled_duplicate_is_reimported(self, bacc: bank.BankAccount, fake_api: FakeFrappeClient, tmp_path: Path) -> None:
        fn = F.write_sparkasse_csv(tmp_path / "spk.csv", ROWS_SPARKASSE[:1])
        bank.BankStatement.process_file(fn)
        name = fake_api.get_list("Bank Transaction")[0]["name"]
        fake_api.cancel("Bank Transaction", name)
        b = bank.BankStatement.process_file(fn)
        assert len(b.transactions) == 1
        assert len(fake_api.get_list("Bank Transaction")) == 2

    def test_sparda_sets_statement_balance(self, somiko: Company, fake_api: FakeFrappeClient, tmp_path: Path) -> None:
        sparda = F.make_bank_account(fake_api, somiko, name="Sparda - SoMiKo", iban=F.IBAN_SPARDA)
        b = bank.BankStatement.process_file(F.write_sparda_csv(tmp_path / "s.csv", ROWS_SPARDA))
        assert sparda.statement_balance == 734.56
        assert sparda.balance == pytest.approx(734.56)

    def test_unknown_file_returns_none(self, bacc: bank.BankAccount, tmp_path: Path, gui: EasyguiStub) -> None:
        gui.answers["msgbox"] = None
        assert bank.BankStatement.process_file(F.write_sparkasse_csv(tmp_path / "x.csv", ROWS_SPARKASSE, iban=F.IBAN_FREMD)) is None
