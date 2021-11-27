#!/usr/bin/python3

# get all purchase invoices and their pdfs from the ERPNext database
# and store them as test data

import os
from api import Api, LIMIT
from purchase_invoice import pdf_to_text
import pickle

Api.initialize_with_settings()

pinvs = Api.api.get_list("Purchase Invoice",
                         filters= {'status':['in',['Paid','Unpaid','Overdue','Partly Paid']]},
                         limit_page_length=LIMIT)
pinv_dict = {}
for pinv in pinvs:
    print(".",end="",flush=True) # progress bar
    pname = pinv['name']
    full_pinv = Api.api.get_doc('Purchase Invoice',pname)
    if 'supplier_invoice' in full_pinv:
            pdf = Api.api.get_file(full_pinv['supplier_invoice'])
            filename = "test/data/"+pname+".pdf"
            with open(filename,'wb') as f:
                f.write(pdf)
            text = pdf_to_text(filename)
            if text: # only keep invoices where the pdf contains some text
                pinv_dict[pname] = full_pinv
            else:
                os.remove(filename) 

pickle.dump(pinv_dict, open("test/data/purchase_invoices.p", "wb" ), protocol=4)

print()

