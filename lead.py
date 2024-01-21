from api import Api, LIMIT
from settings import LEAD_OWNERS
import utils
import easygui

def process_open_leads():
    cleanup_leads()
    lead_owners = {}
    for lo in LEAD_OWNERS:
        lo1 = Api.api.get_list("User",filters={'first_name':lo})
        if lo1:
            lead_owners[lo] = lo1[0]['name']
    lead_owner_list = list(lead_owners.keys())        
    choices = lead_owner_list + ['kein Lead','überspringen']
    leads = Api.api.get_list("Lead",
                             filters={'status':'Open',
                                      '_assign':['like',None]},
                             fields=['name','status'],
                             limit_page_length=LIMIT)
    for lead1 in leads:
        #print(lead1['lead_owner'])
        res = Api.api.load_doc("Lead",lead1['name'])
        doc = res['docs'][0]
        comms = res['docinfo']['communications']
        title = "Bitte Lead Owner wählen"
        texts = [utils.html_to_text(comm['content']) for comm in comms]
        text = "\n--------------------\n".join(texts)
        text = text[:750]
        msg = f"{doc['name']}   {doc['lead_name']}\n\n{text}"
        choice = easygui.choicebox(msg, title, choices)
        if choice is None:
            break
        if choice == 'überspringen':
            continue
        if choice == 'kein Lead':
            doc = Api.api.get_doc("Lead",lead1['name'])
            doc['status'] = 'Do Not Contact'
            Api.api.update(doc)    
        else:
            Api.api.assign_to("Lead",lead1['name'],[lead_owners[choice]])
    print("Leads fertig bearbeitet")        

def cleanup_leads():
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
        


