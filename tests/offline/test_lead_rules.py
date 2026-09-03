"""Tests for lead_rules.py (sorting of leads created from e-mails)."""
from __future__ import annotations

from typing import Any

import pytest

import lead_rules
from frappeclient import FrappeException
from lead_rules import Decision, Rules, classify
from settings import LEAD_RULE_DOCTYPE, SUPPLIER_DOMAINS_FIELD
from support.fakes import FakeFrappeClient


def comm(sender: str, subject: str = "", content: str = "") -> dict[str, Any]:
    return {"sender": sender, "subject": subject, "content": content}


class TestHelpers:
    def test_registrable_domain(self) -> None:
        assert lead_rules.registrable_domain("service.solarwatt.com") == "solarwatt.com"
        assert lead_rules.registrable_domain("EU.ZCSEND.NET") == "zcsend.net"
        assert lead_rules.registrable_domain("mail.example.co.uk") == "example.co.uk"
        assert lead_rules.registrable_domain("gmx.de") == "gmx.de"
        assert lead_rules.registrable_domain("localhost") == "localhost"

    def test_address_and_domain(self) -> None:
        assert lead_rules.address_of("Anna Müller <Anna.Mueller@Example.DE>") == "anna.mueller@example.de"
        assert lead_rules.address_of(None) == "" and lead_rules.address_of("kein Absender") == ""
        assert lead_rules.domain_of("x@news.example.de") == "example.de"
        assert lead_rules.domain_of("") == ""

    def test_domains_in_text(self) -> None:
        text = "Krannich Solar, info@krannich-solar.com, Rechnung an buchhaltung@bremer-solidarstrom.de, privat: a@gmx.de"
        assert lead_rules.domains_in_text(text) == {"krannich-solar.com"}
        assert lead_rules.domains_in_text("") == set()
        assert lead_rules.domains_in_text("info@o\uFB00gridtec.com") == {"offgridtec.com"}     # PDF ligature
        assert lead_rules.domains_in_text("privat@posteo.org") == set()

    def test_split_domains(self) -> None:
        assert lead_rules.split_domains("krannich-solar.com\nshop.memodo.de, x.example.org") == {
            "krannich-solar.com", "memodo.de", "example.org"}
        assert lead_rules.split_domains(None) == set()

    def test_add_pattern(self) -> None:
        rules = Rules()
        rules.add_pattern("@Newsletter.Example.COM", "Kein Lead")
        rules.add_pattern("news@example.com", "Kein Lead")
        rules.add_pattern("partner.org", "Lead")
        rules.add_pattern("chef@partner.org", "Lead")
        rules.add_pattern("  ", "Kein Lead")
        assert rules.block_domains == {"example.com"} and rules.block_addresses == {"news@example.com"}
        assert rules.allow_domains == {"partner.org"} and rules.allow_addresses == {"chef@partner.org"}


