"""Corpus of the team's manually written e-mail replies, taken from ERPNext.

The central inbox receives a copy of every mail the team sends, so ERPNext holds thousands of
replies to customers and suppliers as Communications. Each reply that carries an In-Reply-To
header points at the mail it answers (``in_reply_to`` is the name of that Communication). The
pairs "incoming mail -> our reply" are the material from which Claude can draft new replies in
the team's own words: the most similar earlier pairs go into the prompt as examples.

What goes into the corpus: replies from the team's own domains (``settings.OWN_DOMAINS``) to an
external sender, without quoted earlier mails and without the signature, with the stripped text
of the mail they answer. Left out: internal mails, forwards, replies to automatic senders, empty
replies. The corpus holds personal data and therefore lives outside the repository, by default in
``~/.config/erpnext-client/reply-corpus.json``.

Usage:
    python3 reply_corpus.py --server URL --key KEY --secret SECRET [--out FILE] [--since 2024-01-01]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from typing import Any

import lead_rules
import settings
import utils
from api import Api
from frappeclient import FrappeClient

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mytools', 'reply-corpus.json')
DEFAULT_SINCE = '2024-01-01'
CHUNK = 100                                   # names per get_list (GET: keep the URL short)
MIN_ANSWER = 20                               # characters; shorter replies say nothing
FORWARD = re.compile(r'^\s*(fwd?|wg|weiterleitung)\s*:', re.I)
AUTOMATIC = re.compile(r'mailer-daemon|no-?reply|do-?not-?reply|postmaster|notification|newsletter|'
                       r'mattermost|wordpress|^termine@', re.I)
QUOTE_START = re.compile(r'^\s*(Am .{6,80} schrieb(\s.*)?|On .{6,80} wrote:|'
                         r'-{2,}\s*(Ursprüngliche|Original|Weitergeleitete|Forwarded)\b.*)\s*$', re.I)
OUTLOOK_FROM = re.compile(r'^\s*(Von|From):\s*\S', re.I)
OUTLOOK_SENT = re.compile(r'^\s*(Gesendet|Sent|Datum|Date):\s*\S', re.I)
SIGNATURE_SEPARATOR = re.compile(r'^-- ?$')
ORGANISATION = re.compile(r'Bremer SolidarStrom|Solidarische Ökonomie|Café Sunshine', re.I)
FIELDS = ['name', 'sender', 'sender_full_name', 'recipients', 'cc', 'subject', 'content',
          'communication_date', 'in_reply_to', 'reference_doctype', 'reference_name']


def strip_quotes(text: str) -> str:
    """The mail's own lines: nothing from the first quote header on, no '>' lines. A quote header
    is "Am ... schrieb ...:" (the name may follow on the next line), "On ... wrote:", an
    "----- Ursprüngliche Nachricht -----" rule, or an Outlook block "Von: ..." followed within
    three lines by "Gesendet: ..." (a lone "Von:" line may be a web form field)."""
    lines = (text or '').replace('\r', '').split('\n')
    kept = []
    for i, line in enumerate(lines):
        if QUOTE_START.match(line):
            break
        if OUTLOOK_FROM.match(line) and any(OUTLOOK_SENT.match(l) for l in lines[i + 1:i + 4]):
            break
        if line.lstrip().startswith('>'):
            continue
        kept.append(line.rstrip())
    return '\n'.join(kept).strip()


def name_from_address(address: str | None) -> str:
    """'mia.muster@...' -> 'Mia Muster'."""
    local = lead_rules.address_of(address).split('@')[0]
    return ' '.join(p.capitalize() for p in re.split(r'[._-]+', local) if p)


def strip_signature(text: str, author_names: list[str] | None = None) -> str:
    """Cut the signature: from the '-- ' separator, or from a line ending with the author's name
    ("M. Eng. Mia Muster") when the organisation follows within the next three lines."""
    lines = text.split('\n')
    names = {n.strip() for n in (author_names or []) if n and n.strip()}
    for i, line in enumerate(lines):
        if SIGNATURE_SEPARATOR.match(line):
            return '\n'.join(lines[:i]).strip()
        if any(line.strip().endswith(n) for n in names) and any(ORGANISATION.search(l) for l in lines[i + 1:i + 4]):
            return '\n'.join(lines[:i]).strip()
    return text.strip()


def own_text(mail: dict[str, Any]) -> str:
    """The text a mail adds to the thread: no HTML, no quotes, no signature."""
    text = utils.html_to_text(mail.get('content') or '')
    names = [mail.get('sender_full_name') or '', name_from_address(mail.get('sender'))]
    return strip_signature(strip_quotes(text), names)


def is_team(address: str | None) -> bool:
    return lead_rules.domain_of(address) in settings.OWN_DOMAINS


def pair(reply: dict[str, Any], parent: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    """The corpus entry for a team reply and the mail it answers, or None and the reason."""
    if parent is None:
        return None, 'kein Vorgänger'
    if FORWARD.match(reply.get('subject') or ''):
        return None, 'Weiterleitung'
    if is_team(parent.get('sender')):
        return None, 'intern'
    if AUTOMATIC.search(lead_rules.address_of(parent.get('sender'))):
        return None, 'Automat'
    question = own_text(parent)
    if not question:
        return None, 'leere Anfrage'
    answer = own_text(reply)
    if len(answer) < MIN_ANSWER:
        return None, 'leere Antwort'
    domain = lead_rules.domain_of(parent.get('sender'))
    return {
        'reply': reply['name'],
        'parent': parent['name'],
        'date': (reply.get('communication_date') or '')[:19],
        'author': lead_rules.address_of(reply.get('sender')),
        'author_name': reply.get('sender_full_name') or '',
        'lead': reply.get('reference_name') if reply.get('reference_doctype') == 'Lead' else None,
        'subject': (reply.get('subject') or '').strip(),
        'to': lead_rules.address_of(parent.get('sender')),
        'domain': domain,
        'question': question,
        'answer': answer,
    }, 'ok'


def fetch_team_mails(since: str) -> list[dict[str, Any]]:
    mails: list[dict[str, Any]] = []
    for domain in sorted(settings.OWN_DOMAINS):
        start = 0
        while True:
            rows = Api.api.get_list('Communication', fields=FIELDS,
                                    filters={'sent_or_received': 'Received', 'communication_type': 'Communication',
                                             'sender': ['like', '%@' + domain],
                                             'communication_date': ['>=', since]},
                                    order_by='communication_date asc', limit_start=start, limit_page_length=CHUNK * 5)
            mails.extend(rows)
            if len(rows) < CHUNK * 5:
                break
            start += len(rows)
    return [m for m in mails if not AUTOMATIC.search(lead_rules.address_of(m.get('sender')))]


def fetch_parents(names: list[str]) -> dict[str, dict[str, Any]]:
    parents: dict[str, dict[str, Any]] = {}
    for i in range(0, len(names), CHUNK):
        rows = Api.api.get_list('Communication', fields=FIELDS,
                                filters=[['name', 'in', names[i:i + CHUNK]]], limit_page_length=CHUNK)
        for row in rows:
            parents[row['name']] = row
    return parents


def build(since: str = DEFAULT_SINCE) -> tuple[list[dict[str, Any]], collections.Counter[str]]:
    """All corpus entries since the date, and the count of mails per outcome."""
    replies = fetch_team_mails(since)
    wanted = sorted({r['in_reply_to'] for r in replies if r.get('in_reply_to')})
    parents = fetch_parents(wanted)
    entries = []
    outcomes: collections.Counter[str] = collections.Counter()
    for reply in replies:
        entry, reason = pair(reply, parents.get(reply.get('in_reply_to') or ''))
        outcomes[reason] += 1
        if entry:
            entries.append(entry)
    return entries, outcomes


def save(entries: list[dict[str, Any]], path: str = DEFAULT_PATH) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load(path: str = DEFAULT_PATH) -> list[dict[str, Any]]:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def summary(entries: list[dict[str, Any]], outcomes: collections.Counter[str]) -> str:
    lines = ['{} Antworten des Teams geprüft, {} Paare übernommen'.format(sum(outcomes.values()), len(entries))]
    for reason, n in outcomes.most_common():
        if reason != 'ok':
            lines.append('  nicht übernommen, {}: {}'.format(reason, n))
    by_author = collections.Counter(e['author'] for e in entries)
    lines.append('nach Absender: ' + ', '.join('{} {}'.format(a, n) for a, n in by_author.most_common()))
    by_year = collections.Counter(e['date'][:4] for e in entries)
    lines.append('nach Jahr: ' + ', '.join('{} {}'.format(y, n) for y, n in sorted(by_year.items())))
    suppliers = sum(1 for e in entries if e.get('supplier'))
    if suppliers:
        lines.append('davon an Lieferanten: {}'.format(suppliers))
    return '\n'.join(lines)


def mark_suppliers(entries: list[dict[str, Any]]) -> None:
    """Name the supplier for replies whose addressee's domain is registered at a supplier."""
    rules = lead_rules.Rules.load()
    for e in entries:
        e['supplier'] = rules.supplier_domains.get(e['domain'])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--server', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--secret', required=True)
    parser.add_argument('--out', default=DEFAULT_PATH, help='corpus file (default %(default)s)')
    parser.add_argument('--since', default=DEFAULT_SINCE, help='first date of replies (default %(default)s)')
    args = parser.parse_args(argv)
    Api.api = FrappeClient(args.server, api_key=args.key, api_secret=args.secret)
    entries, outcomes = build(args.since)
    mark_suppliers(entries)
    save(entries, args.out)
    print(summary(entries, outcomes))
    print('gespeichert in', args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
