"""Leads: the server script keeps flagged leads on "Do Not Contact" when e-mails arrive."""
from __future__ import annotations

from typing import Any

import pytest

import lead
import lead_dnc_setup as setup
from settings import LEAD_DNC_FIELD
from support.live import Cleanup, LiveState, tag


def make_lead(api: Any, cleanup: Cleanup, flagged: bool) -> dict[str, Any]:
    name = tag("pytest-Lead")
    doc = api.insert({"doctype": "Lead", "lead_name": name, "email_id": name.lower() + "@example.org",
                      "status": "Do Not Contact", LEAD_DNC_FIELD: 1 if flagged else 0})
    cleanup.add("Lead", doc["name"])
    return doc


def receive_mail(api: Any, cleanup: Cleanup, lead_doc: dict[str, Any]) -> None:
    """Simulate an incoming e-mail linked to the lead (what the mail sync does)."""
    comm = api.insert({"doctype": "Communication", "communication_type": "Communication",
                       "communication_medium": "Email", "sent_or_received": "Received",
                       "subject": "pytest " + lead_doc["lead_name"], "content": "<p>pytest</p>",
                       "sender": lead_doc["email_id"], "reference_doctype": "Lead", "reference_name": lead_doc["name"]})
    cleanup.add("Communication", comm["name"])


@pytest.fixture
def installed(api: Any) -> None:
    fields = api.get_list("Custom Field", filters={"dt": "Lead", "fieldname": LEAD_DNC_FIELD}, limit_page_length=1)
    scripts = api.get_list("Server Script", filters={"name": setup.SERVER_SCRIPT_NAME, "disabled": 0}, limit_page_length=1)
    if not fields or not scripts:
        pytest.skip("lead_dnc_setup.py --apply wurde auf der Instanz noch nicht ausgeführt")


class TestDoNotContactProtection:
    def test_frappe_reopens_unflagged_lead(self, live: LiveState, api: Any, cleanup: Cleanup, installed: None) -> None:
        # the Frappe behaviour the server script counters
        doc = make_lead(api, cleanup, flagged=False)
        receive_mail(api, cleanup, doc)
        assert api.get_doc("Lead", doc["name"])["status"] == "Open"

    def test_flagged_lead_stays_closed(self, live: LiveState, api: Any, cleanup: Cleanup, installed: None) -> None:
        doc = make_lead(api, cleanup, flagged=True)
        receive_mail(api, cleanup, doc)
        assert api.get_doc("Lead", doc["name"])["status"] == "Do Not Contact"

    def test_mark_not_contact_sets_flag(self, live: LiveState, api: Any, cleanup: Cleanup, installed: None) -> None:
        doc = make_lead(api, cleanup, flagged=False)
        api.set_value("Lead", doc["name"], "status", "Open")
        lead.mark_not_contact(doc["name"])
        stored = api.get_doc("Lead", doc["name"])
        assert stored["status"] == "Do Not Contact" and stored[LEAD_DNC_FIELD] == 1
        receive_mail(api, cleanup, doc)
        assert api.get_doc("Lead", doc["name"])["status"] == "Do Not Contact"

    def test_setup_is_idempotent(self, live: LiveState, api: Any, installed: None) -> None:
        assert setup.ensure_custom_field(api, apply=False) is True
        assert setup.ensure_server_script(api, apply=False) is True
