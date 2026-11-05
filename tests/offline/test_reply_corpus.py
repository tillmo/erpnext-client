"""Tests for reply_corpus.py: pairing the team's replies with the mails they answer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import reply_corpus as rc
from tests.support.fakes import FakeFrappeClient


class TestStripping:
    def test_quote_header_on_one_line(self) -> None:
        text = "Hi Anna,\npasst.\nLG Mia\nAm 18.08.25 um 11:42 schrieb Anna Meier:\n> alte Mail\nnoch alt"
        assert rc.strip_quotes(text) == "Hi Anna,\npasst.\nLG Mia"

    def test_quote_header_wrapped_name_on_next_line(self) -> None:
        text = "Danke! :)\nAm 18.08.25 um 11:42 schrieb\nGeschäftsführung | Beispiel Solar GmbH:\nHallo Mia,"
        assert rc.strip_quotes(text) == "Danke! :)"

    def test_outlook_block_is_a_quote(self) -> None:
        text = "Moin,\n16.1. passt.\nGruß Torsten\nVon: Mia Muster <mia.muster@bremer-solidarstrom.de>\nGesendet: Montag\nAn: x\nBetreff: y\nHi"
        assert rc.strip_quotes(text) == "Moin,\n16.1. passt.\nGruß Torsten"

    def test_lone_von_line_is_a_form_field(self) -> None:
        text = "Von: Max Mustermann\nE-Mail: max@example.org\nNachricht: Ich möchte ein Balkonkraftwerk."
        assert rc.strip_quotes(text) == text

    def test_forwarded_rule_and_gt_lines(self) -> None:
        text = "Hier die Mail.\n> zitiert\n-------- Forwarded Message --------\nSubject: x"
        assert rc.strip_quotes(text) == "Hier die Mail."

    def test_signature_separator(self) -> None:
        assert rc.strip_signature("Hi,\nok.\nLG\n-- \nMia Muster\nBremer SolidarStrom") == "Hi,\nok.\nLG"

    def test_signature_by_name_and_organisation(self) -> None:
        text = "Moin Frank,\nanbei die Rechnung.\nSonnige Grüße\nM. Eng. Ole Beispiel\nBremer SolidarStrom\nAbholung: Freitag"
        assert rc.strip_signature(text, ["Ole Beispiel"]) == "Moin Frank,\nanbei die Rechnung.\nSonnige Grüße"

    def test_name_line_without_organisation_stays(self) -> None:
        text = "Liebe Grüße\nMia Muster"
        assert rc.strip_signature(text, ["Mia Muster"]) == text

    def test_name_from_address(self) -> None:
        assert rc.name_from_address("Ole B <ole.beispiel@bremer-solidarstrom.de>") == "Ole Beispiel"
        assert rc.name_from_address(None) == ""


def mail(name: str, sender: str, subject: str = "Re: Anfrage", content: str = "<p>Hallo,<br>danke für die Anfrage. Ja, das geht.</p>",
         in_reply_to: str | None = None, full_name: str = "", **more: object) -> dict[str, object]:
    return dict(name=name, sender=sender, sender_full_name=full_name, subject=subject, content=content,
                in_reply_to=in_reply_to, communication_date="2026-03-01 10:00:00", reference_doctype="Lead",
                reference_name="CRM-LEAD-2026-00001", recipients="", cc=None, **more)


CUSTOMER = mail("p1", "anna@example.org", subject="Anfrage", content="<p>Was kostet ein Balkonkraftwerk?</p>")
TEAM = "mia.muster@bremer-solidarstrom.de"   # Frappe stores the bare address


class TestPair:
    def test_ok(self) -> None:
        entry, reason = rc.pair(mail("r1", TEAM, in_reply_to="p1", full_name="Mia Muster"), CUSTOMER)
        assert reason == "ok" and entry is not None
        assert entry["question"] == "Was kostet ein Balkonkraftwerk?"
        assert entry["answer"] == "Hallo,\ndanke für die Anfrage. Ja, das geht."
        assert entry["author"] == "mia.muster@bremer-solidarstrom.de"
        assert entry["to"] == "anna@example.org" and entry["domain"] == "example.org"
        assert entry["lead"] == "CRM-LEAD-2026-00001" and entry["date"] == "2026-03-01 10:00:00"

    def test_rejections(self) -> None:
        assert rc.pair(mail("r1", TEAM), None) == (None, "kein Vorgänger")
        assert rc.pair(mail("r1", TEAM, subject="Fwd: Anfrage"), CUSTOMER) == (None, "Weiterleitung")
        assert rc.pair(mail("r1", TEAM), mail("p2", "ole.beispiel@bremer-solidarstrom.de")) == (None, "intern")
        assert rc.pair(mail("r1", TEAM), mail("p3", "noreply@shop.example.org")) == (None, "Automat")
        assert rc.pair(mail("r1", TEAM, content="<p>Danke!</p>"), CUSTOMER) == (None, "leere Antwort")
        assert rc.pair(mail("r1", TEAM), mail("p4", "x@example.org", content="<p>&gt; nur Zitat</p>")) == (None, "leere Anfrage")


class TestBuild:
    def test_build_pairs_and_counts(self, fake_api: FakeFrappeClient) -> None:
        common = dict(sent_or_received="Received", communication_type="Communication")
        fake_api.add("Communication", **CUSTOMER, **common)
        fake_api.add("Communication", **mail("r1", TEAM, in_reply_to="p1", full_name="Mia Muster"), **common)
        fake_api.add("Communication", **mail("r2", TEAM, in_reply_to=None), **common)
        fake_api.add("Communication", **mail("r3", "mattermost@bremer-solidarstrom.de", in_reply_to="p1"), **common)
        old = mail("r4", TEAM, in_reply_to="p1")
        old["communication_date"] = "2023-05-01 10:00:00"
        fake_api.add("Communication", **old, **common)
        entries, outcomes = rc.build("2024-01-01")
        assert [e["reply"] for e in entries] == ["r1"]
        assert dict(outcomes) == {"ok": 1, "kein Vorgänger": 1}
        text = rc.summary(entries, outcomes)
        assert "2 Antworten des Teams geprüft, 1 Paare übernommen" in text
        assert "kein Vorgänger: 1" in text and "2026 1" in text

    def test_save_and_load(self, tmp_path: Path) -> None:
        path = str(tmp_path / "sub" / "corpus.json")
        rc.save([{"reply": "r1", "answer": "ä"}], path)
        assert json.loads(Path(path).read_text(encoding="utf-8")) == [{"reply": "r1", "answer": "ä"}]
        assert rc.load(path) == [{"reply": "r1", "answer": "ä"}]
        assert rc.load(str(tmp_path / "missing.json")) == []
