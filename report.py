from api import Api
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, PageBreak, Preformatted, Spacer, Paragraph
from reportlab.rl_config import defaultPageSize
from reportlab.lib.units import inch
PAGE_HEIGHT=defaultPageSize[1]
PAGE_WIDTH=defaultPageSize[0]

def format_float(n):
    return "{:,}".format(round(n)).replace(",",".") 

def format_row(r,col_fields):
    account = r['account_name']
    if account == "'Total Asset (Debit)'":
        account = "Summe Vermögenswerte (Aktiva)"
    elif account == "'Total Liability (Credit)'":
        account = "Teilsumme Vermögensquellen (Passiva)"
    elif account in ["'Provisional Profit / Loss (Credit)'","'Profit for the year'"]:
        account = "Überschuss/Defizit"
    elif account == "'Total (Credit)'":
        account = "Summe Vermögensquellen (Passiva)"
    elif account == "'Total Income (Credit)'":
        account = "Summe Einnahmen"
    elif account == "'Total Expense (Debit)'":
        account = "Summe Ausgaben"
    if 'indent' in r:
        account = "   "*round(r['indent'])+account
    return [account[0:39]]+[format_float(r[c]) for c in col_fields]

def remove_dup(columns,report):
    for i in range(len(columns)):
        for j in range(i+1,len(columns)):
            coli = columns[i]['fieldname'] 
            colj = columns[j]['fieldname'] 
            if all([r[coli]==r[colj] for r in report['result'] if ('account_name' in r)]):
                return columns[j]
    return None

def format_report(company,report_type):
    report = Api.api.query_report(report_name="Consolidated Financial Statement",
                                  filters={'company' : company,
                                           'period_start_date' : '2021-01-01',
                                           'period_end_date' : '2021-06-05',
                                           'accumulated_in_group_company' : True,
                                           'report' : report_type})
    if report_type == 'Profit and Loss Statement':
        report_msg = 'Einnahmen/Ausgaben'
    else:
        report_msg = 'Bilanz'
    columns = [col for col in report['columns'] if not col['fieldname'] in ['account','currency']]
    # remove all zero columns
    for col in columns:
        if not any([r[col['fieldname']] for r in report['result'] if col['fieldname'] in r]):
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
    report_data = [r for r in report['result'] if ('account_name' in r) and sum(round(r[c]) for c in col_fields)]
    data = [format_row(r,col_fields) for r in report_data]            
    grid = [('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
            ('BOX', (0,0), (-1,-1), 0.25, colors.black),
            ('ALIGN',(1,0),(-1,-1),'RIGHT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold')]
    for i in range(len(report_data)):
        r = report_data[i]
        if not 'indent' in r:
            grid.append(('FONTNAME', (0,i+1), (-1,i+1), 'Helvetica-Bold'))
        elif r['indent'] == 1:
            grid.append(('FONTNAME', (0,i+1), (-1,i+1), 'Helvetica-Oblique'))
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

def build_pdf(company,filename):
    title = "Abrechnung "+company
    doc = SimpleDocTemplate(filename)
    ## container for the 'Flowable' objects
    elements = []
    elements.append(Spacer(1,0.8*inch))
    elements.append(format_report(company,'Profit and Loss Statement'))
    elements.append(PageBreak())
    elements.append(format_report(company,'Balance Sheet'))
    ## write the document to disk
    doc.build(elements,onFirstPage=myFirstPage(title), onLaterPages=myLaterPages)


