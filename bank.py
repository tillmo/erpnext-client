import utils
from datetime import datetime
from doc import Doc
from api import Api, LIMIT
from api_wrapper import gui_api_wrapper
import settings
import PySimpleGUI as sg
import company
import payment
from journal import journal_entry
import easygui
from numpy import sign
from collections import defaultdict
import urllib

BT_FIELDS = ['name','deposit','withdrawal','status','date','description',
             'bank_account','company','allocated_amount','unallocated_amount']

class BankAccount(Doc):
    baccounts_by_iban = {}
    baccounts_by_name = {}
    baccounts_by_company = defaultdict(list)
    def __init__(self,doc):
        self.doctype = "Bank Account"
        super().__init__(doc=doc)
        self.company = company.Company.get_company(doc['company'])
        self.iban = doc['iban']
        self.e_account = doc['account']
        self.get_balance()
        self.statement_balance = None
        BankAccount.baccounts_by_iban[self.iban] = self
        BankAccount.baccounts_by_name[self.name] = self
        BankAccount.baccounts_by_company[self.company.name].append(self)
    def blz(self):
        return self.iban[4:12]
    def get_balance(self):
        bts = gui_api_wrapper(Api.api.get_list,'Bank Transaction',
                              filters={'bank_account':self.name,
                                       'docstatus': ['!=', 2],
                                       'status': ['!=','Cancelled']},
                              fields=BT_FIELDS,
                              limit_page_length=LIMIT)
        self.balance = sum([bt['deposit']-bt['withdrawal'] for bt in bts])
    @classmethod
    def init_baccounts(cls):
        if not BankAccount.baccounts_by_iban and not sg.UserSettings()['-setup-']:
            print("Lade Kontodaten",end="")
            for bacc in gui_api_wrapper(Api.api.get_list,
                                        'Bank Account',
                                        fields=['name','company','iban',
                                                'account',
                                                'last_integration_date']):
                print(".",end="")
                BankAccount(bacc)
            print()
    @classmethod
    def clear_baccounts(cls):
        BankAccount.baccounts_by_iban = {}
        BankAccount.baccounts_by_name = {}
        BankAccount.baccounts_by_company = defaultdict(list)
    @classmethod
    def get_baccount_names(cls):
        comp_name = sg.UserSettings()['-company-']
        BankAccount.init_baccounts()
        bank_accounts = BankAccount.baccounts_by_company[comp_name]
        return [ba.name for ba in bank_accounts]
        
