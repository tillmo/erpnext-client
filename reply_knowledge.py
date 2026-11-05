"""Draft the knowledge file for e-mail replies from the team's own answers (reply corpus).

Claude reads a sample of the pairs "incoming mail -> our reply" from ``reply_corpus.py`` and
writes a Markdown file: the team's tone and form (per author), the facts and standard details
that recur in the replies (addresses, links, procedures, prices with the date they stem from),
model answers per kind of request, what the team usually asks back, and what looks outdated or
contradictory. The team reads the draft, corrects it and keeps it as the knowledge base from which
later replies are drafted. It states business facts, not customer data: the prompt forbids
customer names and personal details, and the sample leaves out the addressees.

The file belongs in the private mytools repository next to the corpus, never in the public one.

Usage:
    python3 reply_knowledge.py [--corpus FILE] [--out FILE] [--pairs 250] [--since 2025-01-01]
                               [--seed 1] [--claude-key KEY] [--claude-model MODEL]
The key comes from the client settings ("Einstellungen - Claude") or ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import argparse
import collections
import os
import random
import re
import sys
from typing import Any

import claude_parser
import reply_corpus

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mytools', 'reply-knowledge.md')
MIN_ANSWER, MAX_ANSWER = 120, 2500        # informative replies: not "passt, bis dann", not a treatise
MAX_QUESTION = 2000                       # the incoming mail is cut here (its gist comes first)
SUPPLIER_SHARE = 0.15                     # share of supplier pairs in the sample
AUTHOR_CAP = 0.7                          # no author takes more than this share of the customer pairs

SYSTEM = """Du analysierst E-Mail-Antworten des Teams von Bremer SolidarStrom (Solidarische Ökonomie Bremen e.V.), \
einem gemeinnützigen Verein in Bremen, der Balkonkraftwerke verkauft, Solaranlagen im Selbstbau mit Kund*innen \
baut, soziale Balkonkraftwerke (SBKW) für Menschen mit geringem Einkommen vermittelt und Material liefert. \
Aus einer Stichprobe von Paaren "eingehende Mail -> Antwort des Teams" schreibst du eine Wissensdatei in Markdown, \
mit der später Antwortentwürfe im Stil und mit dem Wissen des Teams erzeugt werden.

Regeln:
- Schreibe auf Deutsch. Keine Namen, Adressen, Telefonnummern oder E-Mail-Adressen von Kund*innen oder \
Lieferant*innen-Ansprechpersonen; Vornamen der Teammitglieder sind in Ordnung. Firmennamen von Lieferanten sind in Ordnung.
- Erfinde nichts. Jede Angabe muss aus den Antworten stammen. Wo Antworten einander widersprechen oder sich \
über die Zeit ändern (Preise, Termine, Abläufe), nenne beide Fassungen mit dem Datum der Mail.
- Fakten mit Jahr versehen, z. B. "(Stand 2026-03)". Preise immer mit Datum.
- Musterantworten in den Worten des Teams, nicht in Behördendeutsch. Zeige, wie das Team wirklich schreibt. \
Die Anrede in Musterantworten lautet immer "Hallo [Vorname]" bzw. "Sehr geehrte*r [Name]", nie ein echter Name.

