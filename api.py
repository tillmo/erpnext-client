from api_wrapper import gui_api_wrapper
import json
from os.path import expanduser 
from frappeclient import FrappeClient
from collections import defaultdict
from settings import WAREHOUSE, DEFAULT_SUPPLIER_GROUP
import itertools
import PySimpleGUI as sg

LIMIT = 100000 # limit_page_length

class Api(object):
    api = None
    items_by_code = []
    item_code_translation = []
    accounts_by_company = {}
    @classmethod
    def initialize(cls):
        settings = sg.UserSettings()
        Api.api = FrappeClient(settings['-server-'])
        Api.api.authenticate(settings['-key-'], settings['-secret-'])
        Api.api.get_list("Company")
    @classmethod
    def load_item_data(cls):
        if not Api.items_by_code:
            Api.items_by_code = {}
            Api.item_code_translation = defaultdict(lambda: {})
            company_name = sg.UserSettings()['-company-']
            for item in Api.api.get_list('Item',limit_page_length=LIMIT):
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
    @classmethod
    def load_account_data(cls):
        if not Api.accounts_by_company:
            accounts = Api.api.get_list('Account',limit_page_length=LIMIT)
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