class BankTransaction(Doc):
    def __init__(self,doc):
        self.doctype = "Bank Transaction"
        super().__init__(doc=doc)
        self.name = doc['name']
        self.date = doc['date']
        self.withdrawal = doc['withdrawal']
        self.deposit = doc['deposit']
        self.amount = -self.withdrawal if self.withdrawal else self.deposit
        self.bank_account = doc['bank_account']
        self.baccount = BankAccount.baccounts_by_name[self.bank_account]
        self.company_name = doc['company']
        self.company = company.Company.companies_by_name[self.company_name]
        if 'description' in doc:
            self.description = doc['description']
        else:    
            self.description = ""

    def show(self):
        return(self.doc['name']+" {}\n{}\n{:.2f}€".format(utils.show_date4(self.date),self.description,self.amount))

    def link_to(self,doctype,docname,amount):
        entry = {'payment_document': doctype,
                 'payment_entry': docname,
                 'allocated_amount': amount}
        if not 'payment_entries' in self.doc:
            self.doc['payment_entries'] = []
        self.doc['payment_entries'].append(entry)
        self.doc['unallocated_amount'] -= amount 
        self.doc['allocated_amount'] += amount 
        if not self.doc['unallocated_amount']:
            self.doc['status'] = 'Reconciled'

    def journal_entry(self,cacc_or_bt,is_bt):
        amount = self.doc['unallocated_amount']
        withdrawal = min([amount,self.withdrawal])
        deposit = min([amount,self.deposit])
        if is_bt:
            bt = BankTransaction(cacc_or_bt)
            bt.load()
            against_account = bt.baccount.e_account
        else:    
            against_account = cacc_or_bt
        j = journal_entry(self.company,self.baccount.e_account,against_account,
                          deposit,withdrawal,self.description[0:140],
                          self.description,self.date)
        #print(j)
        if j:
            j['account'] = against_account
            self.company.journal.append(j)
            if sg.UserSettings()['-buchen-']:
                gui_api_wrapper(Api.submit_doc,"Journal Entry",j['name'])
                print("Buchungssatz {} gebucht".format(j['name']))
            self.link_to('Journal Entry',j['name'],amount)
            self.update()
            if is_bt:
                bt.link_to('Journal Entry',j['name'],amount)
                bt.update()

    def payment(self,inv,is_recv=None,party=None,party_type=None):
        amount = abs(self.doc['unallocated_amount'])
        if inv:
            amount = min([amount,inv.outstanding])
            p = inv.payment(self.baccount.e_account,amount,self.date)
        else:
            p = payment.create_payment(is_recv,self.company,
                                       self.baccount.e_account,amount,
                                       self.date,party,party_type,
                                       utils.find_ref(self.description),[])
        if p:
            self.doc['doctype'] = 'Bank Transaction'
            self.link_to('Payment Entry',p['name'],amount)
            self.update()
            return p
        else:
            return None

    # find an account, bank transaction of invoice that matches
    # the current bank transaction and link it
    def transfer(self,sinvs,pinvs):
        if self.deposit:
            accounts = self.company.leaf_accounts_for_debit
            invs = sinvs
            side = "withdrawal" 
        else:    
            accounts = self.company.leaf_accounts_for_credit
            invs = pinvs
            side = "deposit"
        # find accounts that could match, using previous journal entries    
        account_names = list(map(lambda acc: acc['name'],accounts))
        account_names.sort()
        jaccs = [(je['account'],
                 utils.similar(self.description,je['user_remark'])) \
                   for je in self.company.journal if 'user_remark' in je and je['user_remark']]
        jaccs.sort(key=lambda x: x[1],reverse=True)
        jaccs = list(set([j for (j,desc) in jaccs[0:5]]))
        for j in jaccs:
            try:
                account_names.remove(j)
            except Exception:
                pass
        account_names = jaccs + account_names
        # find invoices that could match
        invs.sort(key=lambda inv: abs(inv.outstanding-abs(self.amount)))
        inv_texts = list(map(lambda inv: utils.showlist([inv.name,inv.party,inv.reference,inv.outstanding]),invs))
        # find bank transactions in other bank accounts that could match
        filters = {'company':self.company.name,
                   'status':'Pending',
                   'bank_account':['!=',self.bank_account],
                   side:['>',0],
                   'unallocated_amount':abs(self.amount)}
        bts = gui_api_wrapper(Api.api.get_list,'Bank Transaction',
                              fields=BT_FIELDS,
                              filters=filters,limit_page_length=LIMIT)
        bt_texts = list(map(lambda bt: utils.showlist([bt['name'],bt['deposit'] if bt['deposit'] else -bt['withdrawal'],bt['description'],bt['unallocated_amount']]),bts))
        # let the user choose between all these
        title = "Rechnung, Banktransaktion oder Buchungskonto wählen"
        msg = "Bankbuchung:\n"+self.show()+"\n\n"+title+"\n"
        options = ["Anzahlung"]+bt_texts+inv_texts+account_names
        choice = easygui.choicebox(msg, title, options)
        # and process the choice
        if choice=="Anzahlung":
            if self.deposit:
                party_type = 'Customer'
                party_descr = 'Kunden'
                is_recv = True
            else:
                party_type = 'Supplier'
                party_descr = 'Lieferanten'
                is_recv = False
            parties = gui_api_wrapper(Api.api.get_list,party_type,
                                      limit_page_length=LIMIT)
            party_names = list(map(lambda p: p['name'],parties))
            party_names.sort(key=str.casefold)
            title = party_descr+" wählen"
            msg = title
            choice = easygui.choicebox(msg, title, party_names)
            if choice:
                self.payment(None,is_recv=recv,party=choice,
                             party_type=party_type)
        elif choice in inv_texts:
            inv = invs[inv_texts.index(choice)]
            self.payment(inv)
        elif choice:
            is_bt = choice in bt_texts
            if is_bt:
                choice = bts[bt_texts.index(choice)]
            self.journal_entry(choice,is_bt)

    @classmethod
    def submit_entry(cls,doc_name,is_journal=True):
        doctype = "Journal Entry" if is_journal else "Payment Entry"
        doctype_name = "Buchungssatz" if is_journal else "Zahlung"
        bts = gui_api_wrapper(Api.api.get_list,"Bank Transaction",
                              fields=BT_FIELDS,
                              filters=
                              [["Bank Transaction Payments",
                                "payment_entry","=",doc_name]])
        for bt in bts:
            bt_name = bt['name']
            if not bt['unallocated_amount']:
                gui_api_wrapper(Api.submit_doc,"Bank Transaction",bt_name)
            print("Banktransaktion {} gebucht".format(bt_name))
        gui_api_wrapper(Api.submit_doc,doctype,doc_name)
        print("{} {} gebucht".format(doctype_name,doc_name))

    @classmethod
    def delete_entry(cls,doc_name,is_journal=True):
        doctype = "Journal Entry" if is_journal else "Payment Entry"
        doctype_name = "Buchungssatz" if is_journal else "Zahlung"
        bts = gui_api_wrapper(Api.api.get_list,"Bank Transaction",
                              fields=BT_FIELDS,
                              filters=
                              [["Bank Transaction Payments",
                                "payment_entry","=",doc_name]])
        if bts:
            bt = gui_api_wrapper(Api.api.get_doc,"Bank Transaction",
                                 bts[0]['name'])
            bt['payment_entries'] = list(filter(lambda pe: pe['payment_entry']!=doc_name,bt['payment_entries']))
            bt['status'] = 'Pending'
            bt['unallocated_amount'] += bt['allocated_amount']
            bt['allocated_amount'] = 0
            gui_api_wrapper(Api.api.update,bt)
            print("Banktransaktion {} angepasst".format(bt['name']))
        else:
            print("Keine Banktransaktion angepasst: "+\
                  "{} {} nicht in Banktransaktionen gefunden".\
                    format(doctype_name,doc_name))
        gui_api_wrapper(Api.api.delete,doctype,doc_name)
        print("{} {} gelöscht".format(doctype_name,doc_name))

    @classmethod
    def find_bank_transaction(cls,comp_name,total,bill_no=""):
        if not bill_no:
            return None
        key = 'deposit'
        if total<0:
            key = 'withdrawal'
            total = -total
        bts = gui_api_wrapper(Api.api.get_list,
                          'Bank Transaction',
                          fields=BT_FIELDS,
                          filters={'company':comp_name,
                                   key:total,
                                   'description':['like','%'+bill_no+'%'],
                                   'status': 'Pending'})
        bts = [BankTransaction(bt) for bt in bts]
        l = len(bts)
        if l==1:
            return bts[0]
        else:
            return None

