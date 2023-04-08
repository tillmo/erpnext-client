import json
import prerechnung
from api import Api, LIMIT
from args import init
import company
import traceback
from compute_tests import compute_json, compute_diff

init()


Api.load_item_data()
pinvs = Api.api.get_list("Purchase Invoice",filters={'company':'Laden'},
                           limit_page_length=1)
for inv in pinvs:
    atts = Api.api.get_list('File', filters={
		'attached_to_doctype': "Purchase Invoice",
		'attached_to_name': inv['name']}, limit_page_length=LIMIT)
    if len(atts)==2:
        pr = {'doctype':'PreRechnung',
              'company':inv['company'],
              'pdf':inv['supplier_invoice'],
              'typ':'Rechnung',
              'lieferant':inv['supplier'],
              'processed':True,
              'purchase_invoice':inv['name']}
        pr = Api.api.insert(pr)
        compute_json(pr)
    
exit(0)


Api.load_item_data()
for pr in Api.api.get_list("PreRechnung",
                           filters={'purchase_invoice': ['is', 'set']},
                           limit_page_length=LIMIT):  # later on, replace with LIMIT
    compute_json(pr)
exit(0)          

for pr in Api.api.get_list("PreRechnung", filters={'json1': ['is', 'set']},
                           limit_page_length=LIMIT):
    compute_diff(pr)
exit(0)          

company.Company.init_companies()
company.Company.current_load_data()
for pr in Api.api.get_list("PreRechnung", filters={'purchase_invoice': ['is', 'set'], 'error':['is', 'set']},
                           limit_page_length=LIMIT):  # later on, replace with 1
#    if pr.get('json1'):
#        continue
    try:
        pinv1 = Api.api.get_doc("Purchase Invoice", pr['purchase_invoice'])
        #if not pr.get('json'):
        prerechnung.process_inv(pr)
        # create purchase invoice object based on pr['json']
        pr = Api.api.get_doc("PreRechnung", pr['name'])  # reload
        pinv2 = prerechnung.read_and_transfer(pr, check_dup=False)
        pinv2 = Api.api.get_doc("Purchase Invoice", pinv2.name)
        pr['json1'] = json.dumps(pinv1)
        pr['json2'] = json.dumps(pinv2)
        pr['doctype'] = 'PreRechnung'
        Api.api.update(pr)
    except Exception as e:
        print(str(e))
        pr['error'] = str(e)+"\n"+traceback.format_exc()
        pr['short_error'] = str(e)
        pr['doctype'] = 'PreRechnung'
        Api.api.update(pr)
    # with open("pinv1.json", "w") as f:
    #     json.dump(pinv1, f)
    # with open("pinv2.json", "w") as f:
    #     json.dump(pinv2, f)
exit(0)

pr = Api.api.get_list("PreRechnung", filters={'processed': False}, limit_page_length=1)[0]
doc = Api.api.get_doc("PreRechnung", pr['name'])
prerechnung.process_inv(doc)

for pr in Api.api.get_list(
        "PreRechnung", filters={'processed': False}, limit_page_length=1):  # later on, replace 1 with LIMIT
    doc = Api.api.get_doc("PreRechnung", pr['name'])
    prerechnung.process_inv(doc)

exit(0)

for pr in Api.api.get_list("PreRechnung", filters={'purchase_invoice': ['is', 'set']},
                           limit_page_length=LIMIT):  # later on, replace with 1
    pr['processed'] = False
    pr['doctype'] = 'PreRechnung'
    Api.api.update(pr)
    
exit(0)    

for pr in Api.api.get_list("PreRechnung", filters={'json1': ['is', 'set']},
                           limit_page_length=LIMIT):
    pr['json1'] = ""
    pr['json2'] = ""
    pr['doctype'] = 'PreRechnung'
    Api.api.update(pr)
exit(0)