Gliederung der Wissensdatei:
1. Tonfall und Form: je Autor*in (Vorname) Anrede (du/Sie, wann was), Begrüßung, Grußformel, typische Länge, \
Eigenheiten, wie mit Verzögerungen oder Absagen umgegangen wird.
2. Fakten und Standardangaben: Orte (Lager, Büro, Abholung), Links, Zeiten, Abläufe (Bestellung, Abholung, \
Rechnung, Zahlung, Anmeldung beim Netzbetreiber, Marktstammdatenregister), Preise und Konditionen, Förderungen, \
Voraussetzungen (Vermieterzustimmung, Außensteckdose, Fotos), technische Standardaussagen (Module, Wechselrichter, \
Speicher, Halterungen, Kabellängen), Kooperationen.
3. Standardantworten je Anliegen: für jedes wiederkehrende Anliegen (z. B. Anfrage Balkonkraftwerk, Anfrage \
Solaranlage, Terminabsprache, Rechnung und Zahlung, SBKW/soziale Balkonkraftwerke, Speicher, Förderung, Reklamation \
oder Defekt, Lieferung und Abholung, Vortrag oder Workshop, Lieferantenbestellung, Lieferantenreklamation) den \
typischen Aufbau der Antwort und eine vollständige Musterantwort.
4. Was das Team üblicherweise zurückfragt oder anfordert.
5. Unklar, widersprüchlich oder vermutlich veraltet: Angaben, die sich geändert haben oder die du nicht sicher \
einordnen kannst, als Prüfliste für das Team."""


def pair_text(i: int, e: dict[str, Any]) -> str:
    kind = 'Lieferant {}'.format(e['supplier']) if e.get('supplier') else 'Kund*in'
    author = (e.get('author_name') or e.get('author') or '').split('@')[0].split()[0] if e.get('author_name') or e.get('author') else '?'
    question = e['question'][:MAX_QUESTION]
    return ('### Paar {} ({}, Antwort von {}, {})\nBetreff: {}\n\nEingehende Mail:\n{}\n\nAntwort des Teams:\n{}\n'
            .format(i, kind, author, e['date'][:10], e.get('subject', ''), question, e['answer']))


def informative(e: dict[str, Any]) -> bool:
    return MIN_ANSWER <= len(e.get('answer', '')) <= MAX_ANSWER and bool(e.get('question'))


def sample(entries: list[dict[str, Any]], n: int, since: str, seed: int) -> list[dict[str, Any]]:
    """A stratified random sample: a share of supplier pairs, the customer pairs spread over the
    authors with no one dominating, recent and informative pairs only."""
    rnd = random.Random(seed)
    pool = [e for e in entries if e['date'] >= since and informative(e)]
    suppliers = [e for e in pool if e.get('supplier')]
    customers = [e for e in pool if not e.get('supplier')]
    n_sup = min(len(suppliers), round(n * SUPPLIER_SHARE))
    n_cust = min(len(customers), n - n_sup)
    by_author: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for e in customers:
        by_author[e['author']].append(e)
    for lst in by_author.values():
        rnd.shuffle(lst)
    chosen: list[dict[str, Any]] = []
    cap = max(1, round(n_cust * AUTHOR_CAP))
    taken = collections.Counter()
    authors = sorted(by_author, key=lambda a: -len(by_author[a]))
    while len(chosen) < n_cust:
        progressed = False
        for a in authors:                      # round robin, each author up to the cap
            if by_author[a] and taken[a] < cap and len(chosen) < n_cust:
                chosen.append(by_author[a].pop())
                taken[a] += 1
                progressed = True
        if not progressed:
            break
    chosen += rnd.sample(suppliers, n_sup)
    chosen.sort(key=lambda e: (bool(e.get('supplier')), e['date']))
    return chosen


def prompt(pairs: list[dict[str, Any]]) -> str:
    head = ('Hier sind {} Paare aus eingehender Mail und Antwort des Teams ({} bis {}). '
            'Schreibe daraus die Wissensdatei nach der vorgegebenen Gliederung.\n\n'
            .format(len(pairs), pairs[0]['date'][:10] if pairs else '', max(e['date'] for e in pairs)[:10] if pairs else ''))
    return head + '\n'.join(pair_text(i + 1, e) for i, e in enumerate(pairs))


GREETING_LINE = re.compile(r'^(\s*>?\s*(?:Hallo|Hi|Hey|Moin|Liebe[rs]?|Guten Tag|Sehr geehrte[rs]?)'
                           r'(?:\s+(?:Herr|Frau|Familie|Dr\.|Prof\.))?\s+)'
                           r'([A-ZÄÖÜ][\w-]+(?:(?:\s+|\s+und\s+|\s*,\s*(?:hi|hallo)\s+)[A-ZÄÖÜ][\w-]+)*)(\s*[,!]?\s*)$', re.M)
CONTINUE = 'Fahre genau an der Stelle fort, an der der Text abbricht: ohne Wiederholung, ohne Einleitung, bis die Gliederung vollständig ist.'


def anonymize_greetings(text: str) -> str:
    """Model answers address the reader as "[Vorname]" - whatever name Claude copied."""
    return GREETING_LINE.sub(lambda m: m.group(1) + '[Vorname]' + m.group(3), text)


def draft(pairs: list[dict[str, Any]], client: Any = None, previous: str = '', rounds: int = 3) -> str:
    """Claude's draft of the knowledge file for the given pairs. A draft that hits the output
    limit is continued in further rounds; ``previous`` resumes an earlier, cut-off draft."""
    client = client or claude_parser._client()
    messages: list[dict[str, Any]] = [{'role': 'user', 'content': prompt(pairs)}]
    parts = [previous] if previous else []
    if previous:
        messages += [{'role': 'assistant', 'content': previous.rstrip()}, {'role': 'user', 'content': CONTINUE}]
    for _ in range(rounds):
        with client.messages.stream(model=claude_parser.model(), max_tokens=24000, system=SYSTEM,
                                    messages=messages) as stream:
            response = stream.get_final_message()
        usage = getattr(response, 'usage', None)
        if usage is not None:
            print('Claude ({}): {} Eingabe-, {} Ausgabe-Tokens, Ende: {}'.format(
                response.model, usage.input_tokens, usage.output_tokens, response.stop_reason))
        text = ''.join(b.text for b in response.content if b.type == 'text')
        parts.append(text)
        if response.stop_reason != 'max_tokens':
            break
        messages += [{'role': 'assistant', 'content': text.rstrip()}, {'role': 'user', 'content': CONTINUE}]
    return anonymize_greetings('\n'.join(p.rstrip('\n') for p in parts) + '\n')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--corpus', default=reply_corpus.DEFAULT_PATH)
    parser.add_argument('--out', default=DEFAULT_OUT)
    parser.add_argument('--pairs', type=int, default=250)
    parser.add_argument('--since', default='2025-01-01')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--claude-key', dest='claude_key')
    parser.add_argument('--claude-model', dest='claude_model')
    parser.add_argument('--dry-run', action='store_true', help='print the sample statistics and the prompt size only')
    parser.add_argument('--resume', action='store_true', help='continue the cut-off draft in --out (same sample: same --seed)')
    args = parser.parse_args(argv)
    if args.claude_key:
        os.environ['ANTHROPIC_API_KEY'] = args.claude_key
    if args.claude_model:
        claude_parser.model = lambda: args.claude_model      # type: ignore[assignment]
    entries = reply_corpus.load(args.corpus)
    if not entries:
        print('Korpus {} fehlt oder ist leer; zuerst reply_corpus.py ausführen'.format(args.corpus))
        return 1
    pairs = sample(entries, args.pairs, args.since, args.seed)
    text = prompt(pairs)
    by_author = collections.Counter((e.get('author_name') or e['author']) for e in pairs)
    print('{} Paare ausgewählt ({} an Lieferanten), {} Zeichen; nach Autor*in: {}'.format(
        len(pairs), sum(1 for e in pairs if e.get('supplier')), len(text),
        ', '.join('{} {}'.format(a, n) for a, n in by_author.most_common())))
    if args.dry_run:
        return 0
    if not claude_parser.configured():
        print('Kein Claude-Schlüssel: --claude-key, Einstellungen - Claude oder ANTHROPIC_API_KEY')
        return 1
    previous = ''
    if args.resume:
        with open(args.out, encoding='utf-8') as f:
            previous = f.read()
    result = draft(pairs, previous=previous)
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(result if result.endswith('\n') else result + '\n')
    print('Entwurf gespeichert in', args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
