from api import Api, LIMIT
import purchase_invoice

def process(company_name):
    prs = Api.api.get_list("PreRechnung",filters={'company':company_name,
                                                  'processed':False},
                           limit_page_length=LIMIT) 
    for pr in prs:
        print(pr['name'])
        inv = purchase_invoice.PurchaseInvoice(pr['lager'])
        pdf = pr['pdf']
        contents = Api.api.get_file(pdf)
        tmpfile = "/tmp/r.pdf"
        with open(tmpfile,"wb") as f:
            f.write(contents)
        try:    
            inv.parse_invoice(tmpfile,account=pr['buchungskonto'],
                                paid_by_submitter=pr['selbst_bezahlt'],
                                given_supplier=pr['lieferant'],
                                is_test=True)
        except:
            pass
        try:
            vat = sum(map(int,inv.vat.values()))
        except:
            vat = 0
        if not inv.gross_total:
            inv.gross_total = inv.total+vat    
        print("{} {} {}".format(pr['name'],inv.gross_total,inv.order_id))
        if inv.gross_total:
            pr['betrag'] = inv.gross_total
        if inv.order_id:
            pr['auftragsnr'] = inv.order_id
        pr['processed'] = True
        pr['doctype'] = 'PreRechnung'       
        Api.api.update(pr)
    print("Prerechnungen vorprozessiert")

def to_pay(company_name):
    prs = Api.api.get_list("PreRechnung",filters={'company':company_name,
                                                  'vom_konto_überwiesen':False,
                                                  'zu_zahlen_am':['>','01-01-1980']},
                           limit_page_length=LIMIT)
    prs.sort(key=lambda pr : pr['zu_zahlen_am'])
    sum = 0.0
    for pr in prs:
        sum += pr['betrag']
        pr['summe'] = sum
    return prs
    
