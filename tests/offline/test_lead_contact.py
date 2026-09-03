"""Tests for lead_contact.py (contact data from lead mails, vCard export)."""
from __future__ import annotations

from typing import Any

import pytest

import lead_contact as lc
from lead_contact import Contact
from support.fakes import FakeFrappeClient
from support.stubs import EasyguiStub

FORM_MAIL = """Neue Kontaktanfrage über die Website

Name: Max Mustermann
E-Mail: max@example.org
Telefon: 0421 / 12 34 56
Adresse: Musterstraße 5a, 28199 Bremen
Betreff: Balkonkraftwerk
Nachricht:
Ich hätte gern eine Beratung am 03.09.2026.

--
Bremer SolidarStrom, Beispielweg 1, 28203 Bremen
"""

FREE_MAIL = """Hallo,

wir interessieren uns für eine Solaranlage auf unserem Dach.
Können Sie uns anrufen?

Viele Grüße
Dr. Erika Musterfrau
Am Deich 12
28201 Bremen
Mobil: +49 (0)170 1234567
Festnetz 0421-9876543
"""


class TestPhones:
    def test_normalize(self) -> None:
        assert lc.normalize_phone("0421 / 12 34 56") == "+49 421 123456"
        assert lc.normalize_phone("+49 (0)170 1234567") == "+49 170 1234567"
        assert lc.normalize_phone("0170-1234567") == "+49 170 1234567"
        assert lc.normalize_phone("0049 30 123456") == "+49 30 123456"
        assert lc.normalize_phone("04298 / 4711") == "+49 4298 4711"
        assert lc.normalize_phone("03.09.2026") == ""              # a date
        assert lc.normalize_phone("28199") == "" and lc.normalize_phone("1234") == ""
        assert lc.is_mobile("+49 170 1234567") and not lc.is_mobile("+49 421 123456")

    def test_phones_in_text(self) -> None:
        assert lc.phones_in("Tel 0421 123456, mobil 0170 1234567, nochmal 0421 123456") == ["+49 421 123456", "+49 170 1234567"]
        assert lc.phones_in("Rechnung 2026-00123 vom 03.09.2026, IBAN DE02 1234 5678 9012 3456 78") == []


class TestNames:
    def test_split_name(self) -> None:
        assert lc.split_name("Max Mustermann") == ("Max", "Mustermann")
        assert lc.split_name("Dr. Erika Musterfrau") == ("Erika", "Musterfrau")
        assert lc.split_name("Mustermann, Max") == ("Max", "Mustermann")
        assert lc.split_name("Herr Karl Heinz Müller") == ("Karl Heinz", "Müller")
        assert lc.split_name("Mustermann") == ("", "Mustermann")
        assert lc.split_name("max@example.org") == ("", "")


