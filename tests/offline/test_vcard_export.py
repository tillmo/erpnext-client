"""Tests for vcard_export.py (vCards of assigned leads into Nextcloud address books)."""
from __future__ import annotations

from typing import Any

import pytest

import vcard_export as vx
from api import Api
from support.fakes import FakeCardDavSession, FakeFrappeClient
from support.stubs import UserSettings

CHRIS = "chris@example.org"
PAUL = "paul@example.org"
BOOK = "erpnext-leads-chris"


@pytest.fixture
def dav() -> vx.CardDav:
    return vx.CardDav("https://cloud.example/", "user", "app-passwort", session=FakeCardDavSession())


@pytest.fixture
def leads(fake_api: FakeFrappeClient) -> FakeFrappeClient:
    fake_api.add("User", email=CHRIS, first_name="Chris")
    fake_api.add("User", email=PAUL, first_name="Paul")
    fake_api.add("User", email="henrik@example.org", first_name="Henrik")      # third owner, without leads
    fake_api.add("Lead", name="L-VOLL", status="Replied", lead_name="Max Mustermann", first_name="Max",
                 last_name="Mustermann", email_id="max@example.org", mobile_no="+49 170 1234567", phone="",
                 city="Bremen", _assign='["{}"]'.format(CHRIS), creation="2026-09-01 10:00:00")
    fake_api.add("Lead", name="L-LEER", status="Open", lead_name="anna@example.org", email_id="anna@example.org",
                 _assign='["{}"]'.format(CHRIS), creation="2026-09-02 10:00:00")
    fake_api.add("Lead", name="L-PAUL", status="Open", lead_name="Paul Kunde", last_name="Kunde",
                 email_id="kunde@example.org", _assign='["{}"]'.format(PAUL), creation="2026-09-02 10:00:00")
    fake_api.add("Lead", name="L-DNC", status="Do Not Contact", email_id="spam@example.org",
                 _assign='["{}"]'.format(CHRIS), creation="2026-09-02 10:00:00")
    fake_api.add("Lead", name="L-FREI", status="Open", email_id="offen@example.org", _assign=None,
                 creation="2026-09-03 10:00:00")
    fake_api.add("Address", address_line1="Musterstraße 5a", pincode="28199", city="Bremen", country="Germany",
                 links=[{"link_doctype": "Lead", "link_name": "L-VOLL"}])
    return fake_api


class TestHelpers:
    def test_addressbook_of(self) -> None:
        assert vx.addressbook_of("Chris") == BOOK
        assert vx.addressbook_of("Anna Lena") == "erpnext-leads-anna-lena"

    def test_card_filename(self) -> None:
        assert vx.card_filename("CRM-LEAD-2026-00001") == "CRM-LEAD-2026-00001.vcf"
        assert vx.card_filename("L 1/2") == "L_1_2.vcf"

    def test_uid_and_marker(self) -> None:
        body = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:L-1\r\nFN:Max\r\nCATEGORIES:ERPNext Lead\r\nEND:VCARD\r\n"
        assert vx.uid_of(body) == "L-1" and vx.is_managed(body)
        assert vx.uid_of("BEGIN:VCARD\nFN:X\n") is None
        assert not vx.is_managed("BEGIN:VCARD\nUID:L-1\nFN:Max\nEND:VCARD\n")
        assert not vx.is_managed("BEGIN:VCARD\nUID:L-1\nCATEGORIES:Privat\nEND:VCARD\n")

    def test_same_card_ignores_server_properties(self) -> None:
        mine = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:L-1\r\nFN:Max\r\nEND:VCARD\r\n"
        theirs = "BEGIN:VCARD\nVERSION:4.0\nPRODID:-//Nextcloud//\nREV:20260904T100000Z\nUID:L-1\nFN:Max\nEND:VCARD\n"
        assert vx.same_card(mine, theirs)
        assert not vx.same_card(mine, theirs.replace("FN:Max", "FN:Moritz"))

    def test_lead_vcard_of_an_incomplete_lead(self, leads: FakeFrappeClient) -> None:
        body = vx.lead_vcard(leads.get_doc("Lead", "L-LEER"), None, "https://erp.example")
        lines = body.split("\r\n")
        assert "UID:L-LEER" in lines and "FN:anna@example.org" in lines          # e-mail as the display name
        assert "EMAIL;TYPE=INTERNET:anna@example.org" in lines
        assert "CATEGORIES:ERPNext Lead" in lines and "NOTE:ERPNext Lead L-LEER (Open)" in lines
        assert "URL:https://erp.example/app/lead/L-LEER" in lines
        assert not any(l.startswith("TEL") or l.startswith("ADR") for l in lines)

    def test_lead_vcard_of_a_complete_lead(self, leads: FakeFrappeClient) -> None:
        address = vx.addresses_for(["L-VOLL"])["L-VOLL"]
        lines = vx.lead_vcard(leads.get_doc("Lead", "L-VOLL"), address, "https://erp.example").split("\r\n")
        assert "FN:Max Mustermann" in lines and "TEL;TYPE=CELL:+49 170 1234567" in lines
        assert "ADR;TYPE=HOME:;;Musterstraße 5a;Bremen;;28199;Germany" in lines