class BankStatementEntry:
    def __init__(self,bank_statement):
        self.bank_statement = bank_statement

    def show(self):
        return("{}\n{}\n{}\n{:.2f}€".format(utils.show_date4(self.posting_date),self.purpose,
                                            self.partner,self.amount))
    def cleanup(self):
        self.purpose = utils.remove_space(self.purpose)
        self.partner = utils.remove_space(self.partner)

    def bank_transaction(self):
        entry = {'doctype' : 'Bank Transaction',
                 'date' : self.posting_date,
                 'bank_account' : self.bank_statement.baccount.name,
                 'description' : self.purpose+" "+self.partner,
                 'currency' : 'EUR',
                 'unallocated_amount' : abs(self.amount),
                 'withdrawal' : -self.amount if self.amount < 0 else 0,
                 'deposit' : self.amount if self.amount > 0 else 0 }
        return entry

class BankStatement:
    def __init__(self,bacc):
        self.baccount = bacc
        self.entries = []
        self.read_iban = None
        self.sbal = None
        self.ebal = None
        
    def read_sparkasse_bremen(self,infile):
        first_row = True
        for row in utils.get_csv('iso-8859-4',infile):
            if not row:
                continue
            if first_row:
                first_row = False
                continue
            be = BankStatementEntry(self)
            self.iban = row[0]
            be.posting_date = utils.convert_date2(row[2])
            be.purpose = row[4]
            be.partner = row[11]
            be.partner_iban = row[12]
            be.amount = utils.read_float(row[14])
            be.cleanup()
            self.entries.append(be)

    def read_sparda_ethik(self,infile):
        ebal_str = ""
        for row in utils.get_csv('utf-8',infile,replacenl=False):
            if not row or len(row)<=1:
                continue
            date = utils.convert_date4(row[5])
            if not date or len(row)<=12:
                continue
            # end balance is in the first row
            if not ebal_str:
                ebal_str = row[13]
            be = BankStatementEntry(self)
            be.posting_date = date
            be.purpose = row[10]
            be.partner = row[6]
            be.partner_iban = row[7]
            be.amount = utils.read_float(row[11])
            be.cleanup()
            self.entries.append(be)
            sbal_str = row[13]
        self.sbal = utils.read_float(sbal_str)
        self.ebal = utils.read_float(ebal_str)

    @classmethod
    def get_baccount(cls,infile):
        blz = None
        baccount_no = None
        iban = None
        for row in utils.get_csv('iso-8859-4',infile):
            if not row:
                continue
            if row[1][0:2]=='DE':
                iban = row[1] 
            if row[0]=='BLZ:':
                blz = int(row[1])
                continue
            if row[0]=='Konto:':
                baccount_no = int(row[1])
                continue
            if row[0][0:2]=='DE':
                iban = row[0]
                break
            if blz and baccount_no:
                iban = utils.iban_de(blz,baccount_no)
                break
        if iban and iban in BankAccount.baccounts_by_iban:
            return (BankAccount.baccounts_by_iban[iban],iban)
        else:
            return (None,iban)

    @classmethod
    def read_statement(cls,infile):
        (bacc,iban) = BankStatement.get_baccount(infile)
        if not bacc:
            easygui.msgbox("Konto unbekannt: IBAN {}".format(iban))
            return None
        b = BankStatement(bacc)
        if bacc.blz()=='83094495': #  Ethikbank
            b.read_sparda_ethik(infile)
        elif bacc.blz()=='25090500': # Sparda 
            b.read_sparda_ethik(infile) 
        elif bacc.blz()=='29050101': #  Sparkasse Bremen
            b.read_sparkasse_bremen(infile)
        else:
            easygui.msgbox("Keine Importmöglichkeit für BLZ {}".format(bacc.blz()))
            return None
        return b

    @classmethod
    def process_file(cls,infile):
        b = BankStatement.read_statement(infile)
        if not b:
            return None
        b.transactions = []
        for be in b.entries:
            bt = be.bank_transaction()
            bt1 = bt.copy()
            del bt1['doctype']
            del bt1['unallocated_amount']
            bt1['status'] = ['!=','Cancelled']
            bt1['docstatus'] = ['!=',2]
            #todo: relax the filter wrt the date (which sometimes is adapted by the bank)
            bts = gui_api_wrapper(Api.api.get_list,'Bank Transaction',
                                  fields=BT_FIELDS,filters=bt1)
            if not bts:
                gui_api_wrapper(Api.api.insert,bt)
                b.transactions.append(bt)
        doc = b.baccount.doc
        doc['last_integration_date'] = datetime.today().strftime('%Y-%m-%d')
        b.baccount.doc = gui_api_wrapper(Api.api.update_with_doctype,doc,"Bank Account")
        if b.ebal:
            b.baccount.statement_balance = b.ebal
        b.baccount.get_balance()
        return b
