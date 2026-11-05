"""Tests for reply_draft.py: choosing the mail, collecting material, the Claude prompt, Thunderbird."""
from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any

import pytest

import reply_draft as rd
from support.fakes import FakeFrappeClient
from support.stubs import EasyguiStub, UserSettings

KNOWLEDGE = """# Wissensdatei

## 1. Tonfall und Form
Duzen ist die Regel.

## 2. Fakten und Standardangaben
Abholung in der Schongauer Str. 7.

## 3. Standardantworten je Anliegen

### 3.1 Anfrage Balkonkraftwerk
Aufbau: Dank, Fotos erbitten, Preise nennen.

### 3.2 Terminabsprache
Termin bestätigen, Handynummer nennen.

### 3.3 Lieferantenbestellung
Bestellung mit Artikelnummern.

## 4. Was das Team üblicherweise zurückfragt
Fotos vom Balkon.

## 5. Unklar
Prüfliste.
"""

TEAM = 'mia.muster@bremer-solidarstrom.de'


def comm(name: str, sender: str, date: str, subject: str = 'Anfrage', content: str = '<p>Hallo, was kostet ein Balkonkraftwerk?</p>',
         recipients: str = '', full_name: str = '') -> dict[str, Any]:
    return dict(name=name, sender=sender, sender_full_name=full_name, recipients=recipients, cc=None, subject=subject,
                content=content, communication_date=date, in_reply_to=None, reference_doctype='Lead',
                reference_name='CRM-LEAD-2026-00001', sent_or_received='Received', communication_type='Communication')


