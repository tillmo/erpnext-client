from __future__ import annotations

import random
import re
import string
from typing import TYPE_CHECKING, Any
from gui import easygui
import utils
from api_wrapper import gui_api_wrapper
from api import Api, LIMIT
from settings import STANDARD_ITEM_GROUP, STANDARD_PRICE_LIST, STOCK_ITEM_GROUPS, AGGREGATE_ITEMS, AGGREGATE_ITEM_VALUE,\
    DEFAULT_ITEMS, WAREHOUSE, MICRO_INVERTER_ITEMS

if TYPE_CHECKING:
    from purchase_invoice import PurchaseInvoice

# invoices name a micro inverter as such or only by its Hoymiles model ("HMS-1600-4T")
MICRO_INVERTER_RE = re.compile(r'mi[ck]ro-?\s?(?:wechselrichter|inverter)|modulwechselrichter|balkonwechselrichter'
                               r'|\bHM[ST]?[- ]?\d{3,4}', re.IGNORECASE)
# accessories, services, kits and storage mention the inverter they belong to after their own name
# ("Anschlusskabel ... für Hoymiles-Mikrowechselrichter"), a real inverter line starts with the inverter
NOT_AN_INVERTER_RE = re.compile(r'kabel|stecker|buchse|connector|verbinder|endkappe|\bdtu\b|halter|drosselung'
                                r'|leistungsbegrenzung|balkonkraftwerk|\bset\b|komplett|speicher|batterie|akku',
                                re.IGNORECASE)
# Wp is the power of modules, not of the inverter, and is left out by the \b after W
WATTS_RE = re.compile(r'(?<![\d.,])(\d{3,4})\s?(?:W|Watt|VA)\b|\bHM[ST]?[- ]?(\d{3,4})', re.IGNORECASE)


def micro_inverter_code(text: str) -> str | None:
    """Item code of a micro inverter by its nominal power, None if the text is not a micro inverter
    with a recognisable power. The nominal power is the largest one: "1600W gedrosselt auf 800W"."""
    inverter = MICRO_INVERTER_RE.search(text)
    if not inverter:
        return None
    other = NOT_AN_INVERTER_RE.search(text)
    if other and other.start() < inverter.start():
        return None
    watts = [int(w or model) for w, model in WATTS_RE.findall(text)]
    if not watts:
        return None
    return next(code for min_watts, code in MICRO_INVERTER_ITEMS if max(watts) >= min_watts)


