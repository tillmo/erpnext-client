"""Set up the sender rules for sorting leads (stage 2 of the lead automation, see lead_rules.py).

Installs on the server

- the custom doctype "Lead Absenderregel" (block/allow list: sender domains and addresses,
  maintained in the ERPNext UI),
- the field ``custom_email_domains`` on Supplier (one e-mail domain per line),

derives the initial rules from the decisions made so far (domains whose leads were always marked
"Do Not Contact" and never treated as a lead), extracts the suppliers' e-mail domains from their
invoice PDFs, and - with ``--backtest`` - reports how the rules would have decided the leads that
were decided manually before the given date.

Usage:
    python3 lead_rules_setup.py --server URL --key KEY --secret SECRET [--apply] [--backtest]
                                [--pdfs-per-supplier N] [--cutoff YYYY-MM-DD]

Without ``--apply`` nothing is changed on the server (dry run). The script is idempotent.
"""
from __future__ import annotations

import argparse
import collections
import os
import subprocess
import sys
import tempfile
from typing import Any, Callable

import lead_rules
import settings
from api import Api
from frappeclient import FrappeClient, FrappeException
from lead_rules import DNC, Rules, domain_of, domains_in_text, split_domains

RULE_DOCTYPE_DOC: dict[str, Any] = {
    'doctype': 'DocType',
    'name': settings.LEAD_RULE_DOCTYPE,
    'module': 'CRM',
    'custom': 1,
    'autoname': 'field:muster',
    'naming_rule': 'By fieldname',
    'title_field': 'muster',
    'track_changes': 1,
    'sort_field': 'modified',
    'sort_order': 'DESC',
    'fields': [
        {'fieldname': 'muster', 'label': 'Absender (Domain oder Adresse)', 'fieldtype': 'Data', 'reqd': 1,
         'unique': 1, 'in_list_view': 1, 'in_standard_filter': 1,
         'description': 'z. B. zcsend.net oder newsletter@example.com; eine Domain gilt samt Subdomains'},
        {'fieldname': 'wirkung', 'label': 'Wirkung', 'fieldtype': 'Select', 'options': 'Kein Lead\nLead',
         'default': 'Kein Lead', 'reqd': 1, 'in_list_view': 1, 'in_standard_filter': 1,
         'description': '"Kein Lead": der Client markiert Leads dieses Absenders automatisch als "nicht kontaktieren". '
                        '"Lead": nie automatisch markieren'},
        {'fieldname': 'quelle', 'label': 'Quelle', 'fieldtype': 'Select', 'options': 'manuell\nHistorie\nLieferant\nClient',
         'default': 'manuell', 'in_list_view': 1},
        {'fieldname': 'bemerkung', 'label': 'Bemerkung', 'fieldtype': 'Small Text'},
        {'fieldname': 'deaktiviert', 'label': 'Deaktiviert', 'fieldtype': 'Check', 'in_standard_filter': 1},
    ],
    'permissions': [
        {'role': 'System Manager', 'read': 1, 'write': 1, 'create': 1, 'delete': 1, 'report': 1, 'export': 1,
         'share': 1, 'print': 1, 'email': 1},
        {'role': 'Sales Manager', 'read': 1, 'write': 1, 'create': 1, 'delete': 1, 'report': 1, 'export': 1},
        {'role': 'Sales User', 'read': 1, 'write': 1, 'create': 1, 'report': 1},
    ],
}

SUPPLIER_FIELD: dict[str, Any] = {
    'doctype': 'Custom Field',
    'dt': 'Supplier',
    'fieldname': settings.SUPPLIER_DOMAINS_FIELD,
    'label': 'E-Mail-Domains',
    'fieldtype': 'Small Text',
    'insert_after': 'supplier_group',
    'description': 'Eine Domain je Zeile. E-Mails von diesen Domains behandelt der ERPNext-Client als Lieferantenpost, '
                   'nicht als Leads. Wird beim Einlesen von Rechnungen automatisch ergänzt.',
}

GOOD_STATUSES = ('Converted', 'Replied', 'Quotation', 'Opportunity', 'Lost Quotation', 'Lead', 'Interested')


def ensure_rule_doctype(api: FrappeClient, apply: bool) -> bool:
    if api.get_list('DocType', filters={'name': settings.LEAD_RULE_DOCTYPE}, fields=['name'], limit_page_length=1):
        print(f"DocType '{settings.LEAD_RULE_DOCTYPE}' vorhanden")
        return True
    if apply:
        api.insert(dict(RULE_DOCTYPE_DOC))
        print(f"DocType '{settings.LEAD_RULE_DOCTYPE}' angelegt")
    else:
        print(f"DocType '{settings.LEAD_RULE_DOCTYPE}' fehlt (wird mit --apply angelegt)")
    return apply


