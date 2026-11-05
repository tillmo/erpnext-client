"""Draft a reply to an incoming mail with Claude and open it in Thunderbird.

Menu "Lead - Antwort entwerfen": the user picks one of the recent incoming mails (external
senders, newest per sender). The client collects the conversation with that sender from ERPNext
(all Communications sent by or to the address, without quoted text and signatures), the parts of
the knowledge file that fit the request, and the most similar earlier pairs from the reply corpus,
and asks Claude for the reply in the words of the user. The draft opens as a new mail in
Thunderbird (``thunderbird -compose``) with recipient, subject and the quoted original, where it
is edited and sent as usual. Thunderbird's command line cannot set In-Reply-To, so the reply
threads by subject only.

Material (private, from the mytools repository next to this file): ``mytools/reply-knowledge.md``
(``reply_knowledge.py``) and ``mytools/reply-corpus.json`` (``reply_corpus.py``). The stable
parts of the knowledge file (tone, facts, what to ask back) go to Claude as a cached system
prompt; of the model answers only the two or three that match the request are sent.

Settings ("Einstellungen - Antworten"): the sender address, which is also the Thunderbird
identity and selects the corpus examples of that author, an optional display name for the
signature, and the Thunderbird program (default ``thunderbird`` on the PATH, on Windows the
usual installation path). Claude key and model as for the invoice extraction.
"""
from __future__ import annotations

import datetime
import html
import os
import re
import subprocess
import sys
from typing import Any

from gui import easygui, sg

import claude_parser
import lead_rules
import reply_corpus
import settings
from api import Api

KNOWLEDGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mytools', 'reply-knowledge.md')
RECENT_DAYS = 21                       # incoming mails offered for a reply
MAX_CHOICES = 40
THREAD_MAILS = 12                      # last mails of the conversation sent to Claude
MAX_MAIL_CHARS = 3000
MODEL_ANSWERS = 3                      # matching sections of the knowledge file
EXAMPLES = 4                           # similar corpus pairs
STABLE_SECTIONS = ('1.', '2.', '4.')   # knowledge sections that go into the cached system prompt
WINDOWS_THUNDERBIRD = r'C:\Program Files\Mozilla Thunderbird\thunderbird.exe'
STOPWORDS = {'aber', 'alle', 'also', 'auch', 'bitte', 'dann', 'dass', 'dein', 'deine', 'dem', 'den', 'der', 'des',
             'die', 'dies', 'diese', 'doch', 'durch', 'eine', 'einem', 'einen', 'einer', 'eines', 'euch', 'euer',
             'eure', 'für', 'gern', 'gerne', 'gibt', 'grüße', 'habe', 'haben', 'hallo', 'hatte', 'ich', 'ihr',
             'ihre', 'ihnen', 'ist', 'kann', 'können', 'liebe', 'lieber', 'mal', 'mehr', 'mein', 'meine', 'mich',
             'mir', 'mit', 'moin', 'nach', 'nicht', 'noch', 'nur', 'oder', 'schon', 'sehr', 'sein', 'sich', 'sie',
             'sind', 'und', 'uns', 'unser', 'unsere', 'viele', 'vielen', 'vom', 'von', 'war', 'was', 'wenn', 'wie',
             'wir', 'wird', 'wurde', 'würde', 'zum', 'zur', 'über', 'dank', 'danke', 'freundlichen', 'beste',
             'sonnige', 'herzliche', 'solidarstrom', 'bremer', 'solar', 'mail', 'email', 'anfrage'}

SYSTEM = """Du entwirfst E-Mail-Antworten für das Team von Bremer SolidarStrom (Solidarische Ökonomie Bremen e.V.). \
Du schreibst im Namen der Person, die dir genannt wird, in deren Tonfall, wie er in der Wissensdatei und den \
Beispielen zu sehen ist. Regeln:
- Antworte nur mit dem Mailtext: Anrede, Text, Grußformel und Vorname. Kein Betreff, keine Erklärungen, keine Signatur \
mit Adresse (die fügt Thunderbird an).
- Du oder Sie wie im bisherigen Verlauf; bei Erstkontakt wie in der Wissensdatei beschrieben.
- Erfinde keine Fakten, Preise, Termine oder Zusagen. Was nicht in der Wissensdatei, dem Verlauf oder den Beispielen \
steht, formulierst du als Rückfrage oder markierst es mit [bitte prüfen].
- Beantworte alles, was in der Mail gefragt wird, und frage nach, was das Team üblicherweise braucht.
- Kurz und konkret, Aufzählungen bei mehreren Punkten, keine Floskelketten.
- Jeder Absatz ist eine Zeile; Absätze werden durch eine Leerzeile getrennt. Keine Zeilenumbrüche innerhalb eines Absatzes.
- Wenn aus der Mail nicht klar hervorgeht, was die Person will, deute nichts hinein und unterstelle nichts: frage \
freundlich nach, worum es geht. Keine Absage auf Verdacht."""


