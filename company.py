JOURNAL_LIMIT = 100

import PySimpleGUI as sg
from api import Api, LIMIT
from api_wrapper import gui_api_wrapper
import bank
import settings
import itertools
import urllib

class Invoice:
    def __init__(self,doc,is_sales):
        self.doc = doc
        self.is_sales = is_sales
        self.name = doc['name']
        self.status = doc['status']
        self.amount = doc['grand_total']
        self.outstanding = doc['outstanding_amount']
        if self.is_sales:
            self.reference = doc['name']
            self.party = doc['customer']
            self.party_type = 'Customer'
        else:    
            self.reference = doc['bill_no']
            self.amount = -self.amount
            self.party = doc['supplier']
            self.party_type = 'Supplier'

class Company:
    companies_by_name = {}
    def leaf_accounts_starting_with_root_type(self,root_type):
        root_types = list(self.leaf_accounts_by_root_type.keys())
        root_types.remove(root_type)
        accounts = self.leaf_accounts_by_root_type[root_type].copy()
        for rt in root_types:
            accounts += self.leaf_accounts_by_root_type[rt].copy()
        return accounts
    
    def __init__(self,doc):
        self.doc = doc
        self.name = doc['name']
        self.cost_center = doc['cost_center']
        self.expense_account = doc['default_expense_account']
        self.payable_account = doc['default_payable_account']
        self.receivable_account = doc['default_receivable_account']
        self.default_finance_book = doc['default_finance_book']
        self.taxes = {}
        self.default_vat = None
        Company.companies_by_name[self.name] = self
        self.data_loaded = False

    def load_data(self):
        if self.data_loaded:
            return
        print("Lade Daten für "+self.name,end="")
        for t in gui_api_wrapper(Api.api.get_list,
                                 'Purchase Taxes and Charges Template',
                                 filters={'company':self.name}):
            print(".",end="")
            taxt = gui_api_wrapper(Api.api.get_doc,
                                  'Purchase Taxes and Charges Template',
                                   urllib.parse.quote(t['name']))
            if taxt and 'taxes' in taxt:
                for tax in taxt['taxes']:
                    self.taxes[tax['rate']] = tax['account_head']
                    if not self.default_vat:
                        self.default_vat = tax['rate']
        Api.load_account_data()
        print(".",end="")
        self.accounts = Api.accounts_by_company[self.name]
        self.leaf_accounts = list(filter(lambda acc: acc['is_group']==0, self.accounts))
        self.leaf_accounts.sort(key=lambda acc: acc['root_type'])
        self.leaf_accounts_by_root_type = {}
        for rt, accs in itertools.groupby(self.leaf_accounts,
                                          lambda acc: acc['root_type']):
            print(".",end="")
            self.leaf_accounts_by_root_type[rt] = list(accs)
        self.doc = gui_api_wrapper(Api.api.get_doc,'Company',self.name)
        self.leaf_accounts_for_debit = self.leaf_accounts_starting_with_root_type("Income")
        self.leaf_accounts_for_credit = self.leaf_accounts_starting_with_root_type("Expense")
        jes = gui_api_wrapper(Api.api.get_list,
            'Journal Entry',
            filters={'company': self.name},
            limit_page_length=JOURNAL_LIMIT,
            order_by='posting_date DESC')
        self.journal = [gui_api_wrapper(Api.api.get_doc,
                                        'Journal Entry',
                                        je['name']) for je in jes]
        #print(self.name,len(self.journal))
        print(".")
        self.data_loaded = True

    @classmethod    
    def current_load_data(cls):
        settings = sg.UserSettings()
        comp_name = settings['-company-']
        if comp_name:
            comp = Company.get_company(comp_name)
            comp.load_data()
        
    @classmethod    
    def init_companies(cls):
        if not Company.companies_by_name:
            print("Lade Firmendaten",end="")
            for comp in gui_api_wrapper(Api.api.get_list,'Company'):
                print(".",end="")
                Company(comp)
            print()
    @classmethod
    def all(cls):
        return list(Company.companies_by_name.keys())
    @classmethod    
    def get_company(cls,name):
        try:
            return Company.companies_by_name[name]
        except Exception:
            return None
    def get_invoices_of_type_and_status(self,inv_type,status):
        is_sales = (inv_type=='Sales Invoice')
        invs = gui_api_wrapper(Api.api.get_list,inv_type,
                               filters={'status':status,'company':self.name},
                               limit_page_length=LIMIT)
        return list(map(lambda inv: Invoice(inv,is_sales),invs))
    def get_open_invoices_of_type(self,inv_type):
        return self.get_invoices_of_type_and_status(inv_type,'Unpaid') + \
               self.get_invoices_of_type_and_status(inv_type,'Overdue') 
    def get_open_sales_invoices(self):
        return self.get_open_invoices_of_type('Sales Invoice')
    def get_open_purchase_invoices(self):
        return self.get_open_invoices_of_type('Purchase Invoice')
    def get_open_invoices(self):
        return self.get_open_invoices_of_type('Purchase Invoice') + \
               self.get_open_invoices_of_type('Sales Invoice')

    def reconciliate(self,bt):
        Api.load_account_data()
        sinvs = self.get_open_sales_invoices()
        pinvs = self.get_open_purchase_invoices()
        bt = gui_api_wrapper(Api.api.get_doc,'Bank Transaction',bt['name'])
        bank.BankTransaction(bt).transfer(sinvs,pinvs)

    def reconciliate_all(self):
        Api.load_account_data()
        sinvs = self.get_open_sales_invoices()
        pinvs = self.get_open_purchase_invoices()
        bts = gui_api_wrapper(Api.api.get_list,'Bank Transaction',
                              filters={'company':self.name,
                                       'status':'Pending'})
        for bt in bts:
            bt = gui_api_wrapper(Api.api.get_doc,'Bank Transaction',bt['name'])
            if (not 'payment_entries' in bt) or (not bt['payment_entries']):
                bank.BankTransaction(bt).transfer(sinvs,pinvs)
    def open_bank_transactions(self):
        bts = gui_api_wrapper(Api.api.get_list,'Bank Transaction',
                                                filters={'company':self.name,
                                                         'status':'Pending'},
                                                limit_page_length=LIMIT)
        return list(filter(lambda bt: \
                        (not 'payment_entries' in bt) or (not bt['payment_entries']),bts))
    def open_journal_entries(self):
        return gui_api_wrapper(Api.api.get_list,'Journal Entry',
                                                filters={'company':self.name,
                                                         'docstatus':0},
                                                limit_page_length=LIMIT)
    def open_payment_entries(self):
        return gui_api_wrapper(Api.api.get_list,'Payment Entry',
                                                filters={'company':self.name,
                                                         'docstatus':0},
                                                limit_page_length=LIMIT)
    def open_purchase_invoices(self):
        return gui_api_wrapper(Api.api.get_list,'Purchase Invoice',
                                                filters={'company':self.name,
                                                         'docstatus':0},
                                                limit_page_length=LIMIT)