class TestCardDav:
    def test_urls_and_missing_book(self, dav: vx.CardDav) -> None:
        assert dav.addressbook_url(BOOK) == "https://cloud.example/remote.php/dav/addressbooks/users/user/" + BOOK + "/"
        assert dav.exists(BOOK) is False

    def test_create_put_report_delete(self, dav: vx.CardDav) -> None:
        dav.create(BOOK, "ERPNext-Leads Chris")
        assert dav.exists(BOOK) is True
        body = "BEGIN:VCARD\r\nUID:L-1\r\nFN:Max\r\nEND:VCARD\r\n"
        dav.put(BOOK, "L-1.vcf", body)
        cards = dav.cards(BOOK)
        href = dav.session.href(BOOK, "L-1.vcf")
        # the XML parser turns CRLF into LF, so compare the properties, not the bytes
        assert list(cards) == [href] and vx.same_card(cards[href], body)
        dav.delete(href)
        assert dav.cards(BOOK) == {}
        assert [m for m, _ in dav.session.requests] == ["MKCOL", "PROPFIND", "PUT", "REPORT", "DELETE", "REPORT"]

    def test_errors_are_raised(self, dav: vx.CardDav) -> None:
        dav.session.status["PROPFIND"] = 401
        with pytest.raises(RuntimeError, match="401"):
            dav.exists(BOOK)
        dav.session.status.clear()
        dav.create(BOOK, "x")
        dav.session.status["PUT"] = 507
        with pytest.raises(RuntimeError, match="507"):
            dav.put(BOOK, "L-1.vcf", "BEGIN:VCARD\r\nEND:VCARD\r\n")


class TestSelection:
    def test_owner_and_assigned_leads(self, leads: FakeFrappeClient) -> None:
        assert vx.owner_user_id("Chris") == CHRIS and vx.owner_user_id("Niemand") is None
        assert [l["name"] for l in vx.assigned_leads(CHRIS)] == ["L-LEER", "L-VOLL"]      # newest first, no DNC
        assert [l["name"] for l in vx.assigned_leads(PAUL)] == ["L-PAUL"]

    def test_substring_assignment_is_not_matched(self, leads: FakeFrappeClient) -> None:
        leads.add("Lead", name="L-FREMD", status="Open", email_id="x@y.de", _assign='["chris@example.org.uk"]',
                  creation="2026-09-02 10:00:00")
        assert "L-FREMD" not in [l["name"] for l in vx.assigned_leads(CHRIS)]

    def test_addresses_for(self, leads: FakeFrappeClient) -> None:
        found = vx.addresses_for(["L-VOLL", "L-LEER"])
        assert list(found) == ["L-VOLL"] and found["L-VOLL"]["pincode"] == "28199"
        assert vx.addresses_for([]) == {}


