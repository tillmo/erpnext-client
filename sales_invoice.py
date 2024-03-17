from api import Api, LIMIT
import utils
from collections import defaultdict
import os
import csv
from settings import EBAY_ACCOUNT
import invoice

def get_items(sinvs):
    Api.load_item_data()
    items = defaultdict(float)
    for sinv in sinvs:
        inv = Api.api.get_doc("Sales Invoice",sinv['name'])
        for item in inv['items']:
            items[item['item_code']] += int(item['qty'])
    full_items = []
    for item_code,qty in items.items():
        # needed because item_name can have changed
        full_item = Api.items_by_code[item_code]
        full_items.append({'item_name':full_item['item_name'],
                           'item_code':full_item['item_code'],
                           'qty':qty})
    return full_items

def get_sales_invoices(company_name,quarter,tax_rates=[]):
    print_format = Api.api.get_list('Print Format',
                                    filters={'doc_type': 'Sales Invoice'})[0]['name']
    start_date,end_date = utils.quarter_to_dates(quarter)
    suffix = "-{}-{}".format(company_name.replace(" ","_"),quarter)
    dir = "EK-Rechnungen"+suffix
    os.makedirs(dir,exist_ok=True)
    with open("{}/EK-Rechnungen{}.csv".format(dir,suffix), mode='w') as csv_file:
        writer = csv.writer(csv_file,delimiter=";")
        writer.writerow(["Datum","Rechnungsnr.","Steuersatz","Netto","USt."])
        tax_sum = 0
        net_sum = 0
        for sinv in Api.api.get_list("Sales Invoice",
                                     filters={'company':company_name,
                                              'posting_date':['between',[start_date,end_date]],
                                              'status': ['!=','Cancelled']},
                                     order_by='posting_date',
                                     limit_page_length=LIMIT):
            print(".",end="",flush=True)
            inv_name = sinv['name']
            #print(inv_name,sinv['posting_date'])
            pretty_inv_name = inv_name.replace(" ","_")
            tax_rate = sinv['taxes_and_charges'].split("%")[0].split()[-1]
            if not tax_rates or int(tax_rate) in tax_rates:
                tax = sinv['total_taxes_and_charges']
                total = sinv['total']
                date = sinv['posting_date']
                writer.writerow([date,pretty_inv_name,tax_rate,
                                 str(total).replace(".",","),
                                 str(tax).replace(".",",")])
                tax_sum += tax
                net_sum += total
                pdf = Api.api.get_pdf('Sales Invoice',inv_name,print_format)
                with open(dir + "/" + pretty_inv_name + ".pdf", 'wb') as f:
                    f.write(pdf.read())
        writer.writerow(["Summe","",str(tax_sum).replace(".",","),
                         str(net_sum).replace(".",",")])
        print()
    return dir    

def ebay_sales(company_name,submit=False):
    invs = Api.api.get_list("Sales Invoice",
                            filters={'company':company_name,
                                     'outstanding_amount':['>',2],
                                     'custom_ebay':1,
                                     'status': ['not in',['Cancelled','Paid','Draft']]},
                            fields=['name','total','status','company',
                                    'posting_date','grand_total',
                                    'outstanding_amount','customer'],
                            limit_page_length=LIMIT)
    for doc in invs:
        inv1 = invoice.Invoice(doc,True)
        pay = inv1.payment(EBAY_ACCOUNT,inv1.amount,inv1.date)
        if submit:
            pay1 = Api.api.get_doc('Payment Entry',pay['name'])
            pay1['doctype'] = 'Payment Entry'
            Api.api.submit(pay1)
    if not submit:
        print("Bitte noch buchen")
