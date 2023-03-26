import prerechnung
from api import Api
from args import init
import company

init()
company.Company.init_companies()
doc = Api.api.get_doc("PreRechnung",'PreR00492')
if not doc.get('json'):
    prerechnung.process_inv(doc)
prerechnung.read_and_transfer(doc)

exit(0)

pr = Api.api.get_list("PreRechnung", filters={'processed': False}, limit_page_length=1)[0]
doc = Api.api.get_doc("PreRechnung", pr['name'])
prerechnung.process_inv(doc)


for pr in Api.api.get_list(
        "PreRechnung", filters={'processed': False}, limit_page_length=1):  # later on, replace 1 with LIMIT
    doc = Api.api.get_doc("PreRechnung", pr['name'])
    prerechnung.process_inv(doc)