def ensure_supplier_field(api: FrappeClient, apply: bool) -> bool:
    if api.get_list('Custom Field', filters={'dt': 'Supplier', 'fieldname': settings.SUPPLIER_DOMAINS_FIELD},
                    fields=['name'], limit_page_length=1):
        print(f"Feld {settings.SUPPLIER_DOMAINS_FIELD} am Lieferanten vorhanden")
        return True
    if apply:
        api.insert(dict(SUPPLIER_FIELD))
        print(f"Feld {settings.SUPPLIER_DOMAINS_FIELD} am Lieferanten angelegt")
    else:
        print(f"Feld {settings.SUPPLIER_DOMAINS_FIELD} am Lieferanten fehlt (wird mit --apply angelegt)")
    return apply


def derive_domain_rules(leads: list[dict[str, Any]], min_dnc: int = 2) -> list[dict[str, Any]]:
    """Block rules from the decisions so far: domains with at least ``min_dnc`` leads marked
    "Do Not Contact" and no lead that was treated as a lead (other status, or assigned).
    Freemail and own domains are never turned into rules."""
    dnc: collections.Counter[str] = collections.Counter()
    good: collections.Counter[str] = collections.Counter()
    for lead in leads:
        domain = domain_of(lead.get('email_id'))
        if not domain or lead_rules.is_freemail(domain) or domain in settings.OWN_DOMAINS:
            continue
        status = lead.get('status')
        assigned = lead.get('_assign') not in (None, '', '[]')
        if status == DNC:
            dnc[domain] += 1
        elif status in GOOD_STATUSES or assigned:
            good[domain] += 1
    return [{'muster': d, 'wirkung': 'Kein Lead', 'quelle': 'Historie',
             'bemerkung': f"{n} Leads 'Do Not Contact', kein echter Lead (automatisch abgeleitet)"}
            for d, n in sorted(dnc.items()) if n >= min_dnc and good[d] == 0]


def apply_rules(api: FrappeClient, rules: list[dict[str, Any]], apply: bool) -> int:
    """Insert the rules that do not exist yet. Returns the number of new rules (or of rules to add)."""
    existing = {r['muster'].lower() for r in api.get_list(settings.LEAD_RULE_DOCTYPE, fields=['muster'],
                                                          limit_page_length=100000)}
    new = [r for r in rules if r['muster'].lower() not in existing]
    if not apply:
        print(f"{len(new)} neue Absenderregeln (von {len(rules)} abgeleiteten) würden angelegt (--apply)")
        return len(new)
    for r in new:
        api.insert(dict(r, doctype=settings.LEAD_RULE_DOCTYPE))
    print(f"{len(new)} Absenderregeln angelegt, {len(rules) - len(new)} gab es schon")
    return len(new)


