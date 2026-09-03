from __future__ import annotations

from typing import Any
from api import Api, LIMIT
from settings import LEAD_OWNERS, LEAD_DNC_FIELD
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

def format(lead: dict[str, Any]) -> dict[str, Any]:
    lead['creation'] = lead['creation'].split()[0]
    return lead

def show_open_leads() -> None:
    leads = Api.api.get_list("Lead",
                             filters={'status':'Open'},
                             fields=['name','status','lead_name', 'creation'],
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
                             limit_page_length=LIMIT)
    for lead1 in leads:
        #print(lead1['lead_owner'])
        res = Api.api.load_doc("Lead",lead1['name'])
        doc = res['docs'][0]
        versions = res['docinfo']['versions']
        choice: str | None = None
        # flagged, or marked "Do Not Contact" before and reopened by a new e-mail
        if doc.get(LEAD_DNC_FIELD) or any(is_change_into_not_contact(v) for v in versions):
            choice = 'kein Lead'
            print(f'Markiere Lead {lead1["name"]} {lead1["lead_name"]} wieder als "nicht kontaktieren"')
        if not choice:
            comms = res['docinfo']['communications']
            title = f"Bitte Lead Owner für {lead1['name']} {lead1['lead_name']} wählen"
            texts = [utils.html_to_text(comm['content']) for comm in comms]
            text = "\n--------------------\n".join(texts)
            text = "\n".join(text.split("\n")[:35])[:1000]
            msg = f"{doc['name']}   {doc['lead_name']}\n\n{text}"
            choice = easygui.choicebox(msg, title, choices)
        if choice is None:
            print("Lead-Bearbeitung abgebrochen")        
            return
        if choice == 'überspringen':
            continue
        if choice == 'kein Lead':
            mark_not_contact(lead1['name'])
        else:
            Api.api.assign_to("Lead",lead1['name'],[lead_owners[choice]])
    print("Leads fertig bearbeitet")        

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
        


