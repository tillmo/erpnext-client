"""Buchen (docstatus 1) und Abbrechen - nur mit ERPNEXT_TEST_ALLOW_SUBMIT=1.

Gebuchte Dokumente lassen sich nicht löschen, sondern nur abbrechen; das Aufräumen bricht sie
ab und löscht sie danach. Auf der Instanz bleiben dabei keine Belege, aber ggf. Lücken in den
Nummernkreisen.
"""
import pytest

import journal
import payment
from api import Api
from support.live import tag


@pytest.fixture(autouse=True)
def _submit(submit_allowed):
    return submit_allowed


class TestSubmitDoc:
    def test_submit_and_cancel_journal_entry(self, live, api, cleanup, today):
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

    def test_buchen_setting_submits_payment(self, live, api, cleanup, test_supplier, today, user_settings):
        user_settings["-buchen-"] = True
        p = payment.create_payment(False, live.company, live.bank_leaf(), 3.0, today, test_supplier, "Supplier", tag(), [])
        cleanup.add("Payment Entry", p["name"])
        doc = api.get_doc("Payment Entry", p["name"])
        assert doc["docstatus"] == 1 and doc["unallocated_amount"] == pytest.approx(3.0)
        assert p["name"] in {pe["name"] for pe in live.company.unassigned_payment_entries()}
