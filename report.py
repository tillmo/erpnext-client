import company
from api import Api, LIMIT
from api_wrapper import gui_api_wrapper
import table
import utils
from datetime import datetime
from datetime import date
from anytree import Node, RenderTree, PostOrderIter
from collections import defaultdict
import PySimpleGUI as sg
import plotly.express as px

def get_dates():
    year = sg.UserSettings()['-year-'] 
    start_date = date(year, 1, 1)
    if year == datetime.today().year:
        end_date = datetime.today()
    else:    
        end_date = date(year, 12, 31)
    return(start_date,end_date)

def format_float(n):
    if type(n)==str:
        return n
    else:
        return "{:,}".format(round(n)).replace(",",".") 

def format_account(r):
    account = r['account_name']
    account = account.replace("'","")
    if account in ['Total Asset (Debit)','Aktiva']:
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
    if r['account_name'] in ['Total Asset (Debit)','Total Liability (Credit)']:
        return False
    for c in col_fields:
        el = r[c]
        if type(el) == str:
            if el:
                return True
        else:
            if round(el):
                return True
    return not ('indent' in r) or r['indent'] == 0

def build_trees(data,ix,indent,parent=None):
    tr_list = []
    l = len(data)
    while ix<l:
        r = data[ix]
        r_indent = int(r['indent']) if 'indent' in r else 0
        if r_indent<indent:
            return (ix,tr_list)
        tr = Node(r['account_name'].strip(),data=r,parent=parent)
        ix += 1
        (ix,trs) = build_trees(data,ix,r_indent+1,tr)
        tr_list.append(tr)
    return (ix,tr_list)

def build_tree(data):
    tr = Node("root")
    _,trs = build_trees(data,0,0,tr)
    return tr


def build_sums(tr,cols):
    for t in tr.children:
        build_sums(t,cols)
    if not tr.is_leaf and not tr.name=="root":
        for c in cols:
            tr.data[c] = sum([t.data[c] for t in tr.children])
        
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
    start_date,end_date = get_dates()
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')
    print(start_date_str,end_date_str)
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
    if balance:
        col_fields.append('total')
        col_labels.append('Total')
    header = [subtitle] + col_labels
    report_data = [format_account(r) for r in report['result']\
                   if ('account_name' in r) and\
                      is_relevant(r,col_fields)]
    # using indentation, organise list of records into list of trees
    tr = build_tree(report_data)
    # print tree
    #for pre, fill, node in RenderTree(tr):
    #     print("%s%s" % (pre, node.name))
    # avoid negative entries in balance
    swap_accounts = {'1400':'Anzahlungen Verkauf','1600':'Anzahlungen Einkauf'}
    swap_account_list = list(swap_accounts.keys())
    swap_data = {}
    if balance:
        for node in PostOrderIter(tr):
            if node.name[0:4] in swap_account_list and node.data['total'] < 0:
                for c in col_fields:
                    swap_data[(node.name[0:4],c)] = -node.data[c]
                    node.data[c] = 0
        for node in PostOrderIter(tr):
            if node.name[0:4] in swap_account_list:
                acc_no = node.name[0:4]
                accs = swap_account_list.copy()
                accs.remove(acc_no)
                s_acc_no = accs[0]
                for c in col_fields:
                    if (s_acc_no,c) in swap_data:
                        node.data['account_name'] = "   "*round(node.data['indent'])+swap_accounts[s_acc_no]
                        node.data[c] = swap_data[(s_acc_no,c)]
        build_sums(tr,col_fields)        
        p_sum = defaultdict(lambda: 0)
        for node in PostOrderIter(tr):
            if node.name!='root':
                if node.data['account_name'] in ['Passiva','Überschuss/Defizit']:
                    for c in col_fields:
                        p_sum[c] += node.data[c]
                elif node.data['account_name'] == 'Summe Vermögensquellen (Passiva)':
                    for c in col_fields:
                        node.data[c] = p_sum[c]
    # formant non-leaf nodes according to indent
    r_data = []
    for node in PostOrderIter(tr):
        if node.name != "root":
            r = node.data
            if not node.is_leaf:
                if (not 'indent' in r) or r['indent'] == 0:
                    r['bold'] = 3
                elif r['indent'] == 1:
                    r['bold'] = 2
                elif r['indent'] >= 2:
                    r['bold'] = 1
            r_data.append(r)
    return table.Table(r_data,['account_name']+col_fields,header,title,
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
             'account' : [account],
             'from_date' : start_date_str,
             'to_date' : end_date_str}
    report = gui_api_wrapper(Api.api.query_report,
                             report_name='General ledger',
                             filters=filters)
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