class TestExportOwner:
    def test_dry_run_writes_nothing(self, leads: FakeFrappeClient, dav: vx.CardDav,
                                    capsys: pytest.CaptureFixture[str]) -> None:
        dav.session.books[BOOK] = {}
        result = vx.export_owner(dav, "Chris", apply=False)
        assert (result.leads, result.created, result.updated, result.unchanged) == (2, 2, 0, 0)
        assert dav.session.books[BOOK] == {}
        assert "PUT" not in [m for m, _ in dav.session.requests]

    def test_apply_creates_and_is_idempotent(self, leads: FakeFrappeClient, dav: vx.CardDav) -> None:
        dav.session.books[BOOK] = {}
        result = vx.export_owner(dav, "Chris", apply=True)
        assert (result.created, result.updated, result.unchanged, result.errors) == (2, 0, 0, 0)
        assert sorted(dav.session.books[BOOK]) == ["L-LEER.vcf", "L-VOLL.vcf"]
        assert "FN:Max Mustermann" in dav.session.books[BOOK]["L-VOLL.vcf"]
        again = vx.export_owner(dav, "Chris", apply=True)
        assert (again.created, again.updated, again.unchanged) == (0, 0, 2)

    def test_changed_lead_updates_the_card(self, leads: FakeFrappeClient, dav: vx.CardDav) -> None:
        dav.session.books[BOOK] = {}
        vx.export_owner(dav, "Chris", apply=True)
        leads.docs("Lead")["L-LEER"]["mobile_no"] = "+49 171 2223334"
        result = vx.export_owner(dav, "Chris", apply=True)
        assert (result.created, result.updated, result.unchanged) == (0, 1, 1)
        assert "TEL;TYPE=CELL:+49 171 2223334" in dav.session.books[BOOK]["L-LEER.vcf"]

    def test_orphan_card_is_only_deleted_on_request(self, leads: FakeFrappeClient, dav: vx.CardDav,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
        dav.session.books[BOOK] = {}
        vx.export_owner(dav, "Chris", apply=True)
        leads.docs("Lead")["L-LEER"]["status"] = "Do Not Contact"      # no longer to be exported
        result = vx.export_owner(dav, "Chris", apply=True)
        assert (result.obsolete, result.deleted) == (1, 0) and "L-LEER.vcf" in dav.session.books[BOOK]
        assert "mit --delete entfernen" in vx.describe(result)
        result = vx.export_owner(dav, "Chris", apply=True, delete=True)
        assert (result.obsolete, result.deleted) == (1, 1) and "L-LEER.vcf" not in dav.session.books[BOOK]

    def test_foreign_cards_are_untouched(self, leads: FakeFrappeClient, dav: vx.CardDav) -> None:
        private = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:privat-1\r\nFN:Oma\r\nEND:VCARD\r\n"
        dav.session.books[BOOK] = {"oma.vcf": private}
        result = vx.export_owner(dav, "Chris", apply=True, delete=True)
        assert result.obsolete == 0 and dav.session.books[BOOK]["oma.vcf"] == private

    def test_missing_book(self, leads: FakeFrappeClient, dav: vx.CardDav, capsys: pytest.CaptureFixture[str]) -> None:
        result = vx.export_owner(dav, "Chris", apply=True)
        assert result.missing_book and result.created == 0
        assert "Adressbuch {} fehlt (mit --create anlegen)".format(BOOK) in capsys.readouterr().out
        result = vx.export_owner(dav, "Chris", apply=True, create=True)
        assert not result.missing_book and result.created == 2
        assert BOOK in dav.session.books
        assert "bitte in Nextcloud für Chris freigeben" in capsys.readouterr().out

    def test_unknown_owner(self, leads: FakeFrappeClient, dav: vx.CardDav, capsys: pytest.CaptureFixture[str]) -> None:
        result = vx.export_owner(dav, "Niemand", apply=True)
        assert result.unknown_owner and vx.describe(result) == ""
        assert "kein ERPNext-Benutzer" in capsys.readouterr().out


class TestExport:
    def test_all_owners(self, leads: FakeFrappeClient, dav: vx.CardDav, capsys: pytest.CaptureFixture[str]) -> None:
        results = vx.export(["Chris", "Paul"], apply=True, create=True, dav=dav)
        assert [(r.owner, r.created) for r in results] == [("Chris", 2), ("Paul", 1)]
        assert sorted(dav.session.books) == [BOOK, "erpnext-leads-paul"]
        out = capsys.readouterr().out
        assert "vCard-Export nach https://cloud.example" in out and "2 Leads, 2 neu" in out

    def test_without_credentials(self, leads: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                                 capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(vx, "credentials", lambda: (None, None, None))
        assert vx.export(["Chris"]) == []
        assert "Kein Nextcloud-Zugang hinterlegt" in capsys.readouterr().out

    def test_server_error_is_caught(self, leads: FakeFrappeClient, dav: vx.CardDav,
                                    capsys: pytest.CaptureFixture[str]) -> None:
        dav.session.status["PROPFIND"] = 500
        results = vx.export(["Chris"], apply=True, dav=dav)
        assert results[0].errors == 1 and "FEHLER" in capsys.readouterr().out

    def test_credentials_from_settings_and_environment(self, monkeypatch: pytest.MonkeyPatch,
                                                       user_settings: UserSettings) -> None:
        for var in ("NEXTCLOUD_URL", "NEXTCLOUD_USER", "NEXTCLOUD_PASSWORD"):
            monkeypatch.delenv(var, raising=False)
        assert not vx.configured()
        monkeypatch.setenv("NEXTCLOUD_URL", "https://env.example")
        monkeypatch.setenv("NEXTCLOUD_USER", "envuser")
        monkeypatch.setenv("NEXTCLOUD_PASSWORD", "envpass")
        assert vx.credentials() == ("https://env.example", "envuser", "envpass") and vx.configured()
        user_settings["-nextcloud-url-"] = "https://cloud.example"
        assert vx.credentials()[0] == "https://cloud.example"


class TestMain:
    def test_dry_run(self, leads: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                     capsys: pytest.CaptureFixture[str]) -> None:
        session = FakeCardDavSession({BOOK: {}, "erpnext-leads-paul": {}, "erpnext-leads-henrik": {}})
        real = vx.CardDav
        monkeypatch.setattr(vx, "CardDav", lambda url, user, password: real(url, user, password, session=session))
        monkeypatch.setattr("frappeclient.FrappeClient", lambda *a, **k: leads)
        assert vx.main(["--server", "https://srv", "--key", "k", "--secret", "s", "--nextcloud-url", "https://c",
                        "--nextcloud-user", "u", "--nextcloud-password", "p"]) == 0
        assert session.books[BOOK] == {}
        assert "3 Karten zu schreiben" in capsys.readouterr().out

    def test_apply_for_one_owner(self, leads: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                                 capsys: pytest.CaptureFixture[str]) -> None:
        session = FakeCardDavSession()
        real = vx.CardDav
        monkeypatch.setattr(vx, "CardDav", lambda url, user, password: real(url, user, password, session=session))
        monkeypatch.setattr("frappeclient.FrappeClient", lambda *a, **k: leads)
        assert vx.main(["--server", "s", "--key", "k", "--secret", "s", "--owner", "Chris", "--apply", "--create",
                        "--nextcloud-url", "https://c", "--nextcloud-user", "u", "--nextcloud-password", "p"]) == 0
        assert sorted(session.books[BOOK]) == ["L-LEER.vcf", "L-VOLL.vcf"]
        assert "2 Karten geschrieben" in capsys.readouterr().out

    def test_missing_credentials(self, leads: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                                 capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(vx, "credentials", lambda: (None, None, None))
        monkeypatch.setattr("frappeclient.FrappeClient", lambda *a, **k: leads)
        assert vx.main(["--server", "s", "--key", "k", "--secret", "s"]) == 2
        assert "Nextcloud-Zugang fehlt" in capsys.readouterr().out
