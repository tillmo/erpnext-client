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
print(gui_api_wrapper(Api.api.get_doc,'Payment Entry','ACC-PAY-2021-00014'))
exit(0)

pinvs = Api.api.get_list("Purchase Invoice",limit_page_length=1)
pinv_dict = {}
for pinv in pinvs:
    pname = pinv['name']
    full_pinv = Api.api.get_doc('Purchase Invoice',pname)
    pinv_dict[pname] = full_pinv
    pdf = Api.api.get_file(full_pinv['pdf'])
    filename = "test/data/"+pname+".pdf"
    with os.fdopen(filename,'wb') as f:
        f.write(pdf)

with os.fdopen(filename,'wb') as f:
    f.write(pdf)
        

pickle.dump(pinv_dict, open("test/data/purchase_invoices.p", "wb" ), protocol=4)


