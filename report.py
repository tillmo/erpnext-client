import company
from api import Api
import table
import utils
from datetime import datetime
from datetime import date
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, PageBreak, Preformatted, Spacer, Paragraph
from reportlab.rl_config import defaultPageSize
from reportlab.lib.units import inch
PAGE_HEIGHT=defaultPageSize[1]
PAGE_WIDTH=defaultPageSize[0]

def format_float(n):
    if type(n)==str:
        return n
    else:
        return "{:,}".format(round(n)).replace(",",".") 

def format_row(r,col_fields):
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
    return [account[0:39]]+[format_float(r[c]) for c in col_fields]

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

def format_report(company_name,report_type,start_date,end_date,
                  periodicity='Yearly',
                  consolidated=False):
    comp = company.Company.get_company(company_name)
    filters={'company' : company_name,
             'period_start_date' : start_date,
             'period_end_date' : end_date,
             #'include_default_book_entries' : True,
             'finance_book' : comp.default_finance_book,
             'accumulated_in_group_company' : True,
             'report' : report_type}
    if consolidated:
        report_name="Consolidated Financial Statement"
    else:                
        report_name=report_type
        filters['periodicity'] = periodicity
    report = Api.api.query_report(report_name=report_name,filters=filters)
    if report_type == 'Profit and Loss Statement':
        report_msg = 'Einnahmen/Ausgaben'
    else:
        report_msg = 'Bilanz'
    columns = [col for col in report['columns']\
               if not col['fieldname'] in ['account','currency']]
    # remove all zero columns
    for col in columns:
        if not any([r[col['fieldname']] for r in report['result']\
                    if col['fieldname'] in r]):
            columns.remove(col)
    # remove all duplicate columns
    col = remove_dup(columns,report)
    while col:
        columns.remove(col)
        col = remove_dup(columns,report)
    # build data        
    col_fields = [col['fieldname'] for col in columns]
    col_labels = [col['label'][0:10] for col in columns]
    header = [report_msg] + col_labels
    report_data = [r for r in report['result']\
                   if ('account_name' in r) and\
                      is_relevant(r,col_fields)]
    data = [format_row(r,col_fields) for r in report_data]            
    grid = [('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
            ('BOX', (0,0), (-1,-1), 0.25, colors.black),
            ('ALIGN',(1,0),(-1,-1),'RIGHT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold')]
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
        r = report_data[i]
        if not 'indent' in r:
            grid.append(('FONTNAME',(0,i+1),(-1,i+1),'Helvetica-Bold'))
        elif r['indent'] == 1:
            grid.append(('FONTNAME',(0,i+1),(-1,i+1),'Helvetica-BoldOblique'))
        elif r['indent'] >= 2:
            grid.append(('FONTNAME',(0,i+1),(-1,i+1),'Helvetica-Oblique'))
    t=Table([header]+data)
    t.setStyle(TableStyle(grid))
    return t

def myFirstPage(title):
    def myPage(canvas, doc):
        canvas.saveState()
        canvas.setTitle(title)
        canvas.setFont('Helvetica-Bold',16)
        canvas.drawCentredString(PAGE_WIDTH/2.0, PAGE_HEIGHT-108, title)
        canvas.setFont('Helvetica',9)
        canvas.drawString(PAGE_WIDTH/2.0, 0.75 * inch, " %d " % doc.page)
        canvas.restoreState()
    return myPage    

def myLaterPages(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica',9)
    canvas.drawString(PAGE_WIDTH/2.0, 0.75 * inch, " %d " % doc.page)
    canvas.restoreState()

def build_pdf(company_name,filename="",consolidated=False,
              periodicity='Yearly'):
    title = "Abrechnung "+company_name
    ## dates
    start_date = date(datetime.today().year, 1, 1)
    end_date = datetime.today()
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')
    title += "  "+start_date.strftime('%d.%m.%Y')+\
             " - "+end_date.strftime('%d.%m.%Y')
    if not filename:
        filename = "Abrechnung_"+company_name.replace(" ","_")+\
                   "_"+start_date_str+".pdf"
    doc = SimpleDocTemplate(filename)
    ## container for the 'Flowable' objects
    elements = []
    elements.append(Spacer(1,0.8*inch))
    elements.append(format_report(company_name,'Profit and Loss Statement',
                                  start_date_str,end_date_str,
                                  periodicity=periodicity,
                                  consolidated=consolidated))
    #elements.append(PageBreak())
    elements.append(Spacer(1,0.8*inch))
    elements.append(format_report(company_name,'Balance Sheet',
                                  start_date_str,end_date_str,
                                  periodicity='Yearly',
                                  consolidated=consolidated))
    ## write the document to disk
    doc.build(elements,
              onFirstPage=myFirstPage(title),
              onLaterPages=myLaterPages)
    return filename

