"""Rules for sorting leads created from incoming e-mails (stage 2 of the lead automation).

Decides for a lead whether it can be marked "Do Not Contact" without asking, whether a
suggestion is shown in the dialog, or whether a person has to decide without help:

1. allow rules (doctype "Lead Absenderregel", effect "Lead") always lead to a question,
2. block rules (effect "Kein Lead") for the sender address or its domain decide automatically,
3. a supplier domain (field ``custom_email_domains`` on Supplier) decides automatically when the
   subject looks transactional (invoice, order, delivery ...), otherwise it is a suggestion,
4. newsletter wording in the mail decides automatically when the sender is no private (freemail)
   address and looks like a bulk sender (noreply, newsletter, ...) or the lead already collected
   several mails, otherwise it is a suggestion,
5. subject words typical of real requests and private (freemail) addresses lead to a question.

``classify`` is a pure function over the data passed in; ``Rules.load`` reads the rules from
ERPNext. ``lead_rules_setup.py`` installs the doctype and the supplier field and derives the
initial rules from the decisions made so far.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

from api import Api, LIMIT
from frappeclient import FrappeException
import settings

KEIN_LEAD = 'kein Lead'
DNC = 'Do Not Contact'

EMAIL_RE = re.compile(r'[\w.+-]+@([\w-]+(?:\.[\w-]+)+)')
_NEWSLETTER_RE = re.compile(settings.LEAD_NEWSLETTER_PATTERN, re.IGNORECASE)
_SECOND_LEVEL = {'co', 'com', 'org', 'net', 'ac', 'gov'}


def registrable_domain(host: str) -> str:
    """service.solarwatt.com -> solarwatt.com, mail.example.co.uk -> example.co.uk"""
    parts = host.lower().strip('.').split('.')
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL and len(parts[-1]) == 2:
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:]) if len(parts) >= 2 else parts[0]


def address_of(text: str | None) -> str:
    """First e-mail address in a string (lower case), '' if none ("Name <a@b.de>" -> a@b.de)."""
    m = EMAIL_RE.search(text or '')
    return m.group(0).lower() if m else ''


def domain_of(address: str | None) -> str:
    m = EMAIL_RE.search(address or '')
    return registrable_domain(m.group(1)) if m else ''


def is_freemail(domain: str) -> bool:
    return domain in settings.FREEMAIL_DOMAINS


def domains_in_text(text: str) -> set[str]:
    """Registrable domains of all e-mail addresses in a text, without freemail and own domains."""
    text = unicodedata.normalize('NFKC', text or '')        # PDF ligatures such as "oﬀ" -> "off"
    return {d for d in (registrable_domain(h) for h in EMAIL_RE.findall(text))
            if d and not is_freemail(d) and d not in settings.OWN_DOMAINS}


def split_domains(text: str | None) -> set[str]:
    """Domains from a Small Text field: one per line, commas and blanks tolerated."""
    return {registrable_domain(d) for d in re.split(r'[\s,;]+', text or '') if '.' in d}


def _first_word(text: str, words: Iterable[str]) -> str | None:
    for w in words:
        if w in text:
            return w
    return None


def _is_bulk_sender(address: str) -> bool:
    local = address.split('@')[0]
    tokens = set(re.split(r'[^a-z0-9]+', local))
    return bool(tokens & settings.LEAD_BULK_SENDERS) or local.replace('-', '').replace('_', '').startswith('noreply')


@dataclass
class Decision:
    auto: bool                  # decide without asking
    choice: str | None          # 'kein Lead' when automatic or suggested; None: no suggestion
    reason: str                 # shown to the user and stored as comment


@dataclass
class Rules:
    block_addresses: set[str] = field(default_factory=set)
    block_domains: set[str] = field(default_factory=set)
    allow_addresses: set[str] = field(default_factory=set)
    allow_domains: set[str] = field(default_factory=set)
    supplier_domains: dict[str, str] = field(default_factory=dict)      # domain -> supplier
    loaded: bool = False

    def add_pattern(self, pattern: str, effect: str) -> None:
        pattern = (pattern or '').strip().lower().lstrip('@')
        if not pattern:
            return
        block = effect != 'Lead'
        if '@' in pattern:
            (self.block_addresses if block else self.allow_addresses).add(pattern)
        else:
            (self.block_domains if block else self.allow_domains).add(registrable_domain(pattern))

    @classmethod
    def load(cls) -> Rules:
        """Read block/allow rules and supplier domains from ERPNext; missing objects give empty rules."""
        rules = cls()
        try:
            rows = Api.api.get_list(settings.LEAD_RULE_DOCTYPE, filters={'deaktiviert': 0},
                                    fields=['muster', 'wirkung'], limit_page_length=LIMIT)
        except FrappeException:
            print(f"Hinweis: DocType '{settings.LEAD_RULE_DOCTYPE}' fehlt (lead_rules_setup.py) - keine Absenderregeln")
            rows = []
        for r in rows:
            rules.add_pattern(r['muster'], r['wirkung'])
        try:
            sups = Api.api.get_list('Supplier', filters={settings.SUPPLIER_DOMAINS_FIELD: ['is', 'set']},
                                    fields=['name', settings.SUPPLIER_DOMAINS_FIELD], limit_page_length=LIMIT)
        except FrappeException:
            print(f"Hinweis: Feld {settings.SUPPLIER_DOMAINS_FIELD} am Lieferanten fehlt (lead_rules_setup.py)")
            sups = []
        for s in sups:
            for d in split_domains(s.get(settings.SUPPLIER_DOMAINS_FIELD)):
                rules.supplier_domains.setdefault(d, s['name'])
        rules.loaded = True
        return rules


def classify(sender: str | None, comms: list[dict[str, Any]], rules: Rules) -> Decision:
    """Decide for a lead from its sender address and its communications (subject, content)."""
    address = address_of(sender)
    if not address:
        for c in comms:
            address = address_of(c.get('sender'))
            if address:
                break
    domain = domain_of(address)
    subjects = " ".join(c.get('subject') or '' for c in comms).lower()
    if address in rules.allow_addresses:
        return Decision(False, None, f"Freigabe für {address}")
    if domain in rules.allow_domains:
        return Decision(False, None, f"Freigabe für {domain}")
    if address in rules.block_addresses:
        return Decision(True, KEIN_LEAD, f"Sperrliste: {address}")
    if domain in rules.block_domains:
        return Decision(True, KEIN_LEAD, f"Sperrliste: {domain}")
    positive = _first_word(subjects, settings.LEAD_POSITIVE_WORDS)
    supplier = rules.supplier_domains.get(domain)
    if supplier:
        transactional = _first_word(subjects, settings.LEAD_TRANSACTIONAL_WORDS)
        if transactional and not positive:
            return Decision(True, KEIN_LEAD, f"Lieferant {supplier}, Betreff '{transactional}'")
        return Decision(False, KEIN_LEAD, f"Absender-Domain gehört zu Lieferant {supplier}")
    newsletter = any(_NEWSLETTER_RE.search(c.get('content') or '') for c in comms)
    if newsletter:
        if (_is_bulk_sender(address) or len(comms) >= 3) and not positive and not is_freemail(domain):
            return Decision(True, KEIN_LEAD, f"Newsletter-Muster, Absender {address}")
        return Decision(False, KEIN_LEAD, "Newsletter-Muster in der Mail")
    if positive:
        return Decision(False, None, f"Betreff enthält '{positive}'")
    if is_freemail(domain):
        return Decision(False, None, "Privatadresse")
    return Decision(False, None, "")


def note_supplier_domains(supplier: str | None, text: str) -> list[str]:
    """Record the e-mail domains found in an invoice text at the supplier. Returns the new domains."""
    if not supplier or supplier == '???':
        return []
    found = domains_in_text(text)
    if not found:
        return []
    try:
        rows = Api.api.get_list('Supplier', filters={'name': supplier},
                                fields=['name', settings.SUPPLIER_DOMAINS_FIELD], limit_page_length=1)
        if not rows:
            return []
        known = split_domains(rows[0].get(settings.SUPPLIER_DOMAINS_FIELD))
        new = sorted(found - known)
        if new:
            Api.api.set_value('Supplier', supplier, settings.SUPPLIER_DOMAINS_FIELD, "\n".join(sorted(known | found)))
            print(f"E-Mail-Domain(s) {', '.join(new)} bei Lieferant {supplier} vermerkt")
        return new
    except FrappeException as e:
        print(f"Hinweis: E-Mail-Domains konnten nicht am Lieferanten vermerkt werden: {str(e).splitlines()[-1][:120]}")
        return []
