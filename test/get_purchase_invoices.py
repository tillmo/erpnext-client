#!/usr/bin/python3

from api import Api, LIMIT
import pickle

Api.initialize_with_settings()

pinvs = Api.api.get_list("Purchase Invoice",
                         filters= {'status':['in',['Paid','Unpaid','Overdue','Partly Paid']]},
                         limit_page_length=LIMIT)
pinv_dict = {}
for pinv in pinvs:
    print(".",end="",flush=True)
    pname = pinv['name']
    full_pinv = Api.api.get_doc('Purchase Invoice',pname)
    if 'supplier_invoice' in full_pinv:
        pinv_dict[pname] = full_pinv
        pdf = Api.api.get_file(full_pinv['supplier_invoice'])
        filename = "test/data/"+pname+".pdf"
        with open(filename,'wb') as f:
            f.write(pdf)

pickle.dump(pinv_dict, open("test/data/purchase_invoices.p", "wb" ), protocol=4)

print()

