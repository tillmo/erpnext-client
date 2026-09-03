"""Tests for lead_rules_setup.py (doctype, supplier field, derived rules, supplier domains, backtest)."""
from __future__ import annotations

from typing import Any

import pytest

import lead_rules_setup as setup
from lead_rules import Rules
from settings import LEAD_RULE_DOCTYPE, SUPPLIER_DOMAINS_FIELD
from support.fakes import FakeFrappeClient


class TestServerObjects:
    def test_doctype(self, fake_api: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        assert setup.ensure_rule_doctype(fake_api, apply=False) is False
        assert fake_api.get_list("DocType") == []
        assert setup.ensure_rule_doctype(fake_api, apply=True) is True
        assert setup.ensure_rule_doctype(fake_api, apply=False) is True
        doc = fake_api.get_doc("DocType", LEAD_RULE_DOCTYPE)
        assert doc["custom"] == 1 and doc["autoname"] == "field:muster"
        assert [f["fieldname"] for f in doc["fields"]] == ["muster", "wirkung", "quelle", "bemerkung", "deaktiviert"]
        assert {p["role"] for p in doc["permissions"]} == {"System Manager", "Sales Manager", "Sales User"}
        assert "fehlt" in capsys.readouterr().out

    def test_supplier_field(self, fake_api: FakeFrappeClient) -> None:
        assert setup.ensure_supplier_field(fake_api, apply=False) is False
        assert setup.ensure_supplier_field(fake_api, apply=True) is True
        assert setup.ensure_supplier_field(fake_api, apply=True) is True
        fields = fake_api.get_list("Custom Field", fields=["dt", "fieldname", "fieldtype"])
        assert fields == [{"dt": "Supplier", "fieldname": SUPPLIER_DOMAINS_FIELD, "fieldtype": "Small Text"}]


LEADS: list[dict[str, Any]] = [
    {"name": "L1", "status": "Do Not Contact", "email_id": "a@eu.zcsend.net", "_assign": None},
    {"name": "L2", "status": "Do Not Contact", "email_id": "b@zcsend.net", "_assign": None},
    {"name": "L3", "status": "Do Not Contact", "email_id": "c@solo.example", "_assign": None},      # only one lead
    {"name": "L4", "status": "Do Not Contact", "email_id": "d@mixed.example", "_assign": None},
    {"name": "L5", "status": "Do Not Contact", "email_id": "e@mixed.example", "_assign": None},
    {"name": "L6", "status": "Converted", "email_id": "f@mixed.example", "_assign": None},          # counterexample
    {"name": "L7", "status": "Do Not Contact", "email_id": "g@assigned.example", "_assign": None},
    {"name": "L8", "status": "Do Not Contact", "email_id": "h@assigned.example", "_assign": None},
    {"name": "L9", "status": "Open", "email_id": "i@assigned.example", "_assign": '["chris@example.org"]'},
    {"name": "L10", "status": "Do Not Contact", "email_id": "j@gmail.com", "_assign": None},
    {"name": "L11", "status": "Do Not Contact", "email_id": "k@gmail.com", "_assign": None},
    {"name": "L12", "status": "Do Not Contact", "email_id": None, "_assign": None},
    {"name": "L13", "status": "Do Not Contact", "email_id": "l@open.example", "_assign": None},
    {"name": "L14", "status": "Do Not Contact", "email_id": "m@open.example", "_assign": None},
    {"name": "L15", "status": "Open", "email_id": "n@open.example", "_assign": None},                # undecided: no counterexample
]


class TestDeriveRules:
    def test_derive_domain_rules(self) -> None:
        rules = setup.derive_domain_rules(LEADS)
        assert [r["muster"] for r in rules] == ["open.example", "zcsend.net"]
        assert rules[1]["wirkung"] == "Kein Lead" and rules[1]["quelle"] == "Historie"
        assert rules[1]["bemerkung"].startswith("2 Leads 'Do Not Contact'")

    def test_min_dnc(self) -> None:
        assert "solo.example" in [r["muster"] for r in setup.derive_domain_rules(LEADS, min_dnc=1)]

    def test_apply_rules_skips_existing(self, fake_api: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        fake_api.add(LEAD_RULE_DOCTYPE, muster="ZCSEND.net", wirkung="Kein Lead")
        rules = setup.derive_domain_rules(LEADS)
        assert setup.apply_rules(fake_api, rules, apply=False) == 1
        assert len(fake_api.get_list(LEAD_RULE_DOCTYPE)) == 1
        assert setup.apply_rules(fake_api, rules, apply=True) == 1
        stored = fake_api.get_list(LEAD_RULE_DOCTYPE, fields=["muster", "quelle"])
        assert sorted(stored, key=lambda r: r["muster"].lower()) == [{"muster": "open.example", "quelle": "Historie"},
                                                                     {"muster": "ZCSEND.net", "quelle": None}]
        assert "1 Absenderregeln angelegt, 1 gab es schon" in capsys.readouterr().out


class TestSupplierDomains:
    @pytest.fixture
    def invoices(self, fake_api: FakeFrappeClient) -> FakeFrappeClient:
        fake_api.add("Supplier", supplier_name="Krannich", **{SUPPLIER_DOMAINS_FIELD: "krannich.de"})
        fake_api.add("Supplier", supplier_name="Memodo", **{SUPPLIER_DOMAINS_FIELD: None})
        fake_api.add("Supplier", supplier_name="Scan")
        for i, (sup, url) in enumerate([("Krannich", "/private/files/k1.pdf"), ("Krannich", "/private/files/k2.pdf"),
                                        ("Krannich", "/private/files/k3.pdf"), ("Memodo", "/private/files/m.pdf"),
                                        ("Scan", "/private/files/s.pdf"), ("Fremd", "/private/files/f.pdf")]):
            fake_api.add("Purchase Invoice", name=f"EK {i}", supplier=sup, supplier_invoice=url, docstatus=1)
        fake_api.add("Purchase Invoice", name="EK storniert", supplier="Memodo", supplier_invoice="/private/files/x.pdf", docstatus=2)
        texts = {"/private/files/k1.pdf": b"alt: uralt@krannich-old.com", "/private/files/k2.pdf": b"info@krannich-solar.com",
                 "/private/files/k3.pdf": b"service@krannich-solar.com und a@gmx.de", "/private/files/m.pdf": b"shop@memodo.de",
                 "/private/files/s.pdf": b"   ", "/private/files/f.pdf": b"x@fremd.de"}
        for url, content in texts.items():
            fake_api.add_file(url, content)
        return fake_api

    def test_extract(self, invoices: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        result = setup.extract_supplier_domains(invoices, apply=False, per_supplier=2, text_of=lambda b: b.decode())
        assert result == {"Krannich": ["krannich-solar.com"], "Memodo": ["memodo.de"]}     # only the two most recent PDFs
        assert invoices.calls_of("set_value") == []
        assert "1 PDFs ohne Text" in capsys.readouterr().out
        result = setup.extract_supplier_domains(invoices, apply=True, per_supplier=2, text_of=lambda b: b.decode())
        assert result == {"Krannich": ["krannich-solar.com"], "Memodo": ["memodo.de"]}
        assert invoices.get_doc("Supplier", "Krannich")[SUPPLIER_DOMAINS_FIELD] == "krannich-solar.com\nkrannich.de"
        assert invoices.get_doc("Supplier", "Memodo")[SUPPLIER_DOMAINS_FIELD] == "memodo.de"
        assert setup.extract_supplier_domains(invoices, apply=True, per_supplier=2, text_of=lambda b: b.decode()) == {}


class TestBacktest:
    def test_counts_and_false_auto(self, fake_api: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        fake_api.add("Lead", name="D1", status="Do Not Contact", email_id="a@zcsend.net", creation="2025-01-01 10:00:00")
        fake_api.add("Lead", name="D2", status="Do Not Contact", email_id="b@firma.de", creation="2025-01-01 10:00:00")
        fake_api.add("Lead", name="G1", status="Converted", email_id="c@gmail.com", creation="2025-01-01 10:00:00")
        fake_api.add("Lead", name="G2", status="Replied", email_id="d@zcsend.net", creation="2025-01-01 10:00:00")
        fake_api.add("Lead", name="NEU", status="Do Not Contact", email_id="e@zcsend.net", creation="2026-01-01 10:00:00")
        for name, sender, subject in [("D1", "a@zcsend.net", "News"), ("D2", "b@firma.de", "Hallo"),
                                      ("G1", "c@gmail.com", "Beratung"), ("G2", "d@zcsend.net", "Anfrage")]:
            fake_api.add("Communication", reference_doctype="Lead", reference_name=name, sender=sender, subject=subject, content="")
        rules = Rules()
        rules.add_pattern("zcsend.net", "Kein Lead")
        counts = setup.backtest(fake_api, rules, cutoff="2025-11-03")
        assert counts == {("Do Not Contact", "automatisch"): 1, ("Do Not Contact", "Frage"): 1,
                          ("echte Leads", "Frage"): 1, ("echte Leads", "automatisch"): 1}
        out = capsys.readouterr().out
        assert "G2  zcsend.net  Sperrliste: zcsend.net" in out and "Rückrechnung (Leads vor 2025-11-03)" in out


class TestMain:
    def test_dry_run(self, fake_api: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                     capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(setup, "FrappeClient", lambda url, api_key=None, api_secret=None: fake_api)
        for lead in LEADS:
            fake_api.add("Lead", **lead)
        assert setup.main(["--server", "https://srv", "--key", "k", "--secret", "s", "--backtest"]) == 0
        out = capsys.readouterr().out
        assert "2 Sperrregeln aus 15 Leads abgeleitet" in out and "fehlt" in out
        assert "Rückrechnung mit den abgeleiteten Regeln" in out
        assert fake_api.get_list("DocType") == [] and fake_api.get_list(LEAD_RULE_DOCTYPE) == []

    def test_apply(self, fake_api: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(setup, "FrappeClient", lambda url, api_key=None, api_secret=None: fake_api)
        for lead in LEADS:
            fake_api.add("Lead", **lead)
        assert setup.main(["--server", "https://srv", "--key", "k", "--secret", "s", "--apply", "--pdfs-per-supplier", "0"]) == 0
        assert len(fake_api.get_list("DocType")) == 1 and len(fake_api.get_list("Custom Field")) == 1
        assert sorted(r["muster"] for r in fake_api.get_list(LEAD_RULE_DOCTYPE, fields=["muster"])) == ["open.example", "zcsend.net"]