def pdf_text(data: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(data)
    try:
        r = subprocess.run(['pdftotext', '-layout', '-enc', 'UTF-8', f.name, '-'], capture_output=True, timeout=120)
        return r.stdout.decode('utf-8', errors='replace')
    finally:
        os.unlink(f.name)


def extract_supplier_domains(api: FrappeClient, apply: bool, per_supplier: int = 2,
                             text_of: Callable[[bytes], str] = pdf_text) -> dict[str, list[str]]:
    """E-mail domains from the suppliers' invoice PDFs, written to the supplier field.
    Returns the new domains per supplier."""
    invoices = api.get_list('Purchase Invoice', filters={'supplier_invoice': ['is', 'set'], 'docstatus': ['!=', 2]},
                            fields=['name', 'supplier', 'supplier_invoice'], limit_page_length=100000)
    by_supplier: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for inv in invoices:
        by_supplier[inv['supplier']].append(inv)
    suppliers = {s['name']: s for s in api.get_list('Supplier', fields=['name', settings.SUPPLIER_DOMAINS_FIELD],
                                                    limit_page_length=100000)}
    result: dict[str, list[str]] = {}
    unreadable = 0
    for i, (supplier, invs) in enumerate(sorted(by_supplier.items()), 1):
        if supplier not in suppliers:
            continue
        found: set[str] = set()
        for inv in invs[-per_supplier:]:                       # the most recent invoices
            try:
                text = text_of(api.get_file(inv['supplier_invoice']))
            except (FrappeException, OSError, subprocess.SubprocessError) as e:
                print(f"{inv['name']}: PDF nicht lesbar ({str(e).splitlines()[-1][:80]})")
                unreadable += 1
                continue
            if not text.strip():
                unreadable += 1
                continue
            found |= domains_in_text(text)
        known = split_domains(suppliers[supplier].get(settings.SUPPLIER_DOMAINS_FIELD))
        new = sorted(found - known)
        if new:
            result[supplier] = new
            if apply:
                api.set_value('Supplier', supplier, settings.SUPPLIER_DOMAINS_FIELD, "\n".join(sorted(known | found)))
        if i % 50 == 0:
            print(f"{i}/{len(by_supplier)} Lieferanten ...")
    total = sum(len(v) for v in result.values())
    print(f"{len(by_supplier)} Lieferanten mit Rechnungs-PDF, {unreadable} PDFs ohne Text; "
          f"{total} neue Domains bei {len(result)} Lieferanten" + ("" if apply else " (Eintrag mit --apply)"))
    return result


def backtest(api: FrappeClient, rules: Rules, cutoff: str) -> dict[tuple[str, str], int]:
    """How would the rules decide the leads that were decided manually before ``cutoff``?
    Prints a table and the real leads that would have been marked automatically (must be none)."""
    leads = api.get_list('Lead', filters={'creation': ['<', cutoff]},
                         fields=['name', 'status', 'email_id', 'lead_name'], limit_page_length=100000)
    groups = {'Do Not Contact': [l for l in leads if l['status'] == DNC],
              'echte Leads': [l for l in leads if l['status'] in GOOD_STATUSES]}
    counts: dict[tuple[str, str], int] = collections.Counter()
    false_auto: list[tuple[str, str, str]] = []
    for group, ls in groups.items():
        names = [l['name'] for l in ls]
        comms: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        for i in range(0, len(names), 15):
            rows = api.get_list('Communication', filters={'reference_doctype': 'Lead', 'reference_name': ['in', names[i:i + 15]]},
                                fields=['reference_name', 'sender', 'subject', 'content'], limit_page_length=100000)
            for r in rows:
                comms[r['reference_name']].append(r)
        for l in ls:
            d = lead_rules.classify(l['email_id'], comms.get(l['name'], []), rules)
            kind = 'automatisch' if d.auto else ('Vorschlag' if d.choice else 'Frage')
            counts[(group, kind)] += 1
            if group == 'echte Leads' and d.auto:
                false_auto.append((l['name'], domain_of(l['email_id']), d.reason))
    print(f"\nRückrechnung (Leads vor {cutoff}):")
    print(f"{'':16} {'automatisch':>12} {'Vorschlag':>10} {'Frage':>8} {'gesamt':>8}")
    for group, ls in groups.items():
        print(f"{group:16} {counts[(group, 'automatisch')]:12} {counts[(group, 'Vorschlag')]:10} "
              f"{counts[(group, 'Frage')]:8} {len(ls):8}")
    if false_auto:
        print("Echte Leads, die automatisch markiert worden wären:")
        for name, domain, reason in false_auto:
            print(f"  {name}  {domain}  {reason}")
    else:
        print("Kein echter Lead wäre automatisch markiert worden.")
    return dict(counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument('--server', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--secret', required=True)
    parser.add_argument('--apply', action='store_true', help='tatsächlich ändern (sonst nur berichten)')
    parser.add_argument('--backtest', action='store_true', help='Regeln gegen die bisherigen Entscheidungen rechnen')
    parser.add_argument('--cutoff', default='2025-11-03', help='Leads vor diesem Datum gelten als von Hand entschieden')
    parser.add_argument('--pdfs-per-supplier', type=int, default=2, help='Rechnungs-PDFs je Lieferant auswerten (0: keine)')
    args = parser.parse_args(argv)
    api = FrappeClient(args.server, api_key=args.key, api_secret=args.secret)
    Api.api = api
    doctype_ok = ensure_rule_doctype(api, args.apply)
    field_ok = ensure_supplier_field(api, args.apply)
    leads = api.get_list('Lead', fields=['name', 'status', 'email_id', '_assign'], limit_page_length=100000)
    derived = derive_domain_rules(leads)
    print(f"{len(derived)} Sperrregeln aus {len(leads)} Leads abgeleitet")
    if doctype_ok:
        apply_rules(api, derived, args.apply)
    if field_ok and args.pdfs_per_supplier:
        extract_supplier_domains(api, args.apply, args.pdfs_per_supplier)
    if args.backtest:
        rules = Rules.load() if doctype_ok and field_ok else Rules()
        if not rules.loaded:
            for r in derived:
                rules.add_pattern(r['muster'], r['wirkung'])
            print("(Rückrechnung mit den abgeleiteten Regeln, ohne Lieferanten-Domains)")
        backtest(api, rules, args.cutoff)
    return 0


if __name__ == '__main__':
    sys.exit(main())
