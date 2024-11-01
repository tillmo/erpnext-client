JOURNAL_LIMIT = 100

from doc import Doc
import PySimpleGUI as sg
from api import Api, LIMIT
from api_wrapper import gui_api_wrapper
from invoice import Invoice
import bank
import settings
import itertools
import urllib
from collections import defaultdict

class Company(Doc):
    companies_by_name = {}
    def leaf_accounts_starting_with_root_type(self,root_type):
        root_types = list(self.leaf_accounts_by_root_type.keys())
        root_types.remove(root_type)
        accounts = self.leaf_accounts_by_root_type[root_type].copy()
        for rt in root_types:
            accounts += self.leaf_accounts_by_root_type[rt].copy()
        return accounts
    
    def __init__(self,doc):
        self.doctype = "Company"
        super().__init__(doc=doc)
        self.cost_center = doc.get('cost_center')
        self.expense_account = doc.get('default_expense_account')
        self.payable_account = doc.get('default_payable_account')
        self.receivable_account = doc.get('default_receivable_account')
        self.default_finance_book = doc.get('default_finance_book')
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
        self.journal = gui_api_wrapper(Api.api.get_list,
            'Journal Entry',
            fields=['name','title','company','posting_date','user_remark',
                'total_debit','total_credit','remark','is_opening',
                "`tabJournal Entry Account`.account as account",
                "`tabJournal Entry Account`.idx as idx",
                "`tabJournal Entry Account`.cost_center as cost_center",
                "`tabJournal Entry Account`.debit_in_account_currency as debit_in_account_currency",
                "`tabJournal Entry Account`.credit_in_account_currency as credit_in_account_currency"
                 ],
            filters={'company': self.name},
            limit_page_length=JOURNAL_LIMIT,
            order_by='posting_date DESC')
        self.journal = [je for je in self.journal if je['idx']==2]
        #print(self.name,len(self.journal))
        pis = gui_api_wrapper(Api.api.get_list,
            'Purchase Invoice',
            filters={'company': self.name},
            fields=['name','title','supplier','supplier_name','company',
                'posting_date','is_paid','cost_center','bill_no',
                'update_stock','total_qty','total','net_total',
                'total_taxes_and_charges','grand_total','credit_to',
                'is_opening','against_expense_account',
                "`tabPurchase Invoice Item`.expense_account as expense_account"
                ],
            limit_page_length=JOURNAL_LIMIT,
            order_by='posting_date DESC')
        self.purchase_invoices = defaultdict(list)
        for pi in pis:
            print(".",end="")
            self.purchase_invoices[pi['supplier']].append(pi)
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
            for comp in Api.api.get_list('Company'):
                print(".",end="")
                Company(comp)
            print()
    @classmethod    
    def clear_companies(cls):
        Company.companies_by_name = {}
    @classmethod
    def all(cls):
        return list(Company.companies_by_name.keys())
    @classmethod    
    def get_company(cls,name):
        try:
            return Company.companies_by_name[name]
        except Exception:
            return None
    def get_invoices_of_type(self,inv_type,open_invs):
        is_sales = (inv_type=='Sales Invoice')
        filters={'company':self.name}
        if open_invs:
            filters['status'] = ['in',['Draft','Unpaid','Overdue','Partly Paid','Return']]
        else:    
            filters['status'] = ['in',['Paid']]
        fields = ['name','status','posting_date','grand_total',
                  'outstanding_amount','company','is_return']
        if is_sales:
            fields += ['customer','custom_ebay']
        else:
            fields += ['supplier','bill_no']
        invs = gui_api_wrapper(\
                Api.api.get_list,inv_type,
                filters=filters,
                fields=fields,               
                limit_page_length=LIMIT)
        return [Invoice(inv,is_sales) for inv in invs if (not open_invs) or inv['outstanding_amount']]
    def get_sales_invoices(self,open_invs):
        return self.get_invoices_of_type('Sales Invoice',open_invs)
    def get_purchase_invoices(self,open_invs):
        return self.get_invoices_of_type('Purchase Invoice',open_invs)
    def get_invoices(self,open_invs):
        return self.get_invoices_of_type('Purchase Invoice',open_invs) + \
               self.get_invoices_of_type('Sales Invoice',open_invs)
    def get_open_pre_invoices(self,advance):
        typ = 'Anzahlungsrechnung' if advance else 'Rechnung'
        return gui_api_wrapper(\
                Api.api.get_list,'PreRechnung',
                filters={'eingepflegt':False,
                         'typ':typ,
                         'company':self.name},
                fields= ['datum','name','chance','lieferant','pdf','json',
                         'lager','selbst_bezahlt','vom_konto_überwiesen','typ',
                         'processed', 'balkonmodule', 'buchungskonto'],
                limit_page_length=LIMIT)

    def reconcile(self,bt):
        Api.load_account_data()
        sinvs = self.get_sales_invoices(True)
        pinvs = self.get_purchase_invoices(True)
        sinvs1 = [inv for inv in sinvs if not inv.is_return]+[inv for inv in pinvs if inv.is_return]
        pinvs1 = [inv for inv in pinvs if not inv.is_return]+[inv for inv in sinvs if inv.is_return]
        bt = gui_api_wrapper(Api.api.get_doc,'Bank Transaction',bt['name'])
        bank.BankTransaction(bt).transfer(sinvs1,pinvs1)

    def reconcile_all(self):
        Api.load_account_data()
        sinvs = self.get_sales_invoices(True)
        pinvs = self.get_purchase_invoices(True)
        bts = gui_api_wrapper(Api.api.get_list,'Bank Transaction',
                              fields=bank.BT_FIELDS,
                              filters={'company':self.name,
                                       'status':'Pending'})
        for bt in bts:
            bt = gui_api_wrapper(Api.api.get_doc,'Bank Transaction',bt['name'])
            if (not 'payment_entries' in bt) or (not bt['payment_entries']):
                bank.BankTransaction(bt).transfer(sinvs,pinvs)
    def open_bank_transactions(self):
        bts = gui_api_wrapper(Api.api.get_list,'Bank Transaction',
                              fields=bank.BT_FIELDS,
                              filters={'company':self.name,
                                       'status':'Pending',
                                       'unallocated_amount':['>',0]},
                                       limit_page_length=LIMIT)
        return bts
    def open_journal_entries(self):
        return gui_api_wrapper(Api.api.get_list,'Journal Entry',
                               filters={'company':self.name,
                                        'docstatus':0},
                               limit_page_length=LIMIT)
    def unbooked_payment_entries(self):
        return gui_api_wrapper(Api.api.get_list,'Payment Entry',
                               filters={'company':self.name,
                                        'docstatus':0},
                               fields=['name','payment_type',
                                       'unallocated_amount',
                                       'paid_amount','party','posting_date'],
                                        limit_page_length=LIMIT)
    def unassigned_payment_entries(self):
        return gui_api_wrapper(Api.api.get_list,'Payment Entry',
                               filters={'company':self.name,
                                        'docstatus':1,
                                        'unallocated_amount':['>',0]},
                               fields=['name','payment_type',
                                       'unallocated_amount',
                                       'paid_amount','party','posting_date'],
                                        limit_page_length=LIMIT)
    def pre_tax_templates(self):
        return gui_api_wrapper(Api.api.get_list,
                                'Purchase Taxes and Charges Template',
                                filters={'company':self.name},
                                limit_page_length=LIMIT)
    def descendants(self):
        children = Api.api.get_list("Company",
                                    filters={'parent_company':self.name},
                                    limit_page_length=LIMIT)
        descendants = [self]
        for c in children:
            descendants += Company.companies_by_name[c['name']].descendants()
        return descendants
    
    @classmethod    
    def descendants_by_name(cls, company_name):
        descendants = Company.companies_by_name[company_name].descendants()
        return list(map(lambda c:c.name,descendants))
