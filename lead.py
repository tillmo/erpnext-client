from __future__ import annotations

from typing import Any
from api import Api, LIMIT
from settings import LEAD_OWNERS, LEAD_DNC_FIELD
import lead_rules
import lead_contact
import utils
import easygui
import json
import table

def is_change_into_not_contact(v: dict[str, Any]) -> bool:
    if 'data' in v:
        j = json.loads(v['data'])
        if j.get('changed') == [['status', 'Open', 'Do Not Contact']]:
            return True
    return False

def mark_not_contact(name: str) -> None:
    """Set a lead to "Do Not Contact" and flag it, so that the server script keeps it there
    when further e-mails arrive (see lead_dnc_setup.py)."""
    doc = Api.api.get_doc("Lead", name)
    doc['status'] = 'Do Not Contact'
    doc[LEAD_DNC_FIELD] = 1
    Api.api.update(doc)

def add_comment(name: str, text: str) -> None:
    """Leave a comment on the lead (why it was marked automatically)."""
    try:
        Api.api.insert({'doctype': 'Comment', 'comment_type': 'Comment', 'reference_doctype': 'Lead',
                        'reference_name': name, 'content': text})
    except Exception as e:
        print(f"Hinweis: Kommentar an {name} nicht möglich: {str(e).splitlines()[-1][:120]}")

def format(lead: dict[str, Any]) -> dict[str, Any]:
    lead['creation'] = lead['creation'].split()[0]
    return lead

def show_open_leads() -> None:
    leads = Api.api.get_list("Lead",
                             filters={'status':'Open'},
                             fields=['name','status','lead_name', 'creation'],
                             order_by='creation desc',
                             limit_page_length=LIMIT)
    
    print()
    leads = [format(lead) for lead in leads]
    keys = ['name','status','lead_name', 'creation']
    headings = ['name','status','lead_name', 'creation']
    title = f'offene Leads: {len(leads)}'
    tbl = table.Table(leads,keys,headings,title,display_row_numbers=True)
    tbl.display()


def process_open_leads() -> None:
    cleanup_leads()
    lead_owners: dict[str, str] = {}
    for lo in LEAD_OWNERS:
        lo1 = Api.api.get_list("User",filters={'first_name':lo})
        if lo1:
            lead_owners[lo] = lo1[0]['name']
    lead_owner_list = list(lead_owners.keys())        
    choices = lead_owner_list + ['kein Lead','überspringen']
    leads = Api.api.get_list("Lead",
                             filters={'status':'Open',
                                      '_assign':['like',None]},
                             fields=['name','status','lead_name'],
                             order_by='creation desc',
                             limit_page_length=LIMIT)
    rules = lead_rules.Rules.load()
    n_auto = n_manual = n_skipped = 0
    for lead1 in leads:
        res = Api.api.load_doc("Lead",lead1['name'])
        doc = res['docs'][0]
        versions = res['docinfo']['versions']
        comms = res['docinfo']['communications']
        choice: str | None = None
        comment: str | None = None
        # flagged, or marked "Do Not Contact" before and reopened by a new e-mail
        if doc.get(LEAD_DNC_FIELD) or any(is_change_into_not_contact(v) for v in versions):
            choice = 'kein Lead'
            print(f'Markiere Lead {lead1["name"]} {lead1["lead_name"]} wieder als "nicht kontaktieren"')
        else:
            decision = lead_rules.classify(doc.get('email_id'), comms, rules)
            if decision.auto:
                choice = decision.choice
                comment = f'Automatisch als "nicht kontaktieren" markiert: {decision.reason}'
                print(f'Markiere Lead {lead1["name"]} {lead1["lead_name"]} als "nicht kontaktieren": {decision.reason}')
            else:
                title = f"Bitte Lead Owner für {lead1['name']} {lead1['lead_name']} wählen"
                texts = [utils.html_to_text(comm['content']) for comm in comms]
                text = lead_contact.excerpt("\n--------------------\n".join(texts))
                hint = ""
                if decision.reason:
                    hint = f"Vorschlag: {decision.choice or 'Lead'} ({decision.reason})\n\n"
                msg = f"{doc['name']}   {doc['lead_name']}\n{hint}\n{text}"
                preselect = choices.index(decision.choice) if decision.choice in choices else 0
                choice = easygui.choicebox(msg, title, choices, preselect=preselect)
                n_manual += 1
        if choice is None:
            print("Lead-Bearbeitung abgebrochen")
            break
        if choice == 'überspringen':
            n_skipped += 1
            continue
        if choice == 'kein Lead':
            mark_not_contact(lead1['name'])
            if comment:
                add_comment(lead1['name'], comment)
                n_auto += 1
        else:
            Api.api.assign_to("Lead",lead1['name'],[lead_owners[choice]])
            lead_contact.complete_lead(lead1['name'], doc, comms)
    print(f"Leads fertig bearbeitet: {n_auto} automatisch als \"nicht kontaktieren\" markiert, "
          f"{n_manual} von Hand entschieden, {n_skipped} übersprungen")
    lead_contact.attach_missing_vcards()

def cleanup_leads() -> None:
    leads = Api.api.get_list("Lead",
                             filters={'first_name': 'Bremer',
                                      'last_name': 'SolidarStrom',
                                      'status':'Open'},
                             limit_page_length=LIMIT)
    for lead1 in leads:
        lead = Api.api.get_doc("Lead",lead1['name'])
        lead['first_name'] = lead['email_id']
        lead['last_name'] = ''
        Api.api.update(lead)
        print(f"{lead1['name']} heißt nun {lead['email_id']}")
        


