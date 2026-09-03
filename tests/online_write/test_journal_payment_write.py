"""Buchungssätze und Zahlungen als Entwurf anlegen (und wieder löschen)."""
from __future__ import annotations

from typing import Any

import pytest

import bank
import journal
import payment
from api import Api
from frappeclient import FrappeException
from support.live import Cleanup, LiveState, tag


class TestJournalEntry:
    def test_journal_entry_draft(self, live: LiveState, api: Any, cleanup: Cleanup, today: str) -> None:
        ref = tag("JE")
        j = journal.journal_entry(live.company, live.bank_leaf(), live.expense_leaf(), 0, 12.34,
                                  "pytest Buchungssatz", "pytest " + ref, today, cheque_no=ref)
        assert j and j["name"]
        cleanup.add("Journal Entry", j["name"])
        doc = api.get_doc("Journal Entry", j["name"])
        assert doc["docstatus"] == 0
        assert doc["total_debit"] == pytest.approx(12.34) and doc["total_credit"] == pytest.approx(12.34)
        assert doc["company"] == live.company_name and doc["posting_date"] == today
        assert doc["cheque_no"] == ref and doc["cheque_date"] == today
        accounts = {a["account"]: a for a in doc["accounts"]}
        assert accounts[live.bank_leaf()]["credit_in_account_currency"] == pytest.approx(12.34)
        assert accounts[live.expense_leaf()]["debit_in_account_currency"] == pytest.approx(12.34)
        # der Client findet ihn unter den offenen Buchungssätzen
        assert j["name"] in {je["name"] for je in live.company.open_journal_entries()}

    def test_journal_entry3_draft(self, live: LiveState, api: Any, cleanup: Cleanup, today: str) -> None:
        j = journal.journal_entry3(live.company, live.bank_leaf(), live.expense_leaf(), live.income_leaf(),
                                   100.0, 19.0, "pytest 3 Konten", "pytest " + tag(), today)
        cleanup.add("Journal Entry", j["name"])
        doc = api.get_doc("Journal Entry", j["name"])
        assert doc["total_debit"] == pytest.approx(119.0) and doc["total_credit"] == pytest.approx(119.0)
        assert len(doc["accounts"]) == 3

    def test_delete_entry_removes_journal_entry(self, live: LiveState, api: Any, today: str,
                                                capsys: pytest.CaptureFixture[str]) -> None:
        j = journal.journal_entry(live.company, live.bank_leaf(), live.expense_leaf(), 5.0, 0,
                                  "pytest löschen", "pytest " + tag(), today)
        bank.BankTransaction.delete_entry(j["name"])
        with pytest.raises(FrappeException):
            api.get_doc("Journal Entry", j["name"])
        assert "gelöscht" in capsys.readouterr().out


class TestPaymentEntry:
    def test_create_payment_draft(self, live: LiveState, api: Any, cleanup: Cleanup, test_supplier: str, today: str) -> None:
        ref = tag("PAY")
        p = payment.create_payment(False, live.company, live.bank_leaf(), 10.0, today, test_supplier, "Supplier", ref, [])
        assert p and p["name"]
        cleanup.add("Payment Entry", p["name"])
        doc = api.get_doc("Payment Entry", p["name"])
        assert doc["docstatus"] == 0 and doc["payment_type"] == "Pay"
        assert doc["party"] == test_supplier and doc["party_type"] == "Supplier"
        assert doc["paid_amount"] == pytest.approx(10.0) and doc["paid_from"] == live.bank_leaf()
        assert doc["paid_to"], "ERPNext hat kein Gegenkonto (Verbindlichkeiten) gesetzt"
        assert doc["reference_no"] == ref and doc["unallocated_amount"] == pytest.approx(10.0)
        assert p["name"] in {pe["name"] for pe in live.company.unbooked_payment_entries()}

    def test_receive_payment_draft(self, live: LiveState, api: Any, cleanup: Cleanup, today: str) -> None:
        customers = api.get_list("Customer", limit_page_length=1)
        if not customers:
            pytest.skip("kein Kunde vorhanden")
        p = payment.create_payment(True, live.company, live.bank_leaf(), 7.5, today, customers[0]["name"], "Customer",
                                   tag("REC"), [])
        cleanup.add("Payment Entry", p["name"])
        doc = api.get_doc("Payment Entry", p["name"])
        assert doc["payment_type"] == "Receive" and doc["paid_to"] == live.bank_leaf()
        assert doc["paid_from"], "ERPNext hat kein Forderungskonto gesetzt"

    def test_delete_entry_for_payment(self, live: LiveState, api: Any, test_supplier: str, today: str) -> None:
        p = payment.create_payment(False, live.company, live.bank_leaf(), 1.0, today, test_supplier, "Supplier", tag(), [])
        bank.BankTransaction.delete_entry(p["name"], is_journal=False)
        with pytest.raises(FrappeException):
            api.get_doc("Payment Entry", p["name"])