def format_opp(opp):
    for field in ['nur_balkonmodul', 'selbstbau', 'mit_speicher',
                  'oksolarteure','anmeldung_eingereicht',
                  'anmeldung_bewilligt',
                  'is_paid','kostenvoranschlag', 'selbstbauset',
                  'elektriker', 'ballastierung']: #,
                  #'angebot_1_liegt_vor', 'angebot_2_liegt_vor',
                  #'bauzeichnung_liegt_vor',
                  #'auszug_solarkataster_liegt_vor','belegungsplan_liegt_vor',
                  #'statik_liegt_vor','artikelliste_liegt_vor',
                  #'verschattungsanalyse_liegt_vor',
                  #'eigenverbrauchsanalyse_liegt_vor']:
       if field in opp:
           if opp[field]:
               opp[field] = "✓"
           else:
               opp[field] = " "
    for field in ['global_margin', 'soliaufschlag']:
       if field in opp:
           if not opp[field]:
               opp[field] = ""
    for field, value in opp.items():
        if value is None:
            opp[field] = ""
        if type(value)==str:    
            opp[field] = opp[field].strip()
            opp[field] = opp[field][0:23]
    return opp

def opportunities_data(company_name,balkon=False):
    opps = {}
    if balkon:
        for si in gui_api_wrapper(Api.api.get_list,'Sales Invoice',filters={'company':company_name,'balkonmodul':balkon,'status': ['!=','Cancelled']},limit_page_length=LIMIT):
            si['transaction_date'] = si['posting_date']
            opp = si
            opp['sales_invoice'] = si['name']
            if si['status'] != "Draft":
                opp['sales_invoice'] += "*"
            opp['is_paid'] = si['status'] == 'Paid'
            opps[si['name']] = opp
        return opps
    for opp in gui_api_wrapper(Api.api.get_list,'Opportunity',filters={'company':company_name,'status': ['!=','Cancelled'], 'nur_balkonmodul':balkon},limit_page_length=LIMIT):
        opps[opp['name']] = opp
    quots = {}
    for quot in gui_api_wrapper(Api.api.get_list,'Quotation',filters={'company':company_name,'status': ['not in',['Cancelled','Expired']]},limit_page_length=LIMIT):
        if quot['opportunity']:
            if quot['opportunity'] in opps:
                opp = quot['opportunity']
                opps[opp]['quotation'] = quot['name']
                opps[opp]['global_margin'] = quot['global_margin']
                opps[opp]['soliaufschlag'] = quot['soliaufschlag']
                opps[opp]['kostenvoranschlag'] = quot['kostenvoranschlag']
                opps[opp]['elektriker'] = quot['elektriker']
                opps[opp]['ballastierung'] = quot['ballastierung']
        else:
            quot['title'] += "?A"
            quot['quotation'] = quot['name']
            opps[quot['name']] = quot
        quots[quot['name']] = quot
    sos = {}    
    for so in gui_api_wrapper(Api.api.get_list,'Sales Order',filters={'company':company_name,'status': ['!=','Cancelled']},fields=["`tabSales Order Item`.prevdoc_docname as quotation","name","status","title","customer_name","transaction_date"],limit_page_length=LIMIT):
        quot_name = so["quotation"]
        if quot_name:
            if quot_name in quots:
                quot = quots[quot_name]
                quot['sales_order'] = so['name']
                quots[quot_name] = quot
                opp_name = quot['opportunity']
                if opp_name and opp_name in opps:
                    opp = opps[opp_name]
                    if opp:
                        opp['sales_order'] = so['name']
                        if so['status'] != "Draft":
                            opp['sales_order'] += "*"
                        opps[opp_name] = opp
                        sos[so['name']] = so
        else:
            if so['title']=='{customer_name}':
                so['title']=so['customer_name']
            so['title'] += "?AB"
            so['sales_order'] = so['name']
            opps[so['name']] = so
            sos[so['name']] = so
    sis = {}
    for si in gui_api_wrapper(Api.api.get_list,'Sales Invoice',filters={'company':company_name,'balkonmodul':balkon,'status': ['!=','Cancelled']},fields=["`tabSales Invoice Item`.sales_order as item_sales_order","name","status","title","posting_date"],limit_page_length=LIMIT):
        if 'item_sales_order' in si:    
            so_name = si['item_sales_order']
        else:    
            so_name = None
        if so_name:
            if so_name in sos:
                sos[so_name]['sales_invoice'] = si['name']
                so = sos[so_name]
                if so:
                    quot_name = so['quotation']
                    if quot_name:
                        quot = quots[quot_name]
                        if quot:
                            opp_name = quot['opportunity']
                            if opp_name:
                                opp = opps[opp_name]
                                if opp:
                                    opp['sales_invoice'] = si['name']
                                    if si['status'] != "Draft":
                                        opp['sales_invoice'] += "*"
                                    opp['is_paid'] = si['status'] == 'Paid'
                                    opps[opp_name] = opp
        else:
            si['title'] += "?R"
            si['sales_invoice'] = si['name']
            si['transaction_date'] = si['posting_date']
            opps[si['name']] = si
        sis[si['name']] = si
    return opps

