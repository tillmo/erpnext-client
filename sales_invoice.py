from api import Api, LIMIT
from collections import defaultdict

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