# ---- knowledge file ---------------------------------------------------------------------------
def split_sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) for every '## ' section of the knowledge file."""
    parts = re.split(r'^## ', text, flags=re.M)
    return [(p.split('\n', 1)[0].strip(), p.split('\n', 1)[1] if '\n' in p else '') for p in parts[1:]]


def split_answers(body: str) -> list[tuple[str, str]]:
    """(heading, body) for every '### ' model answer of section 3."""
    parts = re.split(r'^### ', body, flags=re.M)
    return [(p.split('\n', 1)[0].strip(), p.split('\n', 1)[1] if '\n' in p else '') for p in parts[1:]]


def words(text: str) -> set[str]:
    return {w for w in re.findall(r'[a-zäöüß]{4,}', (text or '').lower()) if w not in STOPWORDS}


def similarity(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class Knowledge:
    def __init__(self, text: str) -> None:
        self.stable = ''
        self.answers: list[tuple[str, str]] = []
        for heading, body in split_sections(text):
            if heading.startswith(STABLE_SECTIONS):
                self.stable += '## ' + heading + '\n' + body
            elif heading.startswith('3.'):
                self.answers = split_answers(body)

    @classmethod
    def load(cls, path: str = KNOWLEDGE_PATH) -> Knowledge | None:
        try:
            with open(path, encoding='utf-8') as f:
                return cls(f.read())
        except OSError:
            return None

    def matching_answers(self, text: str, n: int = MODEL_ANSWERS) -> list[tuple[str, str]]:
        """The model answers whose heading and text share most words with the request."""
        request = words(text)
        scored = []
        for heading, body in self.answers:
            score = similarity(request, words(heading)) * 3 + similarity(request, words(body))
            scored.append((score, heading, body))
        scored.sort(key=lambda s: -s[0])
        return [(h, b) for score, h, b in scored[:n] if score > 0]


def similar_examples(entries: list[dict[str, Any]], text: str, author: str = '', n: int = EXAMPLES) -> list[dict[str, Any]]:
    """The corpus pairs whose incoming mail resembles the request; pairs of the author rank higher."""
    request = words(text)
    scored = []
    for e in entries:
        score = similarity(request, words(e.get('question', '')))
        if score and author and e.get('author') == author:
            score += 0.1
        if score:
            scored.append((score, e))
    scored.sort(key=lambda s: -s[0])
    return [e for _, e in scored[:n]]


# ---- mails from ERPNext ---------------------------------------------------------------------
def address(mail: dict[str, Any]) -> str:
    return lead_rules.address_of(mail.get('sender'))


def is_external(mail: dict[str, Any]) -> bool:
    addr = address(mail)
    return bool(addr) and not reply_corpus.is_team(addr) and not reply_corpus.AUTOMATIC.search(addr)


def recent_mails(days: int = RECENT_DAYS) -> list[dict[str, Any]]:
    """The newest incoming mail of every external sender of the last days, newest first."""
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = Api.api.get_list('Communication', fields=reply_corpus.FIELDS,
                            filters={'sent_or_received': 'Received', 'communication_type': 'Communication',
                                     'communication_date': ['>=', since]},
                            order_by='communication_date desc', limit_page_length=500)
    seen: set[str] = set()
    out = []
    for m in rows:
        addr = address(m)
        if is_external(m) and addr not in seen:
            seen.add(addr)
            out.append(m)
    return out[:MAX_CHOICES]


def conversation(addr: str, limit: int = THREAD_MAILS, until: str = '') -> list[dict[str, Any]]:
    """The last mails exchanged with the address (sent by or to it), oldest first; with ``until``
    only mails up to that date, so that a reply to an older mail does not use what came later."""
    sent = Api.api.get_list('Communication', fields=reply_corpus.FIELDS,
                            filters={'communication_type': 'Communication', 'sender': ['like', '%' + addr + '%']},
                            order_by='communication_date desc', limit_page_length=limit)
    received = Api.api.get_list('Communication', fields=reply_corpus.FIELDS,
                                filters={'communication_type': 'Communication', 'recipients': ['like', '%' + addr + '%']},
                                order_by='communication_date desc', limit_page_length=limit)
    mails = {m['name']: m for m in sent + received}
    ordered = sorted(mails.values(), key=lambda m: m.get('communication_date') or '')
    if until:
        ordered = [m for m in ordered if (m.get('communication_date') or '') <= until]
    return ordered[-limit:]


def later_mails(addr: str, after: str) -> list[dict[str, Any]]:
    """Mails of the address newer than the answered one: the user should know before replying."""
    return [m for m in conversation(addr) if (m.get('communication_date') or '') > after and address(m) == addr]


def choice_text(m: dict[str, Any]) -> str:
    when = (m.get('communication_date') or '')[:16]
    who = m.get('sender_full_name') or address(m)
    return '{}  {}  |  {}'.format(when, who[:30], (m.get('subject') or '')[:60])


def mail_text(m: dict[str, Any]) -> str:
    return reply_corpus.own_text(m)[:MAX_MAIL_CHARS]


def conversation_text(mails: list[dict[str, Any]]) -> str:
    out = []
    for m in mails:
        who = 'Team ({})'.format(m.get('sender_full_name') or address(m)) if reply_corpus.is_team(address(m)) \
            else 'Absender*in ({})'.format(m.get('sender_full_name') or address(m))
        out.append('--- {} am {}: {}\n{}'.format(who, (m.get('communication_date') or '')[:10],
                                                 m.get('subject') or '', mail_text(m)))
    return '\n\n'.join(out)


# ---- prompt and Claude call ------------------------------------------------------------------
def user_prompt(mail: dict[str, Any], thread: list[dict[str, Any]], answers: list[tuple[str, str]],
                examples: list[dict[str, Any]], author_name: str) -> str:
    parts = []
    if answers:
        parts.append('# Passende Musterantworten aus der Wissensdatei\n\n' +
                     '\n\n'.join('### ' + h + '\n' + b.strip() for h, b in answers))
    if examples:
        parts.append('# Ähnliche frühere Anfragen und die Antworten des Teams\n\n' +
                     '\n\n'.join('Anfrage ({}):\n{}\n\nAntwort von {}:\n{}'.format(
                         e.get('date', '')[:10], e.get('question', '')[:1500],
                         (e.get('author_name') or e.get('author', '')).split()[0], e.get('answer', ''))
                         for e in examples))
    earlier = [m for m in thread if m['name'] != mail['name']]
    if earlier:
        parts.append('# Bisheriger Verlauf mit {}\n\n{}'.format(address(mail), conversation_text(earlier)))
    parts.append('# Zu beantwortende Mail\n\nVon: {} <{}>\nDatum: {}\nBetreff: {}\n\n{}'.format(
        mail.get('sender_full_name') or '', address(mail), (mail.get('communication_date') or '')[:16],
        mail.get('subject') or '', mail_text(mail)))
    parts.append('Schreibe die Antwort als {}.'.format(author_name))
    return '\n\n'.join(parts)


def draft(mail: dict[str, Any], thread: list[dict[str, Any]], knowledge: Knowledge, corpus: list[dict[str, Any]],
          author: str, author_name: str, client: Any = None) -> str:
    request = (mail.get('subject') or '') + '\n' + mail_text(mail)
    answers = knowledge.matching_answers(request)
    examples = similar_examples(corpus, request, author)
    client = client or claude_parser._client()
    response = client.messages.create(
        model=claude_parser.model(), max_tokens=2000,
        system=[{'type': 'text', 'text': SYSTEM},
                {'type': 'text', 'text': '# Wissensdatei\n\n' + knowledge.stable,
                 'cache_control': {'type': 'ephemeral', 'ttl': '1h'}}],
        messages=[{'role': 'user', 'content': user_prompt(mail, thread, answers, examples, author_name)}])
    usage = getattr(response, 'usage', None)
    if usage is not None:
        cached = getattr(usage, 'cache_read_input_tokens', 0) or 0
        written = getattr(usage, 'cache_creation_input_tokens', 0) or 0
        print('Claude ({}): {} Eingabe-, {} Ausgabe-Tokens{}{}'.format(
            response.model, usage.input_tokens + cached + written, usage.output_tokens,
            ', davon {} aus dem Cache'.format(cached) if cached else '',
            ', {} in den Cache geschrieben'.format(written) if written else ''))
    if response.stop_reason == 'refusal':
        raise RuntimeError('Claude hat die Anfrage abgelehnt')
    return ''.join(b.text for b in response.content if b.type == 'text').strip()


# ---- Thunderbird -------------------------------------------------------------------------------
def quoted_original(mail: dict[str, Any]) -> str:
    when = (mail.get('communication_date') or '')[:16]
    who = mail.get('sender_full_name') or address(mail)
    lines = ['> ' + l for l in mail_text(mail).split('\n')]
    return 'Am {} schrieb {}:\n{}'.format(when, who, '\n'.join(lines))


def reply_subject(subject: str | None) -> str:
    s = (subject or '').strip()
    return s if re.match(r'(re|aw):', s, re.I) else 'Re: ' + s


def html_body(text: str, mail: dict[str, Any]) -> str:
    """The draft as HTML: a paragraph per text block, the original quoted below. HTML composition
    uses Thunderbird's standard font, plain text would be shown in monospace."""
    paragraphs = []
    for block in re.split(r'\n\s*\n', text.strip()):
        paragraphs.append('<p>' + html.escape(block).replace('\n', '<br>') + '</p>')
    when = (mail.get('communication_date') or '')[:16]
    who = mail.get('sender_full_name') or address(mail)
    quote = '<p>Am {} schrieb {}:</p><blockquote type="cite">{}</blockquote>'.format(
        html.escape(when), html.escape(who), html.escape(mail_text(mail)).replace('\n', '<br>'))
    return ''.join(paragraphs) + quote


