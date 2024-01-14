from api_wrapper import gui_api_wrapper, api_wrapper_test
import json
from os.path import expanduser 
from frappeclient import FrappeClient
from collections import defaultdict
from settings import WAREHOUSE, DEFAULT_SUPPLIER_GROUP
import itertools
import PySimpleGUI as sg
import requests
import time

LIMIT = 100000 # limit_page_length

class Api(object):
    api = None
    items_by_code = {}
    item_code_translation = []
    accounts_by_company = {}
    @classmethod
    def initialize(cls):
        settings = sg.UserSettings()
        Api.api = FrappeClient(settings['-server-'],
                               api_key=settings['-key-'],
                               api_secret=settings['-secret-'])
#        if not Api.api.authenticate(settings['-key-'], settings['-secret-']):
#            print(f"Anmeldung bei {settings['-server-']} fehlgeschlagen")
#            exit(1)
        return Api.api.get_list("Company")
    @classmethod
    def initialize_with_settings(cls):
        sg.user_settings_filename(filename='erpnext.json')
        settings = sg.UserSettings()
        settings['-setup-'] = not api_wrapper_test(Api.initialize)
    @classmethod
    def load_item_data(cls):
        if not Api.items_by_code:
            Api.items_by_code = {}
            Api.item_code_translation = defaultdict(lambda: {})
            company_name = sg.UserSettings()['-company-']
            items = Api.api.get_list('Item',limit_page_length=LIMIT,
                                     fields=['item_code','item_name'])
            print("Lese alle {} ERPNext-Artikel ein".format(len(items)),end="")
            for item in items:
                print(".",end="")
                item_code = item["item_code"]
                doc = Api.api.get_doc('Item', item_code)
                Api.items_by_code[item_code] = doc
                if not doc['item_defaults']:
                    doc['item_defaults'] = [{'company': company_name,
                                             'default_warehouse': WAREHOUSE}]
                    gui_api_wrapper(Api.api.update,doc)
                for supplier_items in doc['supplier_items']:
                    if 'supplier_part_no' in supplier_items:
                        supplier = supplier_items['supplier']
                        supplier_part_no = supplier_items['supplier_part_no']
                        Api.item_code_translation[supplier][supplier_part_no] =\
                                                  item_code
            print()
            
    @classmethod
    def load_account_data(cls):
        if not Api.accounts_by_company:
            accounts = Api.api.get_list('Account',
                                        fields=['name','account_name','company',
                                                'is_group','root_type'],
                                        limit_page_length=LIMIT)
            accounts.sort(key=lambda acc:acc["company"])
            for c, accs in itertools.groupby(accounts, key=lambda acc:acc["company"]):
                Api.accounts_by_company[c] = list(accs)

    @classmethod
    def submit_doc(cls,doctype,docname):
        doc = gui_api_wrapper(Api.api.get_doc,doctype,docname)
        gui_api_wrapper(Api.api.submit,doc)

    @classmethod
    def create_supplier(cls,supplier):
        supps = gui_api_wrapper(Api.api.get_list,"Supplier",
                              filters={'name':supplier})
        if not supps:
            doc = {'doctype' : 'Supplier',
                   'supplier_name' : supplier,
                   'supplier_group': DEFAULT_SUPPLIER_GROUP }
            gui_api_wrapper(Api.api.insert,doc)
