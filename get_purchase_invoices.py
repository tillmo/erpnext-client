#!/usr/bin/python3

JOURNAL_LIMIT = 100

from api import Api, LIMIT
from api_wrapper import gui_api_wrapper, api_wrapper_test
import os
import PySimpleGUI as sg
import pickle

def init():
    sg.user_settings_filename(filename='erpnext.json')
    settings = sg.UserSettings()
    settings['-setup-'] = not api_wrapper_test(Api.initialize)

init()

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

