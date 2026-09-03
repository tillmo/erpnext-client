"""Leads: the server script keeps flagged leads on "Do Not Contact" when e-mails arrive."""
from __future__ import annotations

from typing import Any

import pytest

import lead
import lead_contact
import lead_dnc_setup as setup
import lead_rules
import lead_rules_setup as rules_setup
from settings import LEAD_DNC_FIELD, LEAD_RULE_DOCTYPE, SUPPLIER_DOMAINS_FIELD
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


@pytest.fixture
def rules_installed(api: Any) -> None:
    doctypes = api.get_list("DocType", filters={"name": LEAD_RULE_DOCTYPE}, limit_page_length=1)
    fields = api.get_list("Custom Field", filters={"dt": "Supplier", "fieldname": SUPPLIER_DOMAINS_FIELD}, limit_page_length=1)
    if not doctypes or not fields:
        pytest.skip("lead_rules_setup.py --apply wurde auf der Instanz noch nicht ausgeführt")


class TestSenderRules:
    def test_rule_roundtrip_and_load(self, live: LiveState, api: Any, cleanup: Cleanup, rules_installed: None) -> None:
        domain = tag("pytest").lower() + ".example"
        rule = api.insert({"doctype": LEAD_RULE_DOCTYPE, "muster": domain, "wirkung": "Kein Lead", "quelle": "Client",
                           "bemerkung": "pytest"})
        cleanup.add(LEAD_RULE_DOCTYPE, rule["name"])
        assert rule["name"] == domain                   # named by the pattern
        rules = lead_rules.Rules.load()
        assert domain in rules.block_domains
        d = lead_rules.classify("news@mail." + domain, [{"sender": "news@mail." + domain, "subject": "x", "content": ""}], rules)
        assert d.auto and d.choice == "kein Lead"
        # a disabled rule is ignored
        api.set_value(LEAD_RULE_DOCTYPE, rule["name"], "deaktiviert", 1)
        assert domain not in lead_rules.Rules.load().block_domains

    def test_duplicate_pattern_is_rejected(self, live: LiveState, api: Any, cleanup: Cleanup, rules_installed: None) -> None:
        from frappeclient import FrappeException
        domain = tag("pytest").lower() + ".example"
        cleanup.add(LEAD_RULE_DOCTYPE, api.insert({"doctype": LEAD_RULE_DOCTYPE, "muster": domain, "wirkung": "Kein Lead"})["name"])
        with pytest.raises(FrappeException):
            api.insert({"doctype": LEAD_RULE_DOCTYPE, "muster": domain, "wirkung": "Lead"})

    def test_supplier_domains_field(self, live: LiveState, api: Any, cleanup: Cleanup, test_supplier: str,
                                    rules_installed: None) -> None:
        new = lead_rules.note_supplier_domains(test_supplier, "Rechnung von info@pytest-lieferant.example")
        assert new == ["pytest-lieferant.example"]
        assert api.get_doc("Supplier", test_supplier)[SUPPLIER_DOMAINS_FIELD] == "pytest-lieferant.example"
        assert lead_rules.Rules.load().supplier_domains.get("pytest-lieferant.example") == test_supplier

    def test_setup_is_idempotent(self, live: LiveState, api: Any, rules_installed: None) -> None:
        assert rules_setup.ensure_rule_doctype(api, apply=False) is True
        assert rules_setup.ensure_supplier_field(api, apply=False) is True


class TestContactData:
    def test_complete_lead_stores_data_and_vcard(self, live: LiveState, api: Any, cleanup: Cleanup) -> None:
        name = tag("pytest-Lead")
        doc = api.insert({"doctype": "Lead", "lead_name": name.lower() + "@example.org", "email_id": name.lower() + "@example.org",
                          "status": "Open"})
        cleanup.add("Lead", doc["name"])
        comms = [{"sender": doc["email_id"], "sender_full_name": "Max Mustermann", "sent_or_received": "Received",
                  "creation": "2026-09-01 10:00:00",
                  "content": "<p>Name: Max Mustermann<br>Telefon: 0421 / 12 34 56<br>Handy: 0170 1234567<br>"
                             "Adresse: Musterstraße 5a, 28199 Bremen</p>"}]
        assert lead_contact.complete_lead(doc["name"], doc, comms, ask=False) is True
        stored = api.get_doc("Lead", doc["name"])
        assert stored["lead_name"] == "Max Mustermann" and stored["first_name"] == "Max" and stored["last_name"] == "Mustermann"
        assert stored["mobile_no"] == "+49 170 1234567" and stored["phone"] == "+49 421 123456" and stored["city"] == "Bremen"
        address = lead_contact.linked_address(doc["name"])
        assert address and address["address_line1"] == "Musterstraße 5a" and address["pincode"] == "28199"
        cleanup.add("Address", address["name"])
        files = api.get_list("File", filters={"attached_to_doctype": "Lead", "attached_to_name": doc["name"]},
                             fields=["name", "file_name", "is_private", "file_url"])
        assert len(files) == 1 and files[0]["is_private"] == 1 and files[0]["file_name"].endswith(".vcf")
        content = api.get_file(files[0]["file_url"]).decode("utf-8")
        assert "FN:Max Mustermann" in content and "TEL;TYPE=CELL:+49 170 1234567" in content
        # a second run replaces the vCard and adds nothing
        assert lead_contact.complete_lead(doc["name"], api.get_doc("Lead", doc["name"]), comms, ask=False) is True
        files = api.get_list("File", filters={"attached_to_doctype": "Lead", "attached_to_name": doc["name"]}, fields=["name"])
        assert len(files) == 1
        assert len(api.get_list("Address", filters=[["Dynamic Link", "link_name", "=", doc["name"]]], fields=["name"])) == 1
