"""Server-side protection for leads marked "Do Not Contact" (stage 1 of the lead automation).

E-mails to the central inbox become leads. Frappe reopens a lead on every received e-mail
(``update_parent_document_on_communication`` sets the status back to "Open" with ``db_set``,
without a version entry), so leads marked "Do Not Contact" had to be marked again and again.

This module installs on the server

- a Custom Field ``custom_nicht_kontaktieren`` (Check) on Lead, set by the client when a lead
  is marked "Do Not Contact" (``lead.mark_not_contact``),
- a Server Script on Communication (After Save) that restores "Do Not Contact" for flagged leads,

and flags the leads that have already been marked manually (backfill): leads currently in
"Do Not Contact", and open leads whose last manual status change was to "Do Not Contact"
(they were reopened by e-mails, not by a person) - these are closed again as well.

Usage:
    python3 lead_dnc_setup.py --server URL --key KEY --secret SECRET [--apply] [--limit N]

Without ``--apply`` nothing is changed on the server (dry run). The script is idempotent.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from frappeclient import FrappeClient, FrappeException
from settings import LEAD_DNC_FIELD

DNC = 'Do Not Contact'

CUSTOM_FIELD: dict[str, Any] = {
    'doctype': 'Custom Field',
    'dt': 'Lead',
    'fieldname': LEAD_DNC_FIELD,
    'label': 'Nicht kontaktieren',
    'fieldtype': 'Check',
    'insert_after': 'status',
    'default': '0',
    'in_standard_filter': 1,
    'description': 'Vom ERPNext-Client gesetzt: der Lead bleibt auch bei neuen E-Mails auf "Nicht kontaktieren"',
}

SERVER_SCRIPT_NAME = 'Lead nicht kontaktieren halten'

# Runs in Frappe's restricted Python: `doc` is the Communication that was saved.
# "After Save" runs after Communication.on_update, which has just set the lead to "Open".
SERVER_SCRIPT = f'''# Installed by the ERPNext client (lead_dnc_setup.py) - edit it there, not here.
# Frappe reopens a lead on every received e-mail; keep flagged leads on "Do Not Contact".
if (doc.reference_doctype == "Lead" and doc.reference_name
        and doc.sent_or_received == "Received" and doc.communication_type == "Communication"):
    lead = frappe.db.get_value("Lead", doc.reference_name, ["status", "{LEAD_DNC_FIELD}"], as_dict=True)
    if lead and lead.{LEAD_DNC_FIELD} and lead.status != "Do Not Contact":
        frappe.db.set_value("Lead", doc.reference_name, "status", "Do Not Contact")
'''

SERVER_SCRIPT_DOC: dict[str, Any] = {
    'doctype': 'Server Script',
    'name': SERVER_SCRIPT_NAME,
    'script_type': 'DocType Event',
    'reference_doctype': 'Communication',
    'doctype_event': 'After Save',
    'disabled': 0,
    'script': SERVER_SCRIPT,
}


def ensure_custom_field(api: FrappeClient, apply: bool) -> bool:
    """Create the check field on Lead if missing. Returns True if it exists (or would be created)."""
    existing = api.get_list('Custom Field', filters={'dt': 'Lead', 'fieldname': LEAD_DNC_FIELD},
                            fields=['name'], limit_page_length=1)
    if existing:
        print(f"Feld {LEAD_DNC_FIELD} am Lead vorhanden")
        return True
    if apply:
        api.insert(dict(CUSTOM_FIELD))
        print(f"Feld {LEAD_DNC_FIELD} am Lead angelegt")
    else:
        print(f"Feld {LEAD_DNC_FIELD} am Lead fehlt (wird mit --apply angelegt)")
    return apply


def ensure_server_script(api: FrappeClient, apply: bool) -> bool:
    """Create or update the server script. Returns True if it is installed and current."""
    existing = api.get_list('Server Script', filters={'name': SERVER_SCRIPT_NAME},
                            fields=['name', 'script', 'disabled', 'reference_doctype', 'doctype_event'],
                            limit_page_length=1)
    wanted = {k: SERVER_SCRIPT_DOC[k] for k in ('script', 'disabled', 'reference_doctype', 'doctype_event')}
    if existing and all(existing[0].get(k) == v for k, v in wanted.items()):
        print(f"Server Script '{SERVER_SCRIPT_NAME}' aktuell")
        return True
    if not apply:
        print(f"Server Script '{SERVER_SCRIPT_NAME}' {'veraltet' if existing else 'fehlt'} (wird mit --apply "
              f"{'aktualisiert' if existing else 'angelegt'})")
        return False
    if existing:
        doc = api.get_doc('Server Script', SERVER_SCRIPT_NAME)
        doc.update(wanted)
        api.update(doc)
        print(f"Server Script '{SERVER_SCRIPT_NAME}' aktualisiert")
    else:
        api.insert(dict(SERVER_SCRIPT_DOC))
        print(f"Server Script '{SERVER_SCRIPT_NAME}' angelegt")
    return True


def status_changes(versions: list[dict[str, Any]]) -> dict[str, list[tuple[str, str, str]]]:
    """Per lead the status changes (creation, old, new) from Version documents, in chronological order."""
    changes: dict[str, list[tuple[str, str, str]]] = {}
    for v in versions:
        try:
            changed = json.loads(v.get('data') or '{}').get('changed') or []
        except (TypeError, ValueError):
            continue
        for c in changed:
            if c and c[0] == 'status':
                changes.setdefault(v['docname'], []).append((v['creation'], c[1], c[2]))
    for lst in changes.values():
        lst.sort()
    return changes


def classify(leads: list[dict[str, Any]], versions: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Decide which leads get the flag.

    Returns (flag, flag_and_close): leads in "Do Not Contact" only get the flag; open leads whose
    last status change involving "Do Not Contact" was *to* "Do Not Contact" were reopened by
    e-mails and are closed again. Leads a person reopened (last change *from* "Do Not Contact"),
    leads in other statuses and leads already flagged are left alone.
    """
    changes = status_changes(versions)
    flag: list[str] = []
    close: list[str] = []
    for lead in leads:
        if lead.get(LEAD_DNC_FIELD):
            continue
        if lead['status'] == DNC:
            flag.append(lead['name'])
        elif lead['status'] == 'Open':
            dnc_changes = [c for c in changes.get(lead['name'], []) if DNC in (c[1], c[2])]
            if dnc_changes and dnc_changes[-1][2] == DNC:
                close.append(lead['name'])
    return flag, close


