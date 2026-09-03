"""Submit (docstatus 1) and cancel - only with ERPNEXT_TEST_ALLOW_SUBMIT=1.

Submitted documents cannot be deleted, only cancelled; the cleanup cancels them and deletes
them afterwards. No documents remain on the instance, but there may be gaps in the naming
series.
"""
from __future__ import annotations

from typing import Any

import pytest

import journal
import payment
from api import Api
from support.live import Cleanup, LiveState, tag
from support.stubs import UserSettings


@pytest.fixture(autouse=True)
def _submit(submit_allowed: bool) -> bool:
    return submit_allowed


class TestSubmitDoc:
    def test_submit_and_cancel_journal_entry(self, live: LiveState, api: Any, cleanup: Cleanup, today: str) -> None:
        j = journal.journal_entry(live.company, live.bank_leaf(), live.expense_leaf(), 0, 2.5, "pytest buchen",
                                  "pytest " + tag(), today)
        cleanup.add("Journal Entry", j["name"])
        Api.submit_doc("Journal Entry", j["name"])
        doc = api.get_doc("Journal Entry", j["name"])
        assert doc["docstatus"] == 1
        gl = api.get_list("GL Entry", filters={"voucher_no": j["name"], "is_cancelled": 0}, fields=["account", "debit", "credit"],
                          limit_page_length=10)
        assert len(gl) == 2
        api.cancel("Journal Entry", j["name"])
        assert api.get_doc("Journal Entry", j["name"])["docstatus"] == 2

    def test_buchen_setting_submits_payment(self, live: LiveState, api: Any, cleanup: Cleanup, test_supplier: str,
                                            today: str, user_settings: UserSettings) -> None:
        user_settings["-buchen-"] = True
        p = payment.create_payment(False, live.company, live.bank_leaf(), 3.0, today, test_supplier, "Supplier", tag(), [])
        cleanup.add("Payment Entry", p["name"])
        doc = api.get_doc("Payment Entry", p["name"])
        assert doc["docstatus"] == 1 and doc["unallocated_amount"] == pytest.approx(3.0)
        assert p["name"] in {pe["name"] for pe in live.company.unassigned_payment_entries()}
