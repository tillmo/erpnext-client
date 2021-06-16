import company
from api import Api, LIMIT
from api_wrapper import gui_api_wrapper
import table
import utils
from datetime import datetime
from datetime import date

def format_float(n):
    if type(n)==str:
        return n
    else:
        return "{:,}".format(round(n)).replace(",",".") 

def format_account(r):
    account = r['account_name']
    account = account.replace("'","")
    if account == 'Total Asset (Debit)':
        account = 'Summe Vermögenswerte (Aktiva)'
    elif account == 'Total Liability (Credit)':
        account = 'Teilsumme Vermögensquellen (Passiva)'
    elif account in ['Provisional Profit / Loss (Credit)',
                     'Profit for the year']:
        account = 'Überschuss/Defizit'
    elif account == 'Total (Credit)':
        account = 'Summe Vermögensquellen (Passiva)'
    elif account == 'Total Income (Credit)':
        account = 'Summe Einnahmen'
    elif account == 'Total Expense (Debit)':
        account = 'Summe Ausgaben'
    elif account == 'Unclosed Fiscal Years Profit / Loss (Credit)':
        account = 'Gewinn-/Verlustvortrag'
    if 'indent' in r:
        account = "   "*round(r['indent'])+account
    r['account_name'] = account[0:39]    
    return r     
    #return [account[0:39]]+[format_float(r[c]) for c in col_fields]

def remove_dup(columns,report):
    for i in range(len(columns)):
        for j in range(i+1,len(columns)):
            coli = columns[i]['fieldname'] 
            colj = columns[j]['fieldname'] 
            if all([r[coli]==r[colj] for r in report['result']\
                    if ('account_name' in r)]):
                return columns[j]
    return None

def is_relevant(r,col_fields):
    for c in col_fields:
        el = r[c]
        if type(el) == str:
            if el:
                return True
        else:
            if round(el):
                return True
    return False

def build_report(company_name,filename="",consolidated=False,balance=False,
                 periodicity='Yearly'):
    if not periodicity:
        periodicity = 'Yearly'
    if periodicity=='Monthly':
        title = "Monatsabrechnung"
    elif periodicity=='Quarterly':
        title = "Quartalsabrechnung"
    else:
        title = "Abrechnung"
    if balance:
        title = "Bilanz"
        report_type = 'Balance Sheet'
    else:    
        report_type = 'Profit and Loss Statement'
    title += " "+company_name    
    ## dates
    start_date = date(datetime.today().year-1, 1, 1)
    end_date = datetime.today()
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')
    if not filename:
        filename = title.replace(" ","_")+\
                   "_"+start_date_str+".pdf"
    title += "  "+start_date.strftime('%d.%m.%Y')+\
             " - "+end_date.strftime('%d.%m.%Y')
    comp = company.Company.get_company(company_name)
    filters={'company' : company_name,
             'period_start_date' : start_date_str,
             'period_end_date' : end_date_str,
             #'include_default_book_entries' : True,
             'finance_book' : comp.default_finance_book,
             'accumulated_in_group_company' : True,
             'report' : report_type}
    if consolidated:
        report_name="Consolidated Financial Statement"
    else:                
        report_name=report_type
        filters['periodicity'] = periodicity
    report = gui_api_wrapper(Api.api.query_report,report_name=report_name,
                             filters=filters)
    if report_type == 'Profit and Loss Statement':
        subtitle = 'Einnahmen/Ausgaben'
    else:
        subtitle = 'Bilanz'
    columns = [col for col in report['columns']\
               if not col['fieldname'] in ['account','currency']]
    # remove all zero columns
    columns1 = []
    for col in columns:
        if any([r[col['fieldname']] for r in report['result']\
                    if col['fieldname'] in r]):
            columns1.append(col)
    columns = columns1        
    # if consolidated, remove all duplicate columns (=companies)
    if consolidated:
        col = remove_dup(columns,report)
        while col:
            columns.remove(col)
            col = remove_dup(columns,report)
    # build data        
    col_fields = [col['fieldname'] for col in columns]
    col_labels = [col['label'][0:10] for col in columns]
    header = [subtitle] + col_labels
    report_data = [format_account(r) for r in report['result']\
                   if ('account_name' in r) and\
                      is_relevant(r,col_fields)]
    leaves = []
    tentative_leaves = []
    old_indent = 0
    for i in range(len(report_data)):
        r = report_data[i]
        if not 'indent' in r:
            cur_indent = 0
        else:
            cur_indent = round(r['indent'])
        if cur_indent > old_indent:
            tentative_leaves = [i]
        elif cur_indent == old_indent:    
            tentative_leaves.append(i)
        else:    
            leaves += tentative_leaves.copy()
            tentative_leaves = []
        old_indent = cur_indent
    for i in range(len(report_data)):
        if i in leaves:
            continue
        if not 'indent' in r:
            report_data[i]['bold'] = 3
        elif r['indent'] == 1:
            report_data[i]['bold'] = 2
        elif r['indent'] >= 2:
            report_data[i]['bold'] = 1
    return table.Table(report_data,['account_name']+col_fields,header,title,
                       filename=filename,enable_events=True)

