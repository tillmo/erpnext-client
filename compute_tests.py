import json
import jsondiff
from api import Api, LIMIT

INV_FIELDS = ['supplier', 'posting_date', 'bill_no', 'total',  'grand_total',
              'order_id']

SUBFIELDS = ['qty', 'uom', 'rate', 'amount', 'tax_amount', 'account_head', 'item_code']

EXCLUDE_INVOICE_FIELDS = ['owner', 'creation', 'modified', 'modified_by',
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
    'expense_account', 'set_posting_time', 'is_paid', 'is_return',
    'apply_tds', 'currency', 'buying_price_list', 'price_list_currency',
    'ignore_pricing_rule', 'is_subcontracted', 'tax_category',
    'base_taxes_and_charges_deducted', 'taxes_and_charges_deducted',
    'base_discount_amount', 'additional_discount_percentage']
EXCLUDE_SUBFIELDS = ['name', 'owner', 'creation', 'modified',
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
                         'item_wise_tax_detail', 'doctype']

def convert_item(item,supplier):
    k = item[0]
    v = item[1]
    if k =='account_head':
        if 'Bezugsnebenkosten' in v:
            return [('shipping',1)]
        if 'Abziehbare VSt' in v:
            rate = int(v.split('%')[0].split()[-1])
            return [('rate',rate)]
    if k == 'item_code':
        e_item = Api.items_by_code[v]
        res = [('description',e_item['description'])]
        supp_items = e_item.get('supplier_items')
        if supp_items:
            s = [i for i in supp_items if i.get('supplier')==supplier]
            if s:
                res += [('item_code',s[-1].get('supplier_part_no'))]
        return res
    return [item]

def convert(d,supplier):
    res = [convert_item((k,v),supplier) for k,v in d.items() if k in SUBFIELDS and v]
    return sum(res,[])

def compute_json(pr):
    pinv = Api.api.get_doc("Purchase Invoice", pr['purchase_invoice'])
    j = {field:pinv[field] for field in INV_FIELDS if field in pinv}
    supp = j.get('supplier')
    for f in ['items','taxes']:
        j[f] = [{k:v for k,v in convert(d,supp)} for d in pinv[f]]
    for d in j['taxes']:
        if 'shipping' in d.keys():
            j['shipping'] = d['tax_amount']
            j['taxes'].remove(d)
    if j['items'] and j['items'][0].get('description') in ['Generisches Einkaufsprodukt','Montagematerial']:
        del j['items']
    print(j)        
    pr['json1'] = json.dumps(j)
    pr['doctype'] = 'PreRechnung'
    Api.api.update(pr)

def compute_diff(pr):
    jsons = [1,2]
    jsons[0] = json.loads(pr['json1'])
    jsons[1] = json.loads(pr['json2'])
    for field in EXCLUDE_INVOICE_FIELDS:
        for k in range(2):
            if field in jsons[k]:
                del jsons[k][field]
    for field in ['items','taxes']:
        for subfield in EXCLUDE_SUBFIELDS:
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
    
