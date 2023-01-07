import company
from api import Api
from api_wrapper import gui_api_wrapper
from settings import TAX_ACCOUNTS
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

def journal_entry(company,account,against_account,debit,credit,title,remark,date):
    accounts = [{'account': account,
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
    entry = {'doctype' : 'Journal Entry',
             'title': title,
             'voucher_type': 'Journal Entry',
             'company': company.name,
             'finance_book' : company.default_finance_book,
             'posting_date': date,
             'user_remark': remark,
             'accounts':accounts}
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
    year,q = quarter.split("-")
    d = date(int(year),int(q)*3-2,1)
    start_date = d.strftime('%Y-%m-%d')
    d += relativedelta(months=3) - relativedelta(days=1)
    end_date = d.strftime('%Y-%m-%d')
    this_company = company.Company.companies_by_name[company_name]
    base_title = 'USt-Anmeldung {}'.format(quarter)
    tax_pay_account = tax_accounts['tax_pay_account']
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