class TestExtract:
    def test_form_mail(self) -> None:
        c = lc.extract(FORM_MAIL, "Website Formular", "formular@bremer-solidarstrom.de")
        assert c == Contact(first_name="Max", last_name="Mustermann", mobile_no="", phone="+49 421 123456",
                            street="Musterstraße 5a", pincode="28199", city="Bremen", email="max@example.org")

    def test_free_text_mail(self) -> None:
        c = lc.extract(FREE_MAIL, "Erika Musterfrau", "Erika Musterfrau <erika@example.org>")
        assert c == Contact(first_name="Erika", last_name="Musterfrau", mobile_no="+49 170 1234567", phone="+49 421 9876543",
                            street="Am Deich 12", pincode="28201", city="Bremen", email="erika@example.org")

    def test_form_with_values_on_next_line(self) -> None:
        text = "Vorname:\nMax\nNachname:\nMustermann\nHandy:\n0171 2223334\nStraße:\nHauptstr. 7\nPLZ / Ort:\n28195 Bremen\n"
        c = lc.extract(text)
        assert (c.first_name, c.last_name, c.mobile_no) == ("Max", "Mustermann", "+49 171 2223334")
        assert (c.street, c.pincode, c.city) == ("Hauptstr. 7", "28195", "Bremen")

    def test_own_footer_is_ignored(self) -> None:
        c = lc.extract("Hallo, bitte Rückruf.\n\nBremer SolidarStrom\nBeispielweg 1\n28203 Bremen\n", "Bremer SolidarStrom",
                       "info@bremer-solidarstrom.de")
        assert c == Contact()

    def test_signature_name(self) -> None:
        text = "Hallo,\nbitte um Rückruf.\n\nMit freundlichen Grüßen\nKarl-Heinz Müller\nTel. 0421 111222\n"
        c = lc.extract(text, "formular@bremer-solidarstrom.de", "formular@bremer-solidarstrom.de")
        assert (c.first_name, c.last_name, c.phone) == ("Karl-Heinz", "Müller", "+49 421 111222")
        assert lc.extract("Viele Grüße\nBremer SolidarStrom Team\n").last_name == ""
        assert lc.extract("Viele Grüße\n\nmax@example.org\n").last_name == ""

    def test_extract_from_mails_merges(self) -> None:
        comms = [{"content": "<p>Viele Grüße<br>Max Mustermann</p>", "sender": "max@example.org", "creation": "2026-09-01 10:00:00"},
                 {"content": "<p>Meine Nummer: 0170 1234567<br>Adresse: Weg 1, 28199 Bremen</p>", "sender": "max@example.org",
                  "creation": "2026-09-02 10:00:00"},
                 {"content": "<p>Unsere Antwort</p>", "sent_or_received": "Sent", "creation": "2026-09-01 12:00:00"}]
        contact, first_text = lc.extract_from_mails(comms)
        assert contact == Contact(first_name="Max", last_name="Mustermann", mobile_no="+49 170 1234567", street="Weg 1",
                                  pincode="28199", city="Bremen", email="max@example.org")
        assert first_text == "Viele Grüße\nMax Mustermann"

    def test_quoted_mails_are_ignored(self) -> None:
        text = ("Danke, passt.\nGruß\nMax Mustermann\n\nAm 01.09.2026 um 10:00 schrieb Bremer SolidarStrom:\n"
                "> Viele Grüße\n> Chris Beispiel\n> Tel 0421 0000000\nBremer SolidarStrom\nBeispielweg 1\n28203 Bremen\n")
        c = lc.extract(text)
        assert c == Contact(first_name="Max", last_name="Mustermann")
        text2 = "Hallo\n\n-----Ursprüngliche Nachricht-----\nVon: Chris\nTel 0421 0000000\n"
        assert lc.extract(text2).phone == ""

    def test_sender_name_and_mail_fallback(self) -> None:
        c = lc.extract("kurz", "Anna Beispiel", "Anna Beispiel <anna@example.org>")
        assert (c.first_name, c.last_name, c.email) == ("Anna", "Beispiel", "anna@example.org")
        assert lc.extract("", None, None) == Contact()

    def test_merge_prefers_existing(self) -> None:
        extracted = Contact(first_name="Max", mobile_no="+49 170 1", city="Bremen")
        existing = Contact(first_name="Maximilian", phone="+49 421 1")
        assert extracted.merged_with(existing) == Contact(first_name="Maximilian", mobile_no="+49 170 1", phone="+49 421 1", city="Bremen")
        assert Contact().empty() and not extracted.empty()


