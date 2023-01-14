from api import Api
from settings import PROJECT_WAREHOUSE, SOMIKO_ACCOUNTS, PROJECT_ITEM_GROUP, \
                     PROJECT_UNIT
from api_wrapper import gui_api_wrapper
import project

def stock_reconciliation_for_item(company_name,date,item_code,warehouse,
                                  qty,valuation_rate,account,pinv_name=None):
        item = {'item_code': item_code,
                'warehouse': warehouse,
                'qty': qty,
                'valuation_rate': valuation_rate}
        r = {'company': company_name,
             'purpose': 'Stock Reconciliation',
             'posting_date': date,
             'set_posting_time': 1,
             'expense_account': account,
             'doctype': 'Stock Reconciliation',
             'items': [item]}
        if pinv_name:
            r['purchase_invoice'] = pinv_name 
        doc = gui_api_wrapper(Api.api.insert,r)
        return doc

def project_into_stock(pname,qty=1):
    for pinv in Api.api.get_list("Purchase Invoice",
                                 filters={'project':pname,
                                          'status': ['!=','Cancelled']},
                                 limit_page_length=1000):
        purchase_invoice_into_stock(pinv['name'],qty)

def purchase_invoice_into_stock(pinv_name,qty=1):
    pinv = Api.api.get_doc("Purchase Invoice",pinv_name)
    pname = pinv['project']
    if not pname:
        print("Keine Projekt-Lagerhaltung, da kein Projekt für Einkaufsrechnung {} gefunden".format(pinv_name))
        return
    proj = Api.api.get_doc("Project",pname)
    if not project.is_stock(proj):
        print("Keine Projekt-Lagerhaltung für Projekt {}".format(pname))
        return
    project_no = int(pname.split('-')[1])
    item_code = '000.900.{:03d}'.format(project_no)
    if not Api.api.get_list("Item",filters={'name':item_code}):
        desc = 'Material Projekt {} {}'.format(project_no,proj['project_name'])
        item = {'doctype' : 'Item',
              'item_code' : item_code,
              'item_name' : desc,
              'description' : desc,
              'item_group' : PROJECT_ITEM_GROUP,
              'item_defaults': [{'company': pinv['company'],
                                 'default_warehouse': PROJECT_WAREHOUSE}],
                'stock_uom' : PROJECT_UNIT}  
        print('Artikel {} {} angelegt.'.format(item_code,item_name))
        item = gui_api_wrapper(Api.api.insert,item)
    stock_rec = Api.api.get_list('Stock Reconciliation',
                                 filters={'purchase_invoice':pinv_name,
                                          'docstatus': ['!=',2]},
                                 limit_page_length=10)
    if stock_rec:
        stock_rec_names = list(map(lambda s:s['name'],stock_rec))
        print("Für Einkaufsrechnung {} existiert schon Bestandsabgleich(e) {}".format(pinv_name,stock_rec_names))
        return
    valuation_rate = pinv['total']
    account = list(SOMIKO_ACCOUNTS.values())[0]
    doc = stock_reconciliation_for_item(pinv['company'],pinv['posting_date'],
                                        item_code,PROJECT_WAREHOUSE,
                                        qty,valuation_rate,account,pinv_name)
    print('Bestandsabgleich {} angelegt. Bitte noch buchen.'.format(doc['name']))
    
