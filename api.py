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
            items = Api.api.get_list('Item', limit_page_length=LIMIT,
                                     filters={'disabled': 0},
                                     fields=['name', 'item_code', 'item_name',
                                             'item_group', 'description'])
            print("Lese alle {} ERPNext-Artikel ein".format(len(items)))
            for item in items:
                item['supplier_items'] = []
                Api.items_by_code[item['item_code']] = item
            # Join child table Item Supplier via parent doctype to fetch all
            # supplier mappings in a single request (child doctypes cannot be
            # queried directly via the REST API).
            supplier_rows = Api.api.get_list(
                'Item', limit_page_length=LIMIT,
                filters={'disabled': 0},
                fields=['item_code',
                        '`tabItem Supplier`.supplier as si_supplier',
                        '`tabItem Supplier`.supplier_part_no as si_supplier_part_no'])
            for row in supplier_rows:
                if not row.get('si_supplier_part_no'):
                    continue
                item = Api.items_by_code.get(row['item_code'])
                if not item:
                    continue
                supplier = row['si_supplier']
                supplier_part_no = row['si_supplier_part_no']
                item['supplier_items'].append(
                    {'supplier': supplier,
                     'supplier_part_no': supplier_part_no})
                Api.item_code_translation[supplier][supplier_part_no] = item['item_code']
            # Same trick for Item Default - one row per (item, default) entry;
            # fetch expense_account for the current company and seed missing defaults.
            defaults_rows = Api.api.get_list(
                'Item', limit_page_length=LIMIT,
                filters={'disabled': 0},
                fields=['name', 'item_code',
                        '`tabItem Default`.company as default_company',
                        '`tabItem Default`.expense_account as default_expense_account'])
            items_with_defaults = set()
            for row in defaults_rows:
                if row.get('default_company') != company_name:
                    continue
                items_with_defaults.add(row['name'])
                item = Api.items_by_code.get(row.get('item_code'))
                if item and row.get('default_expense_account'):
                    item['expense_account'] = row['default_expense_account']
            missing_defaults = [item for item in items
                                if item['name'] not in items_with_defaults]
            if missing_defaults:
                print("Ergänze item_defaults für {} Artikel".format(len(missing_defaults)),
                      end="")
                for item in missing_defaults:
                    print(".", end="")
                    doc = Api.api.get_doc('Item', item['name'])
                    if not doc['item_defaults']:
                        doc['item_defaults'] = [{'company': company_name,
                                                 'default_warehouse': WAREHOUSE}]
                        gui_api_wrapper(Api.api.update, doc)
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
