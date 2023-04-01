import json
import jsondiff
import prerechnung
from api import Api, LIMIT
from args import init
import company
import traceback

init()



for pr in Api.api.get_list("PreRechnung", filters={'json1': ['is', 'set']},
                           limit_page_length=LIMIT):
    jsons = [1,2]
    jsons[0] = json.loads(pr['json1'])
    jsons[1] = json.loads(pr['json2'])
    for field in ['owner', 'creation', 'modified', 'modified_by',
                  'docstatus', 'due_date', 'posting_time', 'net_total',
                  'base_taxes_and_charges_added', 'base_total',
                  'base_total_taxes_and_charges', 'base_net_total',
                  'taxes_and_charges_added', 'total_taxes_and_charges',
                  'base_grand_total', 'base_rounded_total', 'base_in_words',
                  'rounded_total', 'in_words', 'outstanding_amount',
                  'status', 'shipping_address', 'shipping_address_display',
                  'other_charges_calculation','supplier_invoice','project',
                  'amended_from','paid_by_submitter', 'payment_schedule',
                  'against_expense_account','supplier_invoice','update_stock',
                  'advances','total_advance','supplier_name',
                  'supplier_address','address_display','naming_series',
                  'cost_center','represents_company',
                  'expense_account']:
        for k in range(2):
            if field in jsons[k]:
                del jsons[k][field]
    for field in ['items','taxes']:
        for subfield in ['name', 'owner', 'creation', 'modified',
                         'modified_by','parent', 'docstatus',
                         'margin_rate_or_amount','base_rate', 'base_amount',
                         'stock_uom_rate', 'net_rate', 'net_amount',
                         'base_net_rate', 'base_net_amount','item_group',
                         'price_list_rate', 'base_price_list_rate',
                         'margin_type','expense_account','parentfield',
                         'parenttype', 'category', 'add_deduct_tax',
                         'charge_type', 'included_in_print_rate',
                         'included_in_paid_amount', 'account_head',
                         'description', 'cost_center',
                         'tax_amount_after_discount_amount',
                         'base_tax_amount', 'base_total',
                         'base_tax_amount_after_discount_amount',
                         'item_wise_tax_detail', 'doctype']:
            for k in range(2):
                for i in range(len(jsons[k][field])):
                    if subfield in jsons[k][field][i]:
                        del jsons[k][field][i][subfield]
    diff = jsondiff.diff(jsons[0],jsons[1],syntax='symmetric')
    for field in ['items']:
        if field in diff:
            for item in list(diff[field].keys()):
                if type(diff[field][item]) == dict:
                    item_codes = diff[field][item].get('item_code')
                    if item_codes and len(item_codes)==2 and '000.000.000' in item_codes:
                        del diff[field][item]
    print(".",end="")
    if diff and list(diff.keys())!=['name']:
        print("\n",pr['name'])
        print(diff)
    else:
        diff = None
    pr['diff'] = str(diff)
    pr['doctype'] = 'PreRechnung'
    Api.api.update(pr)
exit(0)          

company.Company.init_companies()
company.Company.current_load_data()
for pr in Api.api.get_list("PreRechnung", filters={'purchase_invoice': ['is', 'set'], 'error':['is', 'set']},
                           limit_page_length=LIMIT):  # later on, replace with 1
#    if pr.get('json1'):
#        continue
    try:
        pinv1 = Api.api.get_doc("Purchase Invoice", pr['purchase_invoice'])
        #if not pr.get('json'):
        prerechnung.process_inv(pr)
        # create purchase invoice object based on pr['json']
        pr = Api.api.get_doc("PreRechnung", pr['name'])  # reload
        pinv2 = prerechnung.read_and_transfer(pr, check_dup=False)
        pinv2 = Api.api.get_doc("Purchase Invoice", pinv2.name)
        pr['json1'] = json.dumps(pinv1)
        pr['json2'] = json.dumps(pinv2)
        pr['doctype'] = 'PreRechnung'
        Api.api.update(pr)
    except Exception as e:
        print(str(e))
        pr['error'] = str(e)+"\n"+traceback.format_exc()
        pr['short_error'] = str(e)
        pr['doctype'] = 'PreRechnung'
        Api.api.update(pr)
    # with open("pinv1.json", "w") as f:
    #     json.dump(pinv1, f)
    # with open("pinv2.json", "w") as f:
    #     json.dump(pinv2, f)
exit(0)

pr = Api.api.get_list("PreRechnung", filters={'processed': False}, limit_page_length=1)[0]
doc = Api.api.get_doc("PreRechnung", pr['name'])
prerechnung.process_inv(doc)

for pr in Api.api.get_list(
        "PreRechnung", filters={'processed': False}, limit_page_length=1):  # later on, replace 1 with LIMIT
    doc = Api.api.get_doc("PreRechnung", pr['name'])
    prerechnung.process_inv(doc)

exit(0)

for pr in Api.api.get_list("PreRechnung", filters={'purchase_invoice': ['is', 'set']},
                           limit_page_length=LIMIT):  # later on, replace with 1
    pr['processed'] = False
    pr['doctype'] = 'PreRechnung'
    Api.api.update(pr)
    
exit(0)    