class TestVcard:
    def test_vcard(self) -> None:
        c = Contact(first_name="Max", last_name="Mustermann", mobile_no="+49 170 1234567", phone="+49 421 123456",
                    street="Musterstraße 5a", pincode="28199", city="Bremen", email="max@example.org")
        v = lc.vcard("CRM-LEAD-2026-00001", c, "https://erp.example/app/lead/CRM-LEAD-2026-00001")
        lines = v.split("\r\n")
        assert lines[0] == "BEGIN:VCARD" and lines[1] == "VERSION:3.0" and lines[-2] == "END:VCARD" and lines[-1] == ""
        assert "UID:CRM-LEAD-2026-00001" in lines and "N:Mustermann;Max;;;" in lines and "FN:Max Mustermann" in lines
        assert "TEL;TYPE=CELL:+49 170 1234567" in lines and "TEL;TYPE=HOME,VOICE:+49 421 123456" in lines
        assert "ADR;TYPE=HOME:;;Musterstraße 5a;Bremen;;28199;Germany" in lines
        assert "URL:https://erp.example/app/lead/CRM-LEAD-2026-00001" in lines

    def test_escaping_and_minimal(self) -> None:
        v = lc.vcard("L1", Contact(last_name="Müller, Schmidt; Co"), "u")
        assert "N:Müller\\, Schmidt\\; Co;;;;" in v and "FN:Müller\\, Schmidt\\; Co" in v
        assert "TEL" not in v and "ADR" not in v and "EMAIL" not in v


@pytest.fixture
def lead_doc(fake_api: FakeFrappeClient) -> FakeFrappeClient:
    fake_api.add("Lead", name="L-1", lead_name="max@example.org", email_id="max@example.org", status="Open")
    fake_api.communications["L-1"] = [
        {"sender": "max@example.org", "sender_full_name": "Max Mustermann", "subject": "Kontaktanfrage",
         "content": "<p>" + FORM_MAIL.replace("\n", "<br>") + "</p>", "sent_or_received": "Received", "creation": "2026-09-01 10:00:00"},
        {"sender": "max@example.org", "subject": "Re", "content": "<p>Danke</p>", "sent_or_received": "Received",
         "creation": "2026-09-02 10:00:00"}]
    return fake_api


class TestApply:
    def test_apply_fills_empty_fields_and_creates_address(self, lead_doc: FakeFrappeClient) -> None:
        lead_doc.add("Lead", name="L-2", lead_name="Alt Bestand", first_name="Alt", last_name="Bestand", mobile_no="+49 170 0",
                     email_id="alt@example.org", status="Open")
        c = Contact(first_name="Max", last_name="Mustermann", mobile_no="+49 170 1234567", phone="+49 421 123456",
                    street="Musterstraße 5a", pincode="28199", city="Bremen", email="max@example.org")
        assert lc.apply_contact("L-1", c) == ["first_name", "last_name", "mobile_no", "phone", "city", "lead_name", "address"]
        doc = lead_doc.get_doc("Lead", "L-1")
        assert doc["lead_name"] == "Max Mustermann" and doc["mobile_no"] == "+49 170 1234567" and doc["city"] == "Bremen"
        addr = lead_doc.get_list("Address", fields=["*"])[0]
        assert addr["address_line1"] == "Musterstraße 5a" and addr["pincode"] == "28199" and addr["country"] == "Germany"
        assert addr["links"][0]["link_doctype"] == "Lead" and addr["links"][0]["link_name"] == "L-1"
        linked = lc.linked_address("L-1")
        assert linked is not None and linked["name"] == addr["name"]
        # existing values are kept, no second address
        assert lc.apply_contact("L-1", Contact(first_name="Moritz", street="Anderswo 1", city="Bremen")) == []
        assert len(lead_doc.get_list("Address")) == 1
        assert lc.apply_contact("L-2", c) == ["phone", "city", "address"]
        assert lead_doc.get_doc("Lead", "L-2")["mobile_no"] == "+49 170 0"

    def test_names_filled_with_the_address_by_erpnext_are_replaced(self, lead_doc: FakeFrappeClient) -> None:
        lead_doc.add("Lead", name="L-3", lead_name="x@example.org", first_name="x@example.org", email_id="x@example.org", status="Open")
        assert lc.apply_contact("L-3", Contact(first_name="Max", last_name="Mustermann")) == ["first_name", "last_name", "lead_name"]
        doc = lead_doc.get_doc("Lead", "L-3")
        assert (doc["first_name"], doc["last_name"], doc["lead_name"]) == ("Max", "Mustermann", "Max Mustermann")
        assert lc.from_lead({"first_name": "x@example.org", "lead_name": "x@example.org", "email_id": "x@example.org"}, None) == \
            Contact(email="x@example.org")

    def test_attach_vcard_replaces(self, lead_doc: FakeFrappeClient) -> None:
        c = Contact(first_name="Max", last_name="Mustermann")
        assert lc.attach_vcard("L-1", c) == "L-1.vcf"
        assert lc.attach_vcard("L-1", c) == "L-1.vcf"
        files = lead_doc.get_list("File", fields=["file_name", "is_private", "attached_to_name"])
        assert files == [{"file_name": "L-1.vcf", "is_private": 1, "attached_to_name": "L-1"}]
        assert lead_doc.files["/private/files/L-1.vcf"].decode().startswith("BEGIN:VCARD")

    def test_from_lead(self, lead_doc: FakeFrappeClient) -> None:
        doc = lead_doc.get_doc("Lead", "L-1")
        assert lc.from_lead(doc, None) == Contact(email="max@example.org")             # lead_name is the address
        doc.update(lead_name="Max Mustermann", phone="+49 421 1")
        assert lc.from_lead(doc, {"address_line1": "Weg 1", "pincode": "28199", "city": "Bremen"}) == \
            Contact(first_name="Max", last_name="Mustermann", phone="+49 421 1", street="Weg 1", pincode="28199",
                    city="Bremen", email="max@example.org")


