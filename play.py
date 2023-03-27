import json
import prerechnung
from api import Api
from args import init
import company

init()
company.Company.init_companies()
company.Company.current_load_data()
for pr in Api.api.get_list("PreRechnung", filters={'purchase_invoice': ['>', 'a']},
                           limit_page_length=1):  # later on, replace with 1
    pinv1 = Api.api.get_doc("Purchase Invoice", pr['purchase_invoice'])
    if not pr.get('json'):
        prerechnung.process_inv(pr)
    # create purchase invoice object based on pr['json']
    pr = Api.api.get_doc("PreRechnung", pr['name'])  # reload
    pinv2 = prerechnung.read_and_transfer(pr, check_dup=False)
    pinv2 = Api.api.get_doc("Purchase Invoice", pinv2.name)
    with open("pinv1.json", "w") as f:
        json.dump(pinv1, f)
    with open("pinv2.json", "w") as f:
        json.dump(pinv2, f)
exit(0)

pr = Api.api.get_list("PreRechnung", filters={'processed': False}, limit_page_length=1)[0]
doc = Api.api.get_doc("PreRechnung", pr['name'])
prerechnung.process_inv(doc)

for pr in Api.api.get_list(
        "PreRechnung", filters={'processed': False}, limit_page_length=1):  # later on, replace 1 with LIMIT
    doc = Api.api.get_doc("PreRechnung", pr['name'])
    prerechnung.process_inv(doc)
