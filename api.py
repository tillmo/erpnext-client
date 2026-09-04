from __future__ import annotations

from api_wrapper import gui_api_wrapper, api_wrapper_test
import json
from os.path import expanduser 
from frappeclient import FrappeClient
from collections import defaultdict
from settings import WAREHOUSE, DEFAULT_SUPPLIER_GROUP
import itertools
import PySimpleGUI as sg
import re
import requests
from difflib import SequenceMatcher
import time
from typing import Any

LIMIT = 100000 # limit_page_length

class Api(object):
    api: FrappeClient = None  # type: ignore[assignment]
    items_by_code: dict[str, dict[str, Any]] = {}
    item_code_translation: dict[str, dict[str, str]] = defaultdict(dict)
    accounts_by_company: dict[str, list[dict[str, Any]]] = {}
    suppliers_cache: list[dict[str, Any]] | None = None
    @classmethod
    def initialize(cls) -> list[dict[str, Any]]:
        settings = sg.UserSettings()
        Api.api = FrappeClient(settings['-server-'],
                               api_key=settings['-key-'],
                               api_secret=settings['-secret-'])
#        if not Api.api.authenticate(settings['-key-'], settings['-secret-']):
#            print(f"Anmeldung bei {settings['-server-']} fehlgeschlagen")
#            exit(1)
        return Api.api.get_list("Company")
    @classmethod
    def initialize_with_settings(cls) -> None:
        sg.user_settings_filename(filename='erpnext.json')
        settings = sg.UserSettings()
        settings['-setup-'] = not api_wrapper_test(Api.initialize)
    @classmethod
    def load_item_data(cls) -> None:
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
                item = Api.items_by_code.get(row['item_code'])  # type: ignore[assignment]
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
            items_with_defaults: set[str] = set()
            for row in defaults_rows:
                if row.get('default_company') != company_name:
                    continue
                items_with_defaults.add(row['name'])
                item = Api.items_by_code.get(row.get('item_code'))  # type: ignore[assignment, arg-type]
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
    def load_account_data(cls) -> None:
        if not Api.accounts_by_company:
            accounts = Api.api.get_list('Account',
                                        fields=['name','account_name','company',
                                                'is_group','root_type'],
                                        limit_page_length=LIMIT)
            accounts.sort(key=lambda acc:acc["company"])
            for c, accs in itertools.groupby(accounts, key=lambda acc:acc["company"]):
                Api.accounts_by_company[c] = list(accs)

    @classmethod
    def submit_doc(cls, doctype: str, docname: str) -> None:
        doc = gui_api_wrapper(Api.api.get_doc,doctype,docname)
        gui_api_wrapper(Api.api.submit,doc)

    @classmethod
    def find_supplier(cls, name: str | None, tax_id: str | None = None) -> str | None:
        """The ERPNext supplier for a name as printed on an invoice (punctuation and legal-form
        spelling tolerated) or for a VAT id; None if unknown."""
        if not name and not tax_id:
            return None
        if Api.suppliers_cache is None:
            Api.suppliers_cache = Api.api.get_list('Supplier', fields=['name', 'supplier_name', 'tax_id'],
                                                   limit_page_length=LIMIT)

        def norm(s: str | None) -> str:
            return re.sub(r'[^a-z0-9]', '', (s or '').lower().replace('&', 'und').replace('ß', 'ss'))

        def core(s: str | None) -> str:
            """name without legal form, address or brand in parentheses (ERPNext names often carry one)"""
            t = re.split(r'[,|·(]| - ', s or '')[0]
            t = re.sub(r'\b(gmbh|mbh|co\.?|kg|ag|e\.?\s?v\.?|ohg|gbr|ug|se|inc\.?|ltd\.?|und|&)\b', ' ', t, flags=re.I)
            return norm(t)
        if tax_id:
            for s in Api.suppliers_cache:
                if s.get('tax_id') and norm(s['tax_id']) == norm(tax_id):
                    return s['name']
        key = norm(name)
        if not key:
            return None
        for s in Api.suppliers_cache:
            if key in (norm(s['name']), norm(s.get('supplier_name'))):
                return s['name']
        ckey = core(name)
        if len(ckey) >= 5:
            hits = [s['name'] for s in Api.suppliers_cache
                    if core(s['name']) == ckey or core(s.get('supplier_name')) == ckey]
            if len(hits) == 1:
                return hits[0]
        best, best_score = None, 0.0
        for s in Api.suppliers_cache:
            score = SequenceMatcher(None, key, norm(s['name'])).ratio()
            if score > best_score:
                best, best_score = s['name'], score
        return best if best_score >= 0.9 else None

    @classmethod
    def supplier_names(cls) -> list[str]:
        """All ERPNext supplier names (cached), e.g. as a hint for the invoice extraction."""
        if Api.suppliers_cache is None:
            Api.find_supplier('-')
        return sorted(s['name'] for s in (Api.suppliers_cache or []))

    @classmethod
    def create_supplier(cls, supplier: str) -> None:
        supps = gui_api_wrapper(Api.api.get_list,"Supplier",
                              filters={'name':supplier})
        if not supps:
            doc = {'doctype' : 'Supplier',
                   'supplier_name' : supplier,
                   'supplier_group': DEFAULT_SUPPLIER_GROUP }
            gui_api_wrapper(Api.api.insert,doc)
