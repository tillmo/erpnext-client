import company
import utils
from api import Api
from api_wrapper import gui_api_wrapper
from settings import TAX_ACCOUNTS, INCOME_DIST_ACCOUNTS, PAYABLE_ACCOUNTS, \
                     RECEIVABLE_ACCOUNTS
from datetime import date, datetime, timedelta

def add_party_acc(account_entry):
    account = account_entry['account']
    if isinstance(account, str):
        return account_entry
    else:
        account_entry['party_type'] = account['party_type']
        account_entry['party'] = account['party']
        account_entry['account'] = account['account']
        return account_entry

def add_party(account_entries):
    return [add_party_acc(account_entry) for account_entry in account_entries]

def journal_entry(company,account,against_account,debit,credit,title,
                  remark,date,cheque_no=None):
    account_entries = [{'account': account,
         'cost_center': company.cost_center,
         'debit': debit,
         'debit_in_account_currency': debit,
         'credit': credit,
         'credit_in_account_currency': credit },
        {'account': against_account,
         'cost_center': company.cost_center,
         'debit': credit,
         'debit_in_account_currency': credit,
         'credit': debit,
         'credit_in_account_currency': debit}]
    account_entries = add_party(account_entries)
    entry = {'doctype' : 'Journal Entry',
             'title': title,
             'voucher_type': 'Journal Entry',
             'company': company.name,
             'finance_book' : company.default_finance_book,
             'posting_date': date,
             'user_remark': remark,
             'accounts':account_entries}
    if cheque_no:
        entry['cheque_no'] = cheque_no
        entry['cheque_date'] = date
    #print(entry)
    j = gui_api_wrapper(Api.api.insert,entry)
    print("Buchungssatz {} erstellt".format(j['name']))
    return j

def journal_entry3(company,account,against_account1,against_account2,amount1,amount2,title,remark,date,cheque_no=None):
    if amount1 < 0:
        debit = 0
        credit = -amount1-amount2
        debit1 = -amount1
        credit1 = 0
        debit2 = -amount2
        credit2 = 0
    else:
        debit = amount1+amount2
        credit = 0
        debit1 = 0
        credit1 = amount1
        debit2 = 0
        credit2 = amount2
    account_entries = [{'account': account,
         'cost_center': company.cost_center,
         'debit': debit,
         'debit_in_account_currency': debit,
         'credit': credit,
         'credit_in_account_currency': credit},
        {'account': against_account1,
         'cost_center': company.cost_center,
         'debit': debit1,
         'debit_in_account_currency': debit1,
         'credit': credit1,
         'credit_in_account_currency': credit1},
        {'account': against_account2,
         'cost_center': company.cost_center,
         'debit': debit2,
         'debit_in_account_currency': debit2,
         'credit': credit2,
         'credit_in_account_currency': credit2}]
    account_entries = add_party(account_entries)
    entry = {'doctype' : 'Journal Entry',
             'title': title,
             'voucher_type': 'Journal Entry',
             'company': company.name,
             'finance_book' : company.default_finance_book,
             'posting_date': date,
             'user_remark': remark,
             'accounts':account_entries}
    if cheque_no:
        entry['cheque_no'] = cheque_no
        entry['cheque_date'] = date
    #print(entry)
    j = gui_api_wrapper(Api.api.insert,entry)
    print("Buchungssatz {} erstellt".format(j['name']))
    return j

def get_gl(company_name,start_date,end_date,account):
    filters={'company' : company_name,
             'account' : [account],
             'from_date' : start_date,
             'to_date' : end_date,
             'group_by':'Group by Voucher (Consolidated)'}
    report = gui_api_wrapper(Api.api.query_report,
                             report_name='General ledger',
                             filters=filters)
    return report['result']

def get_gl_total(company_name,start_date,end_date,account):
    gl = get_gl(company_name,start_date,end_date,account)
    total = [gle for gle in gl if gle['account'] == "'Total'"]
    return total[0]['balance']

def create_tax_journal_entries(company_name,quarter):
    if not company_name in TAX_ACCOUNTS:
        print("Keine Steuerkonten für {} bekannt".format(company_name))
        return
    tax_accounts = TAX_ACCOUNTS[company_name]
    this_company = company.Company.companies_by_name[company_name]
    base_title = 'USt-Anmeldung {}'.format(quarter)
    tax_pay_account = tax_accounts['tax_pay_account']
    start_date,end_date = utils.quarter_to_dates(quarter)
    for pre_tax_account in tax_accounts['pre_tax_accounts']:
        pre_tax = get_gl_total(company_name,start_date,end_date,pre_tax_account)
        if abs(pre_tax)>1e-06:
            journal_entry(this_company,tax_pay_account,pre_tax_account,
                          pre_tax,0,base_title+" Vorsteuer","",end_date)
        else:
            print("Keine Vorsteuer zu buchen")
    for tax_account in tax_accounts['tax_accounts']:
        tax = -get_gl_total(company_name,start_date,end_date,tax_account)
        if abs(tax)>1e-06:
            journal_entry(this_company,tax_account,tax_pay_account,tax,0,
                          base_title+" Verkaufssteuer","",end_date)
        else:
            print("Keine Umsatzsteuer zu buchen")

