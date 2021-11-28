#!/usr/bin/python3

import purchase_invoice
import os
from api import Api
import json
from menu import initial_loads

Api.initialize_with_settings()
initial_loads()

print("Teste Einkaufsrechnungen",end="",flush=True)
with open("test/data/purchase_invoices.json") as f:
    pinv_dict = json.load(f)
for name,pinv_doc in pinv_dict.items():
    print(".",end="",flush=True) # progress bar
    pdf_name = "test/data/"+pinv_doc['name']+".pdf"
    if os.path.isfile(pdf_name):
        #print(pdf_name)
        pinv = purchase_invoice.PurchaseInvoice()
        pinv.update_stock = False
        pinv.parse_invoice(pdf_name,None,False,True)
        # are bill nos the same or same variant, e.g. 22 versus 22a ?
        same = (pinv.no == pinv_doc['bill_no']) or \
               (pinv.no == pinv_doc['bill_no'][0:-1] and \
                pinv_doc['bill_no'][-1] in 'abcdefhg')
        # special double invoice?
        if pinv.no and not same and pinv.no in pinv_doc['bill_no'] \
           and pinv.no[0]=='8':
            os.remove(pdf_name) 
        elif not same:
            print()
            print(name,"  computed invoice no: '",pinv.no,
                  "'  test data :'",pinv_doc['bill_no'],"'")
            text = purchase_invoice.pdf_to_text(pdf_name,pinv.raw)
            print('parser: ',pinv.parser,' raw: ',pinv.raw,' len: ',len(text))
            for line in text:
                #if "echnung" in line or "ummer" in line:
                if pinv_doc['bill_no'] in line:
                    print(line)
                    