class TestRulesLoad:
    def test_load_rules_and_supplier_domains(self, fake_api: FakeFrappeClient) -> None:
        fake_api.add(LEAD_RULE_DOCTYPE, muster="zcsend.net", wirkung="Kein Lead", deaktiviert=0)
        fake_api.add(LEAD_RULE_DOCTYPE, muster="alt.example", wirkung="Kein Lead", deaktiviert=1)
        fake_api.add(LEAD_RULE_DOCTYPE, muster="partner.org", wirkung="Lead", deaktiviert=0)
        fake_api.add("Supplier", supplier_name="Krannich", **{SUPPLIER_DOMAINS_FIELD: "krannich-solar.com\nkrannich.de"})
        fake_api.add("Supplier", supplier_name="Ohne Domain", **{SUPPLIER_DOMAINS_FIELD: None})
        rules = Rules.load()
        assert rules.loaded
        assert rules.block_domains == {"zcsend.net"} and rules.allow_domains == {"partner.org"}
        assert rules.supplier_domains == {"krannich-solar.com": "Krannich", "krannich.de": "Krannich"}

    def test_missing_doctype_gives_empty_rules(self, fake_api: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
        original = fake_api.get_list

        def get_list(doctype: str, *a: Any, **k: Any) -> Any:
            if doctype == LEAD_RULE_DOCTYPE:
                raise FrappeException("DocType Lead Absenderregel not found")
            return original(doctype, *a, **k)
        monkeypatch.setattr(fake_api, "get_list", get_list)
        rules = Rules.load()
        assert rules.loaded and rules.block_domains == set()
        assert "lead_rules_setup.py" in capsys.readouterr().out


@pytest.fixture
def rules() -> Rules:
    r = Rules()
    r.add_pattern("zcsend.net", "Kein Lead")
    r.add_pattern("spam@gmx.de", "Kein Lead")
    r.add_pattern("partner.org", "Lead")
    r.add_pattern("vip@zcsend.net", "Lead")
    r.supplier_domains = {"krannich-solar.com": "Krannich Solar GmbH & Co KG"}
    return r


class TestClassify:
    def test_block_domain_and_address(self, rules: Rules) -> None:
        assert classify("news@eu.zcsend.net", [comm("news@eu.zcsend.net", "Balkonsolar-Beratung")], rules) == \
            Decision(True, "kein Lead", "Sperrliste: zcsend.net")
        assert classify("spam@gmx.de", [], rules) == Decision(True, "kein Lead", "Sperrliste: spam@gmx.de")

    def test_allow_beats_block(self, rules: Rules) -> None:
        d = classify("vip@zcsend.net", [comm("vip@zcsend.net", "", "unsubscribe")], rules)
        assert d == Decision(False, None, "Freigabe für vip@zcsend.net")
        assert classify("x@partner.org", [comm("x@partner.org", "Rechnung", "abmelden")], rules).auto is False

    def test_supplier_domain(self, rules: Rules) -> None:
        d = classify("order@krannich-solar.com", [comm("order@krannich-solar.com", "Ihre Rechnung 4711")], rules)
        assert d == Decision(True, "kein Lead", "Lieferant Krannich Solar GmbH & Co KG, Betreff 'rechnung'")
        d = classify("anna@krannich-solar.com", [comm("anna@krannich-solar.com", "Frage zu Ihrem Projekt")], rules)
        assert d == Decision(False, "kein Lead", "Absender-Domain gehört zu Lieferant Krannich Solar GmbH & Co KG")
        # a request-like subject is never decided automatically
        d = classify("anna@krannich-solar.com", [comm("anna@krannich-solar.com", "Rechnung und Anfrage Balkonsolar")], rules)
        assert d.auto is False and d.choice == "kein Lead"

    def test_newsletter(self, rules: Rules) -> None:
        content = "<a href='https://x/unsubscribe'>Newsletter abbestellen</a>"
        assert classify("noreply@shop.example", [comm("noreply@shop.example", "Neu", content)], rules) == \
            Decision(True, "kein Lead", "Newsletter-Muster, Absender noreply@shop.example")
        assert classify("Info <info@firma.de>", [comm("info@firma.de", "Aktion", content)], rules).auto is True
        # personal sender with one mail: suggestion only
        d = classify("anna@firma.de", [comm("anna@firma.de", "Aktion", content)], rules)
        assert d == Decision(False, "kein Lead", "Newsletter-Muster in der Mail")
        # ... but three mails make it automatic
        assert classify("anna@firma.de", [comm("anna@firma.de", "A", content)] * 3, rules).auto is True
        # request-like subject prevents automatic marking
        d = classify("noreply@shop.example", [comm("noreply@shop.example", "Ihre Anfrage", content)], rules)
        assert d.auto is False
        # private senders are never marked automatically for newsletter wording (a real lead quoting one)
        d = classify("info.mueller@gmx.de", [comm("info.mueller@gmx.de", "Hallo", content)] * 3, rules)
        assert d == Decision(False, "kein Lead", "Newsletter-Muster in der Mail")

    def test_positive_freemail_and_unknown(self, rules: Rules) -> None:
        assert classify("a@firma.de", [comm("a@firma.de", "Beratung Balkonkraftwerk")], rules) == \
            Decision(False, None, "Betreff enthält 'balkonkraftwerk'")
        assert classify("a@gmail.com", [comm("a@gmail.com", "Hallo")], rules) == Decision(False, None, "Privatadresse")
        assert classify("a@firma.de", [comm("a@firma.de", "Hallo")], rules) == Decision(False, None, "")
        assert classify(None, [], rules) == Decision(False, None, "")

    def test_sender_taken_from_communication(self, rules: Rules) -> None:
        assert classify(None, [comm("news@zcsend.net")], rules).auto is True
        assert classify("", [comm(""), comm("Krannich <order@krannich-solar.com>", "Lieferung")], rules).auto is True


class TestNoteSupplierDomains:
    def test_new_domains_are_recorded(self, fake_api: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        fake_api.add("Supplier", supplier_name="Krannich", **{SUPPLIER_DOMAINS_FIELD: "krannich.de"})
        new = lead_rules.note_supplier_domains("Krannich", "Kontakt: info@krannich-solar.com, privat a@web.de")
        assert new == ["krannich-solar.com"]
        assert fake_api.get_doc("Supplier", "Krannich")[SUPPLIER_DOMAINS_FIELD] == "krannich-solar.com\nkrannich.de"
        assert "krannich-solar.com bei Lieferant Krannich vermerkt" in capsys.readouterr().out
        assert lead_rules.note_supplier_domains("Krannich", "info@krannich-solar.com") == []

    def test_unknown_or_missing_supplier(self, fake_api: FakeFrappeClient) -> None:
        assert lead_rules.note_supplier_domains("???", "a@b.de") == []
        assert lead_rules.note_supplier_domains(None, "a@b.de") == []
        assert lead_rules.note_supplier_domains("Gibt es nicht", "a@b.de") == []
        assert fake_api.calls_of("set_value") == []

    def test_api_error_is_reported(self, fake_api: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                                   capsys: pytest.CaptureFixture[str]) -> None:
        fake_api.add("Supplier", supplier_name="Krannich")

        def fail(*a: Any, **k: Any) -> None:
            raise FrappeException("Field not permitted")
        monkeypatch.setattr(fake_api, "set_value", fail)
        assert lead_rules.note_supplier_domains("Krannich", "info@krannich-solar.com") == []
        assert "nicht am Lieferanten vermerkt" in capsys.readouterr().out