def create_income_dist_journal_entries(company_name,quarter):
    if not company_name in INCOME_DIST_ACCOUNTS:
        print("Keine Umverteilungskonten für {} bekannt".format(company_name))
        return
    this_company = company.Company.companies_by_name[company_name]
    start_date,end_date = utils.quarter_to_dates(quarter)
    def get_gl_total_acc(account):
        return get_gl_total(company_name,start_date,end_date,account)
    dist_accounts = INCOME_DIST_ACCOUNTS[company_name]
    expense_accs = dist_accounts['expense']
    income_accs = dist_accounts['income']
    tax_accs = dist_accounts['tax']
    expenses = {tax: get_gl_total_acc(acc) for tax, acc in expense_accs.items()}
    total_expenses = sum(expenses.values())
    rel_expenses = {tax: exp/total_expenses for tax, exp in expenses.items()}
    base_title = 'Aufteilung nach Steuersätzen {}'.format(quarter)
    descr = "Relative Aufteilung nach Steuersätzen der Ausgaben\n"
    for tax, rel_exp in rel_expenses.items():
      descr += "{}% USt: {:.4f}% Anteil\n".format(tax,rel_exp*100)
    print(descr)
    for accs in income_accs:
        unclear = -get_gl_total_acc(accs['unclear'])
        for tax, rel_exp in rel_expenses.items():
            if abs(unclear)>1e-06:
                net_amount = round(rel_exp*unclear/(1+tax/100),2)
                tax_amount = round(rel_exp*unclear-net_amount,2)
                journal_entry(this_company,accs['unclear'],accs[tax],
                              net_amount,0,
                              base_title,descr,end_date)
                journal_entry(this_company,accs['unclear'],tax_accs[tax],
                              tax_amount,0,
                              base_title,descr,end_date)

def create_advance_payment_journal_entry(payment_entry,tax_rate,revert=False):
    print("Erstelle Umbuchungssatz für {}".format(payment_entry))
    pe = Api.api.get_doc('Payment Entry',payment_entry)
    amount = pe['paid_amount']
    company_name = pe['company']
    this_company = company.Company.companies_by_name[company_name]
    party_type = pe['party_type']
    party = pe['party']
    tax_amount = round(amount/100.0*tax_rate,2)
    net_amount = amount - tax_amount
    if pe['payment_type'] == 'Receive':
        tax_ind = 'tax_accounts'
        accs = RECEIVABLE_ACCOUNTS
        book_from = 'Forderung'
        book_to = 'Verbindlichkeit'
    else:
        tax_ind = 'pre_tax_accounts'
        accs = PAYABLE_ACCOUNTS
        book_from = 'Verbindlichkeit'
        book_to = 'Forderung'
        net_amount = -net_amount
        tax_amount = -tax_amount
    tax_account = TAX_ACCOUNTS[company_name][tax_ind][0]
                                           #fixme: choose the right one
    payable_advance = accs[company_name]['advance']
    payable_post = accs[company_name]['post']
    if revert:
        net_amount = -net_amount
        tax_amount = -tax_amount
        title = "Rückbuchung Anzahlung {}".format(payment_entry)
        remark = "Rückbuchung der Anzahlung {} von {} und Steuern auf {}.".format(payment_entry,book_to,book_from)
        try:
            inv = pe['references'][0]['reference_name']
            doctype = pe['references'][0]['reference_doctype']
            inv = Api.api.get_doc(doctype,inv)
            date = inv['posting_date']
        except Exception:
            print("Keine zugehörige Rechnung für Zahlung {} gefunden".format(payment_entry))
            return
    else:
        date = pe['posting_date']
        title = "Umbuchung Anzahlung {}".format(payment_entry)
        remark = "Umbuchung der Anzahlung {} von negativer {} auf {} und Steuern. Muss später bei Zahlung der Rechnung wieder zurückgebucht werden.".format(payment_entry,book_from,book_to)
    account1 = {'account':payable_post,'party_type':party_type,'party':party}
    account2 = {'account':payable_advance,'party_type':party_type,'party':party}
    jes = Api.api.get_list('Journal Entry',
                           filters={'cheque_no':payment_entry,
                                    'cheque_date':date})
    if jes:
        print("Buchungssatz {} existiert schon".format(jes[0]['name']))
    else:
        journal_entry3(this_company,account1,account2,tax_account,
                       net_amount,tax_amount,title,remark,date,
                       payment_entry)