class SupplierItem:
    purchase_invoice: PurchaseInvoice
    description: str | None
    long_description: str | None
    qty: float | None
    qty_unit: str | None
    rate: float | None
    pos: str | None
    amount: float | None
    item_code: str | None

    def __init__(self, inv: PurchaseInvoice) -> None:
        self.purchase_invoice = inv
        self.description = None
        self.long_description = None
        self.qty = None
        self.qty_unit = None
        self.rate = None
        self.pos = None
        self.amount = None
        self.item_code = None

    def micro_inverter_item(self) -> dict[str, Any] | None:
        code = micro_inverter_code(self.long_description or self.description or '')
        e_item = Api.items_by_code.get(code) if code else None
        if e_item:
            print("Mikro-Wechselrichter nach Nennleistung: {} {}".format(code, e_item['item_name']))
        return e_item

    def search_item(self, supplier: str, check_dup: bool = True) -> dict[str, Any] | None:
        # before the supplier codes: those learned earlier may point to the old per-model inverter items
        e_item = self.micro_inverter_item()
        if e_item:
            return e_item
        if self.item_code:
            if supplier in Api.item_code_translation:
                trans_table_supplier = Api.item_code_translation[supplier]
                if self.item_code in trans_table_supplier:
                    e_item_code = trans_table_supplier[self.item_code]
                    e_item = Api.items_by_code[e_item_code]
                    return e_item
        # look for most similar e_items
        sim_items: list[tuple[float, dict[str, Any]]] = []
        for e_code, e_item in Api.items_by_code.items():
            if e_code in DEFAULT_ITEMS:
                sim = 1
            elif self.description:
                sim = utils.similar(e_item['item_name'], self.description)
            else:
                sim = 0
            sim_items.append((sim, e_item))
        top_items = sorted(sim_items, reverse=True, key=lambda x: x[0])[0:20]
        # print(top_items)
        texts = ['Neuen Artikel anlegen']
        texts += [i[1]['item_code'] + ' ' + i[1]['item_name'] for i in top_items]
        title = "Artikel wählen"
        msg = "Artikel in Rechnung:\n{0}\n\nCode Lieferant: {1}\n\n".format(self.long_description, self.item_code)
        msg += "Bitte passenden Artikel in ERPNext auswählen:"
        if check_dup:
            choice = easygui.choicebox(msg, title, texts)
        else:
            choice = 'Neuen Artikel anlegen'
        if choice == None:
            return None
        if choice:
            choice = texts.index(choice)
        if choice:
            e_item = top_items[choice - 1][1]
            if self.item_code:
                doc = gui_api_wrapper(Api.api.get_doc, 'Item',
                                      e_item['item_code'])
                doc['supplier_items'].append( \
                    {'supplier': supplier,
                     'supplier_part_no': self.item_code})
                Api.item_code_translation[supplier][self.item_code] = e_item['item_code']
                # print(doc['supplier_items'])
                gui_api_wrapper(Api.api.update, doc)
            return e_item
        else:
            title = "Artikelgruppe für Neuen Artikel in ERPNext wählen"
            msg = self.long_description + "\n" if self.long_description else ""
            if self.item_code:
                msg += "Code Lieferant: " + self.item_code + "\n"
            msg += "Einzelpreis: {0:.2f}€".format(self.rate)
            groups = Api.api.get_list("Item Group", limit_page_length=LIMIT)
            groups = [g['name'] for g in groups]
            groups.sort()
            if check_dup:
                group = easygui.choicebox(msg, title, groups)
            else:
                group = STANDARD_ITEM_GROUP
            if group == None:
                return None
            msg += "\nArtikelgruppe: " + group
            title = "Neuen Artikel in ERPNext eintragen"
            msg += "\n\nDiesen Artikel eintragen?"
            if check_dup:
                choice = easygui.choicebox(msg, title, ["Ja", "Nein"])
            else:
                choice = "Ja"
            if choice == "Ja":
                item_code = "new" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                company_name = self.purchase_invoice.company_name
                e_item = {'doctype': 'Item',
                          'item_code': item_code,
                          'item_name': self.description[:140] if self.description else None,
                          'description': self.long_description,
                          'item_group': group,
                          'item_defaults': [{'company': company_name,
                                             'default_warehouse': WAREHOUSE}],
                          'stock_uom': self.qty_unit}
                if self.item_code:
                    e_item['supplier_items'] = [{'supplier': supplier,
                                                 'supplier_part_no': self.item_code}]
                    Api.item_code_translation[supplier][self.item_code] = item_code
                e_item = gui_api_wrapper(Api.api.insert, e_item)
                return e_item
        return None

    def add_item_price(self, e_item: dict[str, Any], rate: float, uom: str, date: str) -> None:
        docs = gui_api_wrapper(Api.api.get_list, 'Item Price',
                               filters={'item_code': e_item['item_code']})
        if docs:
            doc = gui_api_wrapper(Api.api.get_doc, 'Item Price', docs[0]['name'])
            if abs(float(doc['price_list_rate']) - rate) > 0.0005:
                title = "Preis anpassen?"
                msg = "Artikel: {0}\nAlter Preis: {1}\nNeuer Preis: {2:.2f}". \
                    format(e_item['description'], doc['price_list_rate'], rate)
                msg += "\n\nPreis anpassen?"
                if easygui.ccbox(msg, title):
                    doc['price_list_rate'] = rate
                    gui_api_wrapper(Api.api.update, doc)
        else:
            price = {'doctype': 'Item Price',
                     'item_code': e_item['item_code'],
                     'selling': True,
                     'buying': True,
                     'price_list': STANDARD_PRICE_LIST,
                     'valid_from': date,
                     'uom': uom,
                     'price_list_rate': rate}
            # print(price,e_item)
            doc = gui_api_wrapper(Api.api.insert, price)
            # print(doc)

    def process_item(self, supplier: str, date: str, check_dup: bool = True) -> dict[str, Any] | None:
        e_item = self.search_item(supplier, check_dup)
        if e_item:
            if e_item['item_group'] in STOCK_ITEM_GROUPS:
                self.add_item_price(e_item, self.rate, self.qty_unit, date)
            else:
                # convert into lump-sum aggregated item
                code = AGGREGATE_ITEMS.get(e_item['item_group'])
                if not code:
                    code = AGGREGATE_ITEMS['default']
                e_item['item_code'] = code
                self.qty = self.qty * self.rate / AGGREGATE_ITEM_VALUE
                self.rate = AGGREGATE_ITEM_VALUE
            result = {'item_code': e_item['item_code'],
                      'qty': self.qty,
                      'rate': self.rate,
                      'desc': self.description}
            if e_item.get('expense_account'):
                result['expense_account'] = e_item['expense_account']
            return result
        else:
            return None
