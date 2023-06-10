import json
import prerechnung
from api import Api, LIMIT
from args import init
import company
import traceback
from compute_tests import compute_diff, validate_prerechnungs, compute_json1_diff
import purchase_invoice
from purchase_invoice import get_element_with_high_confidence
import menu

init()
company.Company.init_companies()
company.Company.current_load_data()

good = 0
bad = 0
for pr in Api.api.get_list("PreRechnung", filters={'json1': ['is', 'set']}, limit_page_length=LIMIT):
    print("................", end="")
    print("\n", pr['name'])
    d = compute_json1_diff(pr)
    print(d)
    if d:
        bad += 1
    else:
        good += 1

total = good + bad

print("matching: {:.1f}% not matching: {:.1f}%".format(good / total * 100, bad / total * 100))

exit(0)

validate_prerechnungs()

exit(0)

for inv in Api.api.get_list("PreRechnung",
                            filters={'json1': ['is', 'set']},
                            limit_page_length=LIMIT):
    name = inv['name']
    pdf = Api.api.get_file(inv['pdf'])
    print("{} {}".format(inv['name'], inv['pdf']))
    with open(name + ".pdf", 'wb') as f:
        f.write(pdf)
    with open(name + ".json", 'w') as f:
        f.write(inv['json1'])

exit(0)

for pr in Api.api.get_list("PreRechnung",
                           filters={'short_error': ['is', 'set']},
                           limit_page_length=LIMIT):
    print(pr['name'], pr['short_error'])

exit(0)

FIELD = 'bill_no'
FIELD1 = 'bill_no'
for pr in Api.api.get_list("PreRechnung",
                           filters={'json': ['is', 'set'], 'json1': ['is', 'set']},
                           limit_page_length=LIMIT):
    myjson = json.loads(pr['json'])
    f = get_element_with_high_confidence(myjson, FIELD)
    json1 = json.loads(pr['json1'])
    if pr.get('json2'):
        json2 = json.loads(pr['json2'])
    else:
        json2 = {}
    # print(json1)
    if json1.get(FIELD1):
        if f != json1.get(FIELD1) and f != json2.get(FIELD1):
            if json2.get(FIELD1) and json2.get(FIELD1) != json1.get(FIELD1):
                print("{}: expected1: '{}',  expected2: '{}', actual: '{}'".format(pr['name'], json1.get(FIELD1),
                                                                                   json2.get(FIELD1), f))
            else:
                print("{}: expected1: '{}', actual: '{}'".format(pr['name'], json1.get(FIELD1), f))
        else:
            print("OK")
    else:
        print("not found")
#    prerechnung.process_inv(pr)
exit(0)
menu.main_loop()
exit(0)

company.Company.init_companies()
pinvs = Api.api.get_list("PreRechnung", filters={'lieferant': ['in',
                                                               ['Krannich Solar GmbH & Co KG', 'pvXchange Trading GmbH',
                                                                'Solarwatt GmbH', 'Wagner Solar',
                                                                'Heckert Solar GmbH']]},
                         limit_page_length=LIMIT)
for pr in pinvs:
    print(pr['name'])
    inv = purchase_invoice.PurchaseInvoice(True)
    pdf = pr['pdf']
    contents = Api.api.get_file(pdf)
    tmpfile = "/tmp/r.pdf"
    with open(tmpfile, "wb") as f:
        f.write(contents)
    try:
        inv.parse_invoice(None, tmpfile,
                          account=pr['buchungskonto'],
                          paid_by_submitter=pr['selbst_bezahlt'],
                          given_supplier=pr['lieferant'],
                          is_test=True)
    except Exception as e:
        print(e)
        pass
    try:
        vat = sum(map(int, inv.vat.values()))
    except:
        vat = 0
    if not inv.gross_total:
        inv.gross_total = inv.total + vat
    if vars(inv).get('items'):
        j = {'order_id': inv.order_id,
             'total': inv.total,
             'gross_total': inv.gross_total,
             'taxes': [{"rate": 19, "tax_amount": inv.vat[None]}],
             'supplier': inv.supplier,
             'posting_date': inv.date,
             'bill_no': inv.no,
             'shipping': inv.shipping}
        items = []
        for item in inv.items:
            d = vars(item)
            d['short_description'] = d['description']
            d['description'] = d['long_description']
            del d['long_description']
            del d['purchase_invoice']
            items.append(d)
        j['items'] = items
        pr['json2'] = json.dumps(j)
        pr['doctype'] = 'PreRechnung'
        Api.api.update(pr)
        print(j['taxes'])

exit(0)

for pr in Api.api.get_list("PreRechnung", filters={'json1': ['is', 'set']},
                           limit_page_length=LIMIT):
    compute_diff(pr)
exit(0)

company.Company.init_companies()
company.Company.current_load_data()
for pr in Api.api.get_list("PreRechnung", filters={'purchase_invoice': ['is', 'set'], 'error': ['is', 'set']},
                           limit_page_length=LIMIT):  # later on, replace with 1
    #    if pr.get('json1'):
    #        continue
    try:
        prerechnung.process_inv(pr)
        # create purchase invoice object based on pr['json']
        pr = Api.api.get_doc("PreRechnung", pr['name'])  # reload
        pinv2 = prerechnung.read_and_transfer(pr, check_dup=False)
        pinv2 = Api.api.get_doc("Purchase Invoice", pinv2.name)
        pr['json2'] = json.dumps(pinv2)
        pr['doctype'] = 'PreRechnung'
        Api.api.update(pr)
    except Exception as e:
        print(str(e))
        pr['error'] = str(e) + "\n" + traceback.format_exc()
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