def compose_argument(to: str, subject: str, body: str, sender: str = '') -> str:
    """The value of thunderbird -compose: comma separated key='value' pairs. Values are enclosed
    in single quotes, so an apostrophe inside becomes the typographic one."""
    def q(value: str) -> str:
        return "'" + value.replace("'", '’') + "'"
    pairs = []
    if sender:
        pairs.append('from=' + q(sender))
    pairs += ['to=' + q(to), 'subject=' + q(subject), 'format=html', 'body=' + q(body)]
    return ','.join(pairs)


def thunderbird_program() -> str:
    try:
        program = sg.UserSettings().get('-thunderbird-')
    except Exception:
        program = None
    if program:
        return program
    if sys.platform.startswith('win') and os.path.exists(WINDOWS_THUNDERBIRD):
        return WINDOWS_THUNDERBIRD
    return 'thunderbird'


def open_in_thunderbird(to: str, subject: str, body: str, sender: str = '') -> None:
    subprocess.Popen([thunderbird_program(), '-compose', compose_argument(to, subject, body, sender)])


# ---- menu action -------------------------------------------------------------------------------
def reply_settings() -> tuple[str, str]:
    """(sender address, display name) from the settings; the name derives from the address."""
    try:
        s = sg.UserSettings()
        sender = (s.get('-reply-from-') or '').strip()
        name = (s.get('-reply-name-') or '').strip()
    except Exception:
        sender, name = '', ''
    return sender, name or reply_corpus.name_from_address(sender)