def backfill(api: FrappeClient, apply: bool, limit: int = 0, field_exists: bool = True) -> tuple[int, int]:
    """Flag the leads marked manually so far. Returns (flagged, errors).

    ``field_exists=False`` (dry run before the field is created) does not query the flag."""
    fields = ['name', 'status'] + ([LEAD_DNC_FIELD] if field_exists else [])
    leads = api.get_list('Lead', fields=fields, limit_page_length=100000)
    versions = api.get_list('Version', filters={'ref_doctype': 'Lead'}, fields=['docname', 'data', 'creation'],
                            limit_page_length=100000)
    flag, close = classify(leads, versions)
    print(f"{len(leads)} Leads, davon {sum(1 for l in leads if l.get(LEAD_DNC_FIELD))} schon markiert; "
          f"zu markieren: {len(flag)} in 'Do Not Contact', {len(close)} wieder geöffnete (werden wieder geschlossen)")
    todo = [(n, False) for n in flag] + [(n, True) for n in close]
    if limit:
        todo = todo[:limit]
    if not apply:
        print(f"{len(todo)} Leads würden markiert (--apply)")
        return 0, 0
    done = errors = skipped = 0
    for i, (name, set_status) in enumerate(todo, 1):
        try:
            doc = api.get_doc('Lead', name)
            doc[LEAD_DNC_FIELD] = 1
            if set_status:
                doc['status'] = DNC
            saved = api.update(doc)
            # ERPNext recomputes the status on save: a lead linked to a customer or an
            # opportunity becomes "Converted"/"Opportunity" - such a lead must not be kept closed
            if saved.get('status') != DNC:
                doc = api.get_doc('Lead', name)
                doc[LEAD_DNC_FIELD] = 0
                api.update(doc)
                skipped += 1
                print(f"{name} hat nach dem Speichern Status '{saved.get('status')}', nicht markiert")
            else:
                done += 1
        except FrappeException as e:
            errors += 1
            print(f"Fehler bei {name}: {str(e).splitlines()[-1][:160]}")
        if i % 100 == 0:
            print(f"{i}/{len(todo)} ...")
    print(f"{done} Leads markiert, {skipped} wegen geändertem Status ausgelassen, {errors} Fehler")
    return done, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument('--server', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--secret', required=True)
    parser.add_argument('--apply', action='store_true', help='tatsächlich ändern (sonst nur berichten)')
    parser.add_argument('--limit', type=int, default=0, help='höchstens so viele Leads markieren (Test)')
    args = parser.parse_args(argv)
    api = FrappeClient(args.server, api_key=args.key, api_secret=args.secret)
    field_ok = ensure_custom_field(api, args.apply)
    ensure_server_script(api, args.apply)
    if not field_ok and args.apply:
        return 1
    _, errors = backfill(api, args.apply, args.limit, field_exists=field_ok)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