def opportunities(company_name,balkon=False):
    opps = opportunities_data(company_name,balkon)
    opps = [format_opp(opp) for opp in opps.values()]
    opps.sort(key=lambda x: x['transaction_date'],reverse=True)
    columns = ['title', 'transaction_date','soliaufschlag']
    if not balkon:
        columns += ['selbstbau', 'selbstbauset',
                    'mit_speicher', 'kostenvoranschlag',
                    'elektriker', 'ballastierung',
                    'quotation', 'sales_order',
                    'anzahlung','oksolarteure','anmeldung_eingereicht',
                    'anmeldung_bewilligt', 'auftragsnummer_lieferant',
                    'lieferant_bezahlt', 'liefertermin_material', 'bautermin']
    columns += ['sales_invoice','is_paid']
                #'global_margin',
                #'angebot_1_liegt_vor', 'angebot_2_liegt_vor',
                #'bauzeichnung_liegt_vor',
                #'auszug_solarkataster_liegt_vor','belegungsplan_liegt_vor',
                #'statik_liegt_vor','artikelliste_liegt_vor',
                #'verschattungsanalyse_liegt_vor',
                #'eigenverbrauchsanalyse_liegt_vor']
    headings = ['Titel','Datum','Soli']
    if not balkon:
        headings += ['Selbst','Set','Speich','KV','Elektr.',
                     'Ball.', 'Angebot',
                     'Auftragsbest.','Anzahlung','OK Sol.',
                     'Anm. eing.', 'Anm. bew.',
                     'Auftragsnr.','bez.', 'Liefertermin', 'Bautermin']
    headings += ['Rechnung','bez.']
                 #'Marge',
                 #'Angebot1', 'Angebot2', 
                 #'Bauzeichnung','Kataster','Belegungsplan',
                 # 'Statik', 'Artikelliste','Verschattung','Eigen']
    return table.Table(opps,columns,headings,'Chancen für '+company_name)
    
def projects():
    projects = []
    for p in Api.api.get_list("Project",
                    fields=["name","project_name","creation","status",'project_type'],
                              limit_page_length=LIMIT,
                              order_by='status DESC, creation DESC'):
        pname = p['name']
        ptitle = p['project_name']
        pdate = p['creation']
        typ = p['project_type'] if 'project_type' in p else ''
        sis = Api.api.get_list('Sales Invoice',
                    filters={'project':pname,'status': ['!=','Cancelled']},
                    fields=['total'],limit_page_length=LIMIT)
        pis = Api.api.get_list('Purchase Invoice',
                    filters={'project':pname,'status': ['!=','Cancelled']},
                    fields=['total'],limit_page_length=LIMIT)
        ssum = sum([si['total'] for si in sis])
        psum = sum([pi['total'] for pi in pis])
        projects.append({'Name':pname,'Datum':pdate,'Titel':ptitle,'Typ':typ,'Status':p['status'],'Einkauf':psum,'Verkauf':ssum,'Marge':ssum-psum})
    columns = ['Name','Titel','Typ','Einkauf','Verkauf','Marge','Status']
    return table.Table(projects,columns,columns,'Projekte',just='right',enable_events=True)

def adapt(e,factor):
    e['balance'] *= factor
    return e

def set_title(e,title):
    e['Bilanzposten'] = title
    return e

def balance(company,accounts,factor,start_date_str,end_date_str):
    r = Api.api.query_report(report_name="General ledger",filters={'company':company,'from_date' : start_date_str, 'to_date' : end_date_str,'report':"General ledger", 'account':accounts, 'group_by':'Group by Voucher (Consolidated)'})
    r = r['result']
    r[0]['posting_date'] = start_date_str
    r[-1]['posting_date'] = end_date_str
    r = [adapt(e,factor) for e in r if 'account' in e and 'posting_date' in e and e['account']!="'Total'"]
    return r

def balances(company,account_areas):
    start_date,end_date = get_dates()
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')
    report = []
    for title,entry in account_areas.items():
        accs,factor = entry
        r = balance(company,accs,factor,start_date_str,end_date_str)
        r = [set_title(e,title) for e in r]
        report += r
    fig = px.line(report, x="posting_date", y="balance", title=company+' - wichtigste Bilanzposten', color='Bilanzposten',line_shape='hv')
    fig.show()    


def sold_items(project):
    items = defaultdict(float)
    sinvs = Api.api.get_list("Sales Invoice",
                             filters={'project' : project,
                                      'status': ['!=','Cancelled']},
                             limit_page_length=LIMIT)
    for sinv in sinvs:
        inv = Api.api.get_doc("Sales Invoice",sinv['name'])
        for item in inv['items']:
            items[item['item_code']] += int(item['qty'])
    full_items = []
    for item_code,qty in items.items():
        # needed because item_name can have changed
        full_item = Api.api.get_doc("Item",item_code)
        full_items.append({'item_name':full_item['item_name'],
                           'item_code':full_item['item_code'],
                           'qty':qty})
    return full_items