def format_GL(r):
    if 'remarks' in r:
        if r['remarks'] in ['Keine Anmerkungen','No Remarks']:
            r['remarks'] = ''
    if r['account'] == "'Opening'":
        r['account'] = 'Eröffnung'
        r['bold'] = 3
    elif r['account'] == "'Total'":
        r['account'] = 'Total'
        r['bold'] = 3
    elif r['account'] == "'Closing (Opening + Total)'":
        r['account'] = 'Abschluss (Eröffnung + Total)'
        r['bold'] = 3
    return r

def is_relevat_GL(r):
    if not ('debit' in r and 'credit' in r and 'balance' in r):
        return False
    #if not (r['debit'] or r['credit'] or r['balance']):
    #    return False
    return True

def keep_first(data,accounts):
    data1 = []
    found = False
    #print(r['account'])
    for r in data:
        if r['account'] in accounts:
            #print("found",found)
            if found:
                continue
            else:
                found = True
        data1.append(r)
    return data1  

def general_ledger(company_name,account):
    ## dates
    start_date = date(datetime.today().year, 1, 1)
    end_date = datetime.today()
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')
    filters={'company' : company_name,
             'account' : account,
             'from_date' : start_date_str,
             'to_date' : end_date_str}
    try:
        report = Api.api.query_report(report_name='General ledger',
                                      filters=filters)
    except Exception:
        return None
    columns = ['posting_date','account','debit','credit','balance','against',
               'remarks','voucher_no']
    headings = ['Datum','Konto','Soll','Haben','Stand','Gegenkonto',
                'Bemerkungen','Beleg']
    report_data = [r for r in report['result'] if is_relevat_GL(r)]
    report_data = keep_first(report_data,["'Opening'"])
    report_data.reverse()
    report_data = keep_first(report_data,["'Total'"])
    report_data = keep_first(report_data,["'Closing (Opening + Total)'"])
    report_data.reverse()
    report_data = [format_GL(r) for r in report_data]
    return table.Table(report_data,columns,headings,'Hauptbuch für '+account)

    
def opportunities(company_name):
    opps = gui_api_wrapper(Api.api.get_list,'Opportunity',limit_page_length=LIMIT)
    opps.sort(key=lambda x: x['transaction_date'],reverse=True)
    quots = gui_api_wrapper(Api.api.get_list,'Quotation',limit_page_length=LIMIT)
    sos = gui_api_wrapper(Api.api.get_list,'Sales Order',limit_page_length=LIMIT)
    for so in sos:
        so1 = Api.api.get_doc('Sales Order',so['name'])
        so['quotation'] = so1['items'][0]['prevdoc_docname']
    sis = gui_api_wrapper(Api.api.get_list,'Sales Invoice',limit_page_length=LIMIT)
    for si in sis:
        si1 = Api.api.get_doc('Sales Invoice',si['name'])
        item = si1['items'][0]
        if 'sales_order' in item:
            si['sales_order'] = item['sales_order']
        else:    
            si['sales_order'] = None
    for opp in opps:
        for quot in quots:
            if quot['opportunity'] == opp['name']:
                opp['quotation'] = quot['name']
                for so in sos:
                    if  so['quotation']== quot['name']:
                        opp['sales_order'] = so['name']
                        for si in sis:
                            if  si['sales_order']== so['name']:
                                opp['sales_invoice'] = si['name']
                                break
                        break
    columns = ['title', 'transaction_date', 'quotation', 'sales_order', 'sales_inovice', 'bauzeichnung_liegt_vor',
               'auszug_solarkataster_liegt_vor','belegungsplan_liegt_vor',
               'statik_liegt_vor','artikelliste_liegt_vor',
               'verschattungsanalyse_liegt_vor','eigenverbrauchsanalyse_liegt_vor']
    headings = ['Titel','Datum','Angebot', 'Auftragsbest.', 'Rechnung', 'Bauzeichnung','Kataster','Belegungsplan','Statik',
                'Artikelliste','Verschattung','Eigen']
    return table.Table(opps,columns,headings,'Chacen für '+company_name)
    
