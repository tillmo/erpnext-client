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

def stock_entry_for_item(company_name,date,item_code,warehouse,
                         ingoing,amount,account,
                         pinv_name=None,project=None):
        item = {'item_code': item_code,
                'expense_account': account,
                'qty': amount,
                'basic_rate': 1}
        e = {'company': company_name,
             'doctype': 'Stock Entry'}
        if ingoing: # only for adding to stock, use purchase invoice date
            item['t_warehouse'] = warehouse
            e['stock_entry_type'] = 'Material Receipt'
            e['posting_date'] = date
            e['set_posting_time'] = 1
        else:
            item['s_warehouse'] = warehouse
            e['stock_entry_type'] = 'Material Issue'
#            e['posting_date'] = "2022-04-07"
#            e['set_posting_time'] = 1
        if pinv_name:
            e['purchase_invoice'] = pinv_name 
        if project:
            e['project'] = project
        e['items'] = [item]
        doc = gui_api_wrapper(Api.api.insert,e)
        return doc

def project_into_stock(pname,ingoing=True):
    for pinv in Api.api.get_list("Purchase Invoice",
                                 filters={'project':pname,
                                          'status': ['!=','Cancelled']},
                                 limit_page_length=1000):
        purchase_invoice_into_stock(pinv['name'],ingoing)

def purchase_invoice_into_stock(pinv_name,ingoing=True):
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
        item = gui_api_wrapper(Api.api.insert,item)
        print('Artikel {} {} angelegt.'.format(item_code,desc))
    stock_ent = Api.api.get_list('Stock Entry',
                                 filters={'purchase_invoice':pinv_name,
                                          'docstatus': ['!=',2]},
                                 limit_page_length=10)
    if stock_ent and ingoing:
        stock_ent_names = list(map(lambda s:s['name'],stock_ent))
        print("Für Einkaufsrechnung {} existiert schon eine Lagerbuchung {}".format(pinv_name,stock_ent_names))
        return
    amount = pinv['total']
    account = list(SOMIKO_ACCOUNTS.values())[0]
    doc = stock_entry_for_item(pinv['company'],pinv['posting_date'],
                               item_code,PROJECT_WAREHOUSE,
                               ingoing,amount,account,pinv_name,pname)
    print('Lagerbuchung {} angelegt. Bitte noch buchen.'.format(doc['name']))
    