def today(days_ago: int = 0, hour: str = '10:00:00') -> str:
    return (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat() + ' ' + hour


class TestKnowledge:
    def test_stable_and_matching_answers(self) -> None:
        k = rd.Knowledge(KNOWLEDGE)
        assert '## 1. Tonfall' in k.stable and '## 2. Fakten' in k.stable and '## 4. Was' in k.stable
        assert '3.1' not in k.stable and 'Prüfliste' not in k.stable
        assert [h for h, _ in k.answers] == ['3.1 Anfrage Balkonkraftwerk', '3.2 Terminabsprache', '3.3 Lieferantenbestellung']
        best = k.matching_answers('Anfrage Balkonkraftwerk\nWas kostet ein Balkonkraftwerk mit Preisen?', n=2)
        assert [h for h, _ in best][0] == '3.1 Anfrage Balkonkraftwerk'
        assert k.matching_answers('xyz') == []

    def test_load_missing(self, tmp_path: Any) -> None:
        assert rd.Knowledge.load(str(tmp_path / 'none.md')) is None

    def test_similar_examples_prefer_author(self) -> None:
        corpus = [{'question': 'Was kostet ein Balkonkraftwerk mit zwei Modulen?', 'answer': 'A', 'author': 'x@bremer-solidarstrom.de'},
                  {'question': 'Was kostet ein Balkonkraftwerk mit zwei Modulen?', 'answer': 'B', 'author': TEAM},
                  {'question': 'Rechnung für die Solaranlage', 'answer': 'C', 'author': TEAM}]
        best = rd.similar_examples(corpus, 'Balkonkraftwerk kostet Module', author=TEAM, n=2)
        assert [e['answer'] for e in best] == ['B', 'A']


class TestMails:
    def test_recent_mails_newest_per_external_sender(self, fake_api: FakeFrappeClient) -> None:
        fake_api.add('Communication', **comm('c1', 'anna@example.org', today(1)))
        fake_api.add('Communication', **comm('c2', 'anna@example.org', today(3)))
        fake_api.add('Communication', **comm('c3', TEAM, today(0)))
        fake_api.add('Communication', **comm('c4', 'noreply@shop.example.org', today(0)))
        fake_api.add('Communication', **comm('c5', 'old@example.org', today(40)))
        fake_api.add('Communication', **comm('c6', 'bert@example.org', today(0)))
        assert [m['name'] for m in rd.recent_mails()] == ['c6', 'c1']

    def test_conversation_by_address(self, fake_api: FakeFrappeClient) -> None:
        fake_api.add('Communication', **comm('c1', 'anna@example.org', '2026-03-01 10:00:00'))
        fake_api.add('Communication', **comm('c2', TEAM, '2026-03-02 10:00:00', recipients='Anna <anna@example.org>',
                                             content='<p>Hallo Anna,<br>gern. LG Mia</p>', full_name='Mia Muster'))
        fake_api.add('Communication', **comm('c3', 'other@example.org', '2026-03-03 10:00:00'))
        thread = rd.conversation('anna@example.org')
        assert [m['name'] for m in thread] == ['c1', 'c2']
        assert [m['name'] for m in rd.conversation('anna@example.org', until='2026-03-01 10:00:00')] == ['c1']
        fake_api.add('Communication', **comm('c4', 'anna@example.org', '2026-03-05 10:00:00', subject='Nachtrag'))
        assert [m['name'] for m in rd.later_mails('anna@example.org', '2026-03-01 10:00:00')] == ['c4']
        text = rd.conversation_text(thread)
        assert 'Absender*in (anna@example.org) am 2026-03-01' in text and 'Team (Mia Muster) am 2026-03-02' in text


class TestPromptAndThunderbird:
    def test_user_prompt(self) -> None:
        mail = comm('c1', 'anna@example.org', '2026-03-01 10:00:00', full_name='Anna Meier')
        earlier = comm('c0', TEAM, '2026-02-01 10:00:00', content='<p>Frühere Mail</p>', full_name='Mia Muster')
        text = rd.user_prompt(mail, [earlier, mail], [('3.1 Anfrage', 'Aufbau')],
                              [{'date': '2026-01-01', 'question': 'Q', 'answer': 'A', 'author_name': 'Mia Muster'}], 'Mia')
        assert '### 3.1 Anfrage\nAufbau' in text
        assert 'Anfrage (2026-01-01):\nQ\n\nAntwort von Mia:\nA' in text
        assert '# Bisheriger Verlauf mit anna@example.org' in text and 'Frühere Mail' in text
        assert 'Von: Anna Meier <anna@example.org>' in text and text.endswith('Schreibe die Antwort als Mia.')

    def test_draft_calls_claude_with_cached_knowledge(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        calls: list[dict[str, Any]] = []

        def create(**kw: Any) -> Any:
            calls.append(kw)
            return SimpleNamespace(model='m', stop_reason='end_turn', content=[SimpleNamespace(type='text', text='Hallo Anna,\nja.\nLG Mia')],
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=100, cache_creation_input_tokens=7))
        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        monkeypatch.setattr(rd.claude_parser, 'model', lambda: 'm')
        mail = comm('c1', 'anna@example.org', '2026-03-01 10:00:00')
        text = rd.draft(mail, [mail], rd.Knowledge(KNOWLEDGE), [], TEAM, 'Mia', client=client)
        assert text == 'Hallo Anna,\nja.\nLG Mia'
        kw = calls[0]
        assert kw['model'] == 'm' and kw['system'][0]['text'] == rd.SYSTEM
        assert kw['system'][1]['cache_control'] == {'type': 'ephemeral', 'ttl': '1h'} and '## 1. Tonfall' in kw['system'][1]['text']
        assert '3.1 Anfrage Balkonkraftwerk' in kw['messages'][0]['content']
        assert '117 Eingabe-, 5 Ausgabe-Tokens, davon 100 aus dem Cache, 7 in den Cache geschrieben' in capsys.readouterr().out

    def test_compose_argument_and_subject(self) -> None:
        arg = rd.compose_argument('anna@example.org', "Re: Anfrage, geht's?", "Hallo Anna,\ngeht's.\nLG", 'mia@x.de')
        assert arg == "from='mia@x.de',to='anna@example.org',subject='Re: Anfrage, geht’s?',format=html,body='Hallo Anna,\ngeht’s.\nLG'"
        assert rd.reply_subject('Anfrage') == 'Re: Anfrage' and rd.reply_subject('AW: Anfrage') == 'AW: Anfrage'
        assert rd.reply_subject(None) == 'Re: '

    def test_quoted_original_and_html_body(self) -> None:
        mail = comm('c1', 'anna@example.org', '2026-03-01 10:00:00', full_name='Anna Meier', content='<p>Zeile 1<br>Zeile &lt;2&gt;</p>')
        assert rd.quoted_original(mail) == 'Am 2026-03-01 10:00 schrieb Anna Meier:\n> Zeile 1\n> Zeile <2>'
        assert rd.html_body('Hallo Anna,\n\nja & nein.\n- a\n- b\n\nLG\nMia', mail) == (
            '<p>Hallo Anna,</p><p>ja &amp; nein.<br>- a<br>- b</p><p>LG<br>Mia</p>'
            '<p>Am 2026-03-01 10:00 schrieb Anna Meier:</p><blockquote type="cite">Zeile 1<br>Zeile &lt;2&gt;</blockquote>')

    def test_thunderbird_program_setting(self, user_settings: UserSettings) -> None:
        user_settings['-thunderbird-'] = '/opt/tb/thunderbird'
        assert rd.thunderbird_program() == '/opt/tb/thunderbird'
        user_settings['-thunderbird-'] = ''
        assert rd.thunderbird_program() in ('thunderbird', rd.WINDOWS_THUNDERBIRD)


class TestDraftReply:
    def test_end_to_end(self, fake_api: FakeFrappeClient, gui: EasyguiStub, user_settings: UserSettings,
                        monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]) -> None:
        user_settings['-reply-from-'] = TEAM
        user_settings['-claude-key-'] = 'k'
        path = tmp_path / 'k.md'
        path.write_text(KNOWLEDGE, encoding='utf-8')
        monkeypatch.setattr(rd, 'KNOWLEDGE_PATH', str(path))
        monkeypatch.setattr(rd.reply_corpus, 'load', lambda path=None: [])
        fake_api.add('Communication', **comm('c1', 'anna@example.org', today(1), subject='Balkonkraftwerk', full_name='Anna Meier'))
        gui.answers['choicebox'] = lambda msg, title, choices, **kw: choices[0]
        monkeypatch.setattr(rd, 'draft', lambda *a, **k: 'Hallo Anna,\nja.\nLG Mia')
        opened: list[list[str]] = []
        monkeypatch.setattr(rd.subprocess, 'Popen', lambda argv: opened.append(argv))
        rd.draft_reply()
        assert opened and opened[0][1] == '-compose'
        arg = opened[0][2]
        assert arg.startswith("from='{}',to='anna@example.org',subject='Re: Balkonkraftwerk',format=html,body='<p>Hallo Anna,<br>ja.<br>LG Mia</p>".format(TEAM))
        assert '<blockquote type="cite">Hallo, was kostet ein Balkonkraftwerk?</blockquote>' in arg
        out = capsys.readouterr().out
        assert 'Entwurf in Thunderbird geöffnet: anna@example.org - Re: Balkonkraftwerk' in out
        assert 'Achtung' not in out

    def test_missing_settings(self, user_settings: UserSettings, capsys: pytest.CaptureFixture[str]) -> None:
        user_settings['-reply-from-'] = ''
        rd.draft_reply()
        assert 'Absenderadresse' in capsys.readouterr().out