def draft_reply() -> None:
    sender, author_name = reply_settings()
    if not sender:
        print('Bitte zuerst unter "Einstellungen - Antworten" die eigene Absenderadresse eintragen')
        return
    if not claude_parser.configured():
        print('Kein Claude-Schlüssel: bitte unter "Einstellungen - Claude" eintragen')
        return
    knowledge = Knowledge.load()
    if knowledge is None:
        print('Wissensdatei {} fehlt (privates Repository mytools)'.format(KNOWLEDGE_PATH))
        return
    corpus = reply_corpus.load()
    mails = recent_mails()
    if not mails:
        print('Keine eingegangenen Mails der letzten {} Tage'.format(RECENT_DAYS))
        return
    texts = [choice_text(m) for m in mails]
    choice = easygui.choicebox('Welche Mail soll beantwortet werden?', 'Antwort entwerfen', texts, preselect=0)
    if not choice:
        return
    mail = mails[texts.index(choice)]
    when = mail.get('communication_date') or ''
    thread = conversation(address(mail), until=when)
    if all(m['name'] != mail['name'] for m in thread):
        thread.append(mail)
    for m in later_mails(address(mail), when):
        print('Achtung: neuere Mail dieses Absenders vom {}: {}'.format((m.get('communication_date') or '')[:16], m.get('subject') or ''))
    print('Entwurf für {} ({} Mails im Verlauf, {} Beispiele im Korpus) ...'.format(
        address(mail), len(thread), len(corpus)))
    try:
        text = draft(mail, thread, knowledge, corpus, sender, author_name)
    except Exception as e:
        print('Entwurf fehlgeschlagen: {}'.format(e))
        return
    open_in_thunderbird(address(mail), reply_subject(mail.get('subject')), html_body(text, mail), sender)
    print('Entwurf in Thunderbird geöffnet: {} - {}'.format(address(mail), reply_subject(mail.get('subject'))))