class TestCompleteLead:
    def test_dialog_values_are_stored(self, lead_doc: FakeFrappeClient, gui: EasyguiStub, capsys: pytest.CaptureFixture[str]) -> None:
        def answer(msg: str, title: str, fields: list[str], values: list[str]) -> list[str]:
            assert "L-1" in title and "Max Mustermann" in msg
            assert dict(zip(fields, values)) == {"Vorname": "Max", "Nachname": "Mustermann", "Handy": "", "Telefon": "+49 421 123456",
                                                 "Straße und Hausnummer": "Musterstraße 5a", "PLZ": "28199", "Ort": "Bremen",
                                                 "E-Mail": "max@example.org"}
            values = list(values)
            values[2] = "0171 999 8877"          # the user adds a mobile number
            return values
        gui.answers["multenterbox"] = answer
        doc = lead_doc.get_doc("Lead", "L-1")
        assert lc.complete_lead("L-1", doc, lead_doc.communications["L-1"]) is True
        stored = lead_doc.get_doc("Lead", "L-1")
        assert stored["mobile_no"] == "+49 171 9998877" and stored["phone"] == "+49 421 123456" and stored["lead_name"] == "Max Mustermann"
        assert len(lead_doc.get_list("Address")) == 1
        assert lead_doc.get_list("File", fields=["file_name"]) == [{"file_name": "L-1.vcf"}]
        comments = lead_doc.get_list("Comment", fields=["content"])
        assert comments and comments[0]["content"].startswith("Kontaktdaten aus der E-Mail übernommen: first_name")
        assert "vCard L-1.vcf angehängt" in capsys.readouterr().out

    def test_cancel(self, lead_doc: FakeFrappeClient, gui: EasyguiStub, capsys: pytest.CaptureFixture[str]) -> None:
        gui.answers["multenterbox"] = None
        assert lc.complete_lead("L-1", lead_doc.get_doc("Lead", "L-1"), lead_doc.communications["L-1"]) is False
        assert lead_doc.calls_of("update") == [] and lead_doc.get_list("File") == []
        assert "übersprungen" in capsys.readouterr().out

    def test_without_dialog(self, lead_doc: FakeFrappeClient) -> None:
        assert lc.complete_lead("L-1", lead_doc.get_doc("Lead", "L-1"), lead_doc.communications["L-1"], ask=False) is True
        assert lead_doc.get_doc("Lead", "L-1")["phone"] == "+49 421 123456"


