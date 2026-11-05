"""Tests for reply_knowledge.py: sampling the corpus and drafting the knowledge file."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import reply_knowledge as rk


def entry(i: int, author: str = "mia.muster@bremer-solidarstrom.de", date: str = "2026-02-01 10:00:00",
          supplier: str | None = None, answer_len: int = 300) -> dict[str, Any]:
    return {"reply": "r%d" % i, "parent": "p%d" % i, "date": date, "author": author, "author_name": "",
            "lead": "CRM-LEAD-2026-%05d" % i, "subject": "Re: Anfrage %d" % i, "to": "k%d@example.org" % i,
            "domain": "example.org", "question": "Frage %d?" % i, "answer": "A" * answer_len, "supplier": supplier}


class TestSample:
    def test_stratified_and_filtered(self) -> None:
        entries = [entry(i) for i in range(100)]                                     # one author
        entries += [entry(100 + i, author="ole.beispiel@bremer-solidarstrom.de") for i in range(100)]
        entries += [entry(200 + i, supplier="Beispiel Solar GmbH") for i in range(30)]
        entries += [entry(300, date="2024-05-01 10:00:00"), entry(301, answer_len=10), entry(302, answer_len=5000)]
        chosen = rk.sample(entries, 100, "2025-01-01", seed=3)
        assert len(chosen) == 100
        assert sum(1 for e in chosen if e["supplier"]) == 15
        authors = {e["author"] for e in chosen if not e["supplier"]}
        assert authors == {"mia.muster@bremer-solidarstrom.de", "ole.beispiel@bremer-solidarstrom.de"}
        assert not {e["reply"] for e in chosen} & {"r300", "r301", "r302"}
        assert chosen == rk.sample(entries, 100, "2025-01-01", seed=3)             # deterministic

    def test_author_cap(self) -> None:
        entries = [entry(i) for i in range(100)] + [entry(100 + i, author="x@bremer-solidarstrom.de") for i in range(5)]
        chosen = rk.sample(entries, 50, "2025-01-01", seed=1)
        assert sum(1 for e in chosen if e["author"].startswith("x@")) == 5
        assert sum(1 for e in chosen if e["author"].startswith("mia")) == 35          # 70 % of 50

    def test_prompt_text(self) -> None:
        pairs = [entry(1), entry(2, supplier="Beispiel Solar GmbH")]
        pairs[0]["author_name"] = "Mia Muster"
        text = rk.prompt(pairs)
        assert text.startswith("Hier sind 2 Paare")
        assert "### Paar 1 (Kund*in, Antwort von Mia, 2026-02-01)" in text
        assert "### Paar 2 (Lieferant Beispiel Solar GmbH, Antwort von mia.muster, 2026-02-01)" in text
        assert "Eingehende Mail:\nFrage 1?" in text and "k1@example.org" not in text


class TestDraft:
    def test_greetings_anonymised(self) -> None:
        text = "> Hallo Helga Harms,\n> Moin Tjark, hi Ida,\n> Hallo Ida und Emil Engel,\n> Sehr geehrte Frau Nagel,\nHallo zusammen,\n"
        assert rk.anonymize_greetings(text) == (
            "> Hallo [Vorname],\n> Moin [Vorname],\n> Hallo [Vorname],\n> Sehr geehrte Frau [Vorname],\nHallo zusammen,\n")

    def test_draft_continues_after_output_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[dict[str, Any]]] = []
        answers = iter([("## 1\n> Hallo Helga Harms,\nText bricht ab", "max_tokens"), ("und geht weiter\n", "end_turn")])

        class Stream:
            def __init__(self, messages: list[dict[str, Any]]) -> None:
                calls.append(messages)

            def __enter__(self) -> "Stream":
                return self

            def __exit__(self, *a: Any) -> None:
                pass

            def get_final_message(self) -> Any:
                text, stop = next(answers)
                return SimpleNamespace(model="m", stop_reason=stop, usage=SimpleNamespace(input_tokens=1, output_tokens=2),
                                       content=[SimpleNamespace(type="text", text=text)])

        client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: Stream(kw["messages"])))
        monkeypatch.setattr(rk.claude_parser, "model", lambda: "m")
        result = rk.draft([entry(1)], client=client)
        assert result == "## 1\n> Hallo [Vorname],\nText bricht ab\nund geht weiter\n"
        assert len(calls) == 2
        assert calls[1][1] == {"role": "assistant", "content": "## 1\n> Hallo Helga Harms,\nText bricht ab"}
        assert calls[1][2] == {"role": "user", "content": rk.CONTINUE}

    def test_main_dry_run_and_missing_corpus(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert rk.main(["--corpus", str(tmp_path / "none.json"), "--dry-run"]) == 1
        import reply_corpus
        reply_corpus.save([entry(1), entry(2)], str(tmp_path / "c.json"))
        assert rk.main(["--corpus", str(tmp_path / "c.json"), "--dry-run", "--pairs", "1"]) == 0
        out = capsys.readouterr().out
        assert "Korpus" in out and "1 Paare ausgewählt (0 an Lieferanten)" in out
