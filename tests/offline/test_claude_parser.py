"""Tests for claude_parser.py (invoice extraction with Claude, API faked)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import claude_parser
from support.stubs import UserSettings

GOOD: dict[str, Any] = {"supplier": "Muster Solartechnik GmbH", "supplier_tax_id": "DE123456789", "bill_no": "2026-0815", "posting_date": "2026-09-03",
        "order_id": None, "total": 115.0, "grand_total": 136.85, "shipping": 15.0, "skonto_percent": None,
        "taxes": [{"rate": 19, "net": 115.0, "tax_amount": 21.85}],
        "items": [{"item_code": "MS-1", "description": "Montageschiene 2m", "qty": 2, "uom": "Stk", "rate": 50.0, "amount": 100.0}]}


class FakeClient:
    """Returns the prepared answers one after the other and records the requests."""

    def __init__(self, answers: list[dict[str, Any]], stop_reason: str = "end_turn") -> None:
        self.answers = list(answers)
        self.requests: list[dict[str, Any]] = []
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        data = self.answers.pop(0)
        return SimpleNamespace(stop_reason=self.stop_reason, model=kwargs["model"],
                               content=[SimpleNamespace(type="text", text=json.dumps(data))],
                               usage=SimpleNamespace(input_tokens=3000, output_tokens=200),
                               stop_details=SimpleNamespace(explanation="nein"))


class TestCheck:
    def test_consistent(self) -> None:
        assert claude_parser.check(GOOD) == []

    def test_inconsistencies(self) -> None:
        bad = dict(GOOD, grand_total=140.0, items=[dict(GOOD["items"][0], amount=90.0)])
        problems = claude_parser.check(bad)
        assert any("grand_total" in p for p in problems)
        assert any("Positionen" in p for p in problems)
        assert any("Montageschiene" in p for p in problems)
        assert claude_parser.check(dict(GOOD, taxes=[{"rate": 19, "net": 115.0, "tax_amount": 10.0}])) != []

    def test_empty(self) -> None:
        assert claude_parser.check({"total": 0, "grand_total": 0, "taxes": [], "items": []}) == []


class TestConfiguration:
    def test_key_from_settings_or_environment(self, monkeypatch: pytest.MonkeyPatch, user_settings: UserSettings) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        user_settings.delete_entry("-claude-key-")
        assert not claude_parser.configured()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
        assert claude_parser.api_key() == "env-key"
        user_settings["-claude-key-"] = "settings-key"
        assert claude_parser.api_key() == "settings-key" and claude_parser.configured()
        assert claude_parser.model() == "claude-opus-5"
        user_settings["-claude-model-"] = "claude-sonnet-5"
        assert claude_parser.model() == "claude-sonnet-5"


class TestExtract:
    def test_request_shape_and_result(self) -> None:
        client = FakeClient([GOOD])
        d = claude_parser.extract(b"%PDF-1.4 test", supplier_hint="Muster Solartechnik GmbH", client=client,
                                  suppliers=["Krannich Solar GmbH & Co KG", "Muster Solartechnik GmbH"])
        assert d["source"] == "claude" and d["problems"] == [] and d["bill_no"] == "2026-0815"
        req = client.requests[0]
        assert req["model"] == "claude-opus-5" and req["output_config"]["format"]["schema"] is claude_parser.SCHEMA
        # rules first, then the cached supplier list
        assert req["system"][0]["text"] == claude_parser.SYSTEM and "cache_control" not in req["system"][0]
        assert "Krannich Solar GmbH & Co KG\nMuster Solartechnik GmbH" in req["system"][1]["text"]
        assert req["system"][1]["cache_control"] == {"type": "ephemeral"}
        assert req["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in req["betas"]
        content = req["messages"][0]["content"]
        assert content[0]["type"] == "document" and content[0]["source"]["media_type"] == "application/pdf"
        assert content[0]["source"]["data"] == "JVBERi0xLjQgdGVzdA=="
        assert "Muster Solartechnik GmbH" in content[1]["text"]

    def test_second_attempt_on_inconsistency(self, capsys: pytest.CaptureFixture[str]) -> None:
        bad = dict(GOOD, grand_total=200.0)
        client = FakeClient([bad, GOOD])
        d = claude_parser.extract(b"pdf", client=client)
        assert d["grand_total"] == 136.85 and d["problems"] == []
        assert len(client.requests) == 2
        second = client.requests[1]["messages"]
        assert second[1]["role"] == "assistant" and second[2]["role"] == "user" and "grand_total" in second[2]["content"]
        assert "zweiter Versuch" in capsys.readouterr().out

    def test_second_attempt_not_worse(self, capsys: pytest.CaptureFixture[str]) -> None:
        bad = dict(GOOD, grand_total=200.0)
        worse = dict(bad, total=1.0)
        d = claude_parser.extract(b"pdf", client=FakeClient([bad, worse]))
        assert d["grand_total"] == 200.0 and len(d["problems"]) == 1
        assert "Warnung" in capsys.readouterr().out

    def test_refusal_raises(self) -> None:
        with pytest.raises(RuntimeError, match="abgelehnt"):
            claude_parser.extract(b"pdf", client=FakeClient([GOOD], stop_reason="refusal"))

    def test_without_supplier_list(self) -> None:
        client = FakeClient([GOOD])
        claude_parser.extract(b"pdf", client=client)
        assert client.requests[0]["system"] == [{"type": "text", "text": claude_parser.SYSTEM}]