class TestCompleteLeads:
    def test_menu_action(self, lead_doc: FakeFrappeClient, gui: EasyguiStub, capsys: pytest.CaptureFixture[str]) -> None:
        lead_doc.get_doc("Lead", "L-1")
        lead_doc.docs("Lead")["L-1"].update(status="Replied", creation="2026-09-01 10:00:00")
        lead_doc.add("Lead", name="L-DNC", status="Do Not Contact", email_id="x@y.de", creation="2026-09-02 10:00:00")
        lead_doc.add("Lead", name="L-OPEN", status="Open", _assign=None, email_id="o@y.de", creation="2026-09-02 10:00:00")
        lead_doc.add("Lead", name="L-ASSIGNED", status="Open", _assign='["chris@example.org"]', email_id="a@y.de",
                     creation="2026-09-03 10:00:00")
        lead_doc.add("Lead", name="L-HAS-PHONE", status="Converted", mobile_no="+49 170 1", creation="2026-09-03 10:00:00")
        gui.answers["multenterbox"] = lambda msg, title, fields, values: values
        lc.complete_leads()
        titles = [call[1][1] for call in gui.calls if call[0] == "multenterbox"]
        assert titles == ["Kontaktdaten für L-ASSIGNED", "Kontaktdaten für L-1"]      # newest first, only real leads
        out = capsys.readouterr().out
        assert "2 Leads ohne Telefonnummer" in out and "Kontaktdaten für 2 Leads nachgetragen" in out

    def test_cancel_asks_to_continue(self, lead_doc: FakeFrappeClient, gui: EasyguiStub) -> None:
        lead_doc.docs("Lead")["L-1"].update(status="Replied", creation="2026-09-01 10:00:00")
        lead_doc.add("Lead", name="L-3", status="Replied", email_id="b@y.de", creation="2026-09-02 10:00:00")
        gui.answers["multenterbox"] = None
        gui.answers["ynbox"] = False
        lc.complete_leads()
        assert len([c for c in gui.calls if c[0] == "multenterbox"]) == 1


class TestCreateVcard:
    def test_choice_list_newest_first(self, lead_doc: FakeFrappeClient, gui: EasyguiStub) -> None:
        lead_doc.docs("Lead")["L-1"].update(status="Replied", creation="2026-09-01 10:00:00", mobile_no="+49 170 1")
        lead_doc.add("Lead", name="L-NEWER", status="Converted", lead_name="Neu Er", email_id="n@y.de", creation="2026-09-05 10:00:00")
        lead_doc.add("Lead", name="L-DNC", status="Do Not Contact", email_id="x@y.de", creation="2026-09-06 10:00:00")
        lead_doc.add("Lead", name="L-OPEN", status="Open", _assign=None, email_id="o@y.de", creation="2026-09-07 10:00:00")
        seen: dict[str, Any] = {}

        def choose(msg: str, title: str, choices: list[str], **kw: Any) -> str:
            seen["choices"] = choices
            return choices[1]
        gui.answers["choicebox"] = choose
        gui.answers["multenterbox"] = lambda msg, title, fields, values: values
        lc.create_vcard()
        assert [c.split()[0] for c in seen["choices"]] == ["L-NEWER", "L-1"]
        assert "Neu Er" in seen["choices"][0] and "(Converted, 2026-09-05)" in seen["choices"][0]
        assert lead_doc.get_list("File", fields=["attached_to_name"]) == [{"attached_to_name": "L-1"}]

    def test_cancel(self, lead_doc: FakeFrappeClient, gui: EasyguiStub, capsys: pytest.CaptureFixture[str]) -> None:
        lead_doc.docs("Lead")["L-1"].update(status="Replied", creation="2026-09-01 10:00:00")
        gui.answers["choicebox"] = None
        lc.create_vcard()
        assert lead_doc.get_list("File") == [] and "abgebrochen" in capsys.readouterr().out
