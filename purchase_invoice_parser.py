import random
import re
import string

import easygui

from api import Api, LIMIT
import utils
from api_wrapper import gui_api_wrapper
from settings import STANDARD_ITEM_GROUP, STANDARD_PRICE_LIST, NKK_ACCOUNTS, KORNKRAFT_ACCOUNTS, STOCK_ITEM_GROUPS, \
    AGGREGATE_ITEMS, AGGREGATE_ITEM_VALUE, DEFAULT_ITEMS, WAREHOUSE


class SupplierItem:
    def __init__(self, inv):
        self.purchase_invoice = inv
        self.description = None
        self.long_description = None
        self.qty = None
        self.qty_unit = None
        self.rate = None
        self.pos = None
        self.amount = None
        self.item_code = None

    def search_item(self, supplier, check_dup=True):
        if self.item_code:
            if supplier in Api.item_code_translation:
                trans_table_supplier = Api.item_code_translation[supplier]
                if self.item_code in trans_table_supplier:
                    e_item_code = trans_table_supplier[self.item_code]
                    e_item = Api.items_by_code[e_item_code]
                    return e_item
        # look for most similar e_items
        sim_items = []
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
                e_item = gui_api_wrapper(Api.api.insert, e_item)
                return e_item
        return None

    def add_item_price(self, e_item, rate, uom, date):
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

    def process_item(self, supplier, date, check_dup=True):
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
            return {'item_code': e_item['item_code'],
                    'qty': self.qty,
                    'rate': self.rate,
                    'desc': self.description}
        else:
            return None


class PurchaseInvoiceParser:
    def __init__(self, purchase_invoice, supplier, lines):
        self.purchase_invoice = purchase_invoice
        self.supplier = supplier
        self.lines = lines
        self.line_items = []
        self.is_rechnung = False
        self.rounding_error = 0

    def get_purchase_data(self):
        supplier = self.purchase_invoice.supplier
        bill_no = self.purchase_invoice.no
        order_id = self.purchase_invoice.order_id
        shipping = self.purchase_invoice.shipping
        posting_date = self.purchase_invoice.date
        total = self.purchase_invoice.totals[self.purchase_invoice.default_vat] if self.purchase_invoice.totals[
            self.purchase_invoice.default_vat] else 0
        grand_total = self.purchase_invoice.gross_total if self.purchase_invoice.gross_total else 0

        taxes = []
        if self.purchase_invoice.vat[self.purchase_invoice.default_vat]:
            taxes.append({"rate": 19, "tax_amount": self.purchase_invoice.vat[self.purchase_invoice.default_vat]})

        items = []
        for s_item in self.purchase_invoice.items:
            items.append({
                "description": s_item.description,
                "qty": s_item.qty,
                "uom": s_item.qty_unit,
                "rate": s_item.rate,
                "amount": s_item.amount
            })

        result = {
            "supplier": supplier,
            "total": total,
            "grand_total": grand_total,
            "taxes": taxes,
        }
        if bill_no:
            result.update({
                "bill_no": bill_no,
            })
        if order_id:
            result.update({
                "order_id": order_id,
            })
        if posting_date:
            result.update({
                "posting_date": posting_date,
            })
        if shipping > 0:
            result.update({
                "shipping": shipping,
            })
        if items:
            result.update({
                "items": items,
            })

        return result

    def set_purchase_info(self):
        if self.supplier == 'generic':
            self.set_generic_info()
        else:
            self.set_basic_info()
            self.purchase_invoice.items = []
            self.purchase_invoice.shipping = 0
            if self.purchase_invoice.update_stock:
                self.set_items()
            self.set_totals()
        return self.purchase_invoice

    def set_generic_info(self):
        self.purchase_invoice.parse_generic(self.lines)

    def set_basic_info(self):
        self.purchase_invoice.date = None
        self.purchase_invoice.no = None
        item = []
        if self.supplier == 'nkk':
            for line in self.lines:
                words = line.split()
                if not self.purchase_invoice.date:
                    for i in range(len(words)):
                        self.purchase_invoice.date = utils.convert_date4(words[i])
                        if self.purchase_invoice.date:
                            self.purchase_invoice.no = words[i - 1]
                            break
                elif words:
                    for vat in self.purchase_invoice.vat_rates:
                        vatstr = "{:.2f}%".format(vat).replace(".", ",")
                        if words[0] == vatstr:
                            self.purchase_invoice.vat[vat] = utils.read_float(words[5])
                            self.purchase_invoice.totals[vat] = utils.read_float(words[1]) + \
                                                                utils.read_float(words[3])
        elif self.supplier == 'kornkraft':
            for vat in self.purchase_invoice.vat_rates:
                self.purchase_invoice.vat[vat] = 0
                self.purchase_invoice.totals[vat] = 0
            vat_rate_strs = ["{:.2f}".format(r).replace(".", ",") for r in self.purchase_invoice.vat_rates]
            for line in self.lines:
                words = line.split()
                if not self.purchase_invoice.date:
                    for i in range(len(words)):
                        self.purchase_invoice.date = utils.convert_date4(words[i])
                        if self.purchase_invoice.date:
                            self.purchase_invoice.no = words[i - 2]
                            break
                else:
                    if len(words) > 12:
                        words = [w.replace('*', '') for w in words]
                        for vat in vat_rate_strs:
                            if vat in words[0:6]:
                                vat = utils.read_float(vat)
                                self.purchase_invoice.vat[vat] = utils.read_float(words[-4])
                                self.purchase_invoice.totals[vat] = utils.read_float(words[-2]) - self.purchase_invoice.vat[vat]
                                break
        elif self.supplier == 'krannich':
            for line in self.lines:
                if line[0].isdigit():
                    self.line_items.append(item)
                    item = [line]
                else:
                    item.append(line)
            self.line_items.append(item)
            for line in self.line_items[0]:
                if (not self.purchase_invoice.date) and "echnung" in line:
                    self.purchase_invoice.no = line.split()[1]
                    self.purchase_invoice.date = utils.convert_date4(line.split()[2])
                for s in ["Auftragsbestätigung", "Order confirmation", "Vorkasse zu AB"]:
                    self.purchase_invoice.extract_order_id(s, line)
            if not self.purchase_invoice.order_id:
                for i in range(-1, -len(self.line_items) - 1, -1):
                    order_id_lines = [line for line in self.line_items[i] if
                                      'Vorkasse zu AB' in line or 'Vorkasse zur AB' in line]
                    if order_id_lines:
                        self.purchase_invoice.extract_order_id("Vorkasse zu AB", order_id_lines[0])
                        self.purchase_invoice.extract_order_id("Vorkasse zur AB", order_id_lines[0])
                        break
        elif self.supplier == 'pvxchange':
            preamble = True
            for line in self.lines:
                words = line.split()
                for i in [1, 2]:
                    if len(words) > i:
                        d = utils.convert_date4(words[i])
                        if d:
                            self.date = d
                if line[0:8] == "Rechnung":
                    if len(words) > 1:
                        self.no = words[2]
                if preamble:
                    if len(line) >= 4 and line[0:4] == "Pos.":
                        preamble = False
                    continue
                if len(line) >= 5 and line[0:5] == "Seite":
                    preamble = True
                    continue
                try:
                    pos_no = int(words[0])
                except Exception:
                    pos_no = -1
                if pos_no == 28219:
                    break
                if pos_no >= 0 or 'Nettosumme' in line:
                    self.line_items.append(item)
                    item = [line]
                else:
                    item.append(line)
            self.line_items.append(item)
        elif self.supplier == 'heckert':
            for line in self.lines:
                words = line.split()
                if "Belegdatum" in line:
                    d = utils.convert_date4(words[-1])
                    if d:
                        self.purchase_invoice.date = d
                if "Auftrag " in line:
                    self.purchase_invoice.order_id = line[120:].split()[0]
                if "Belegnummer / Document Number" in line:
                    self.purchase_invoice.no = words[-1]
                if words and words[0] and words[0][0].isdigit():
                    self.line_items.append(item)
                    item = [line]
                else:
                    item.append(line)
            self.line_items.append(item)
        elif self.supplier == 'wagner':
            for line in self.lines:
                words = line.split()
                if not self.purchase_invoice.date and "Datum" in line:
                    d = utils.convert_date_written_month(" ".join(words[-3:]))
                    if d:
                        self.purchase_invoice.date = d
                if "Auftragsnummer" in line:
                    self.purchase_invoice.order_id = words[-1]
                if not self.purchase_invoice.no and (
                        "Auftragsbestätigung" in line or "Vorkasserechnung" in line or "Rechnung" in line):
                    self.purchase_invoice.no = words[-1]
                    self.is_rechnung = "Rechnung" in line
                elif words and words[0] and words[0][0].isdigit():
                    self.line_items.append(item)
                    item = [line]
                else:
                    item.append(line)
            self.line_items.append(item)

    def set_items(self):
        if self.supplier == 'nkk':
            self.purchase_invoice.items = []
            self.purchase_invoice.assign_default_e_items(NKK_ACCOUNTS)
        elif self.supplier == 'kornkraft':
            self.purchase_invoice.items = []
            self.purchase_invoice.assign_default_e_items(KORNKRAFT_ACCOUNTS)
        elif self.supplier == 'krannich':
            for item_lines in self.line_items[1:]:
                item_str = item_lines[0]
                clutter = ['Einzelpreis', 'Krannich', 'IBAN', 'Rechnung', 'Übertrag']
                s_item = SupplierItem(self.purchase_invoice)
                s_item.description = ""
                long_description_lines = \
                    [l for l in item_lines[1:] \
                     if utils.no_substr(clutter, l) and l.strip()]
                if long_description_lines:
                    s_item.description = " ".join(long_description_lines[0][0:82].split())
                s_item.long_description = ""
                for l in long_description_lines:
                    if "Zwischensumme" in l:
                        break
                    s_item.long_description += l
                try:
                    pos = float(item_str[0:7].split()[0])
                except Exception as e:
                    print(e)
                    continue
                if pos > 1000:
                    break
                if "Vorkasse" in s_item.description:
                    continue
                s_item.item_code = item_str.split()[1]
                q = re.search("([0-9]+) *([A-Za-z]+)", item_str[73:99])
                if not q:
                    continue
                s_item.qty = int(q.group(1))
                s_item.qty_unit = q.group(2)
                s_item.amount = utils.read_float(item_str[157:].split()[0])
                if s_item.qty_unit == "Rol":
                    try:
                        r1 = re.search('[0-9]+ *[mM]', s_item.description)
                        r2 = re.search('[0-9]+', r1.group(0))
                        s_item.qty_unit = "Meter"
                        s_item.qty = int(r2.group(0))
                    except Exception:
                        pass
                if s_item.qty:
                    s_item.rate = round(s_item.amount / s_item.qty, 2)
                    self.rounding_error += s_item.amount - s_item.rate * s_item.qty
                    self.purchase_invoice.items.append(s_item)
        elif self.supplier == 'pvxchange':
            for item_lines in self.line_items[1:-1]:
                try:
                    parts = " ".join(map(lambda s: s.strip(), item_lines)).split()
                    s_item = SupplierItem(self.purchase_invoice)
                    s_item.qty = int(parts[1])
                    s_item.rate = utils.read_float(parts[-4])
                    s_item.amount = utils.read_float(parts[-2])
                    s_item.qty_unit = "Stk"
                    s_item.description = " ".join(parts[2:-4])
                    s_item.long_description = s_item.description
                except Exception:
                    continue
                try:
                    ind = parts.index('Artikelnummer:')
                    s_item.item_code = parts[ind + 1]
                except Exception:
                    s_item.item_code = None
                if s_item.description.strip() == "Transportkosten":
                    self.purchase_invoice.shipping = s_item.amount
                    continue
                if not (s_item.description == "Selbstabholer" and s_item.amount == 0.0):
                    self.purchase_invoice.items.append(s_item)
        elif self.supplier == 'heckert':
            for item_lines in self.line_items[1:]:
                item_str = item_lines[0]
                try:
                    pos = int(item_str.split()[0])
                except Exception:
                    continue
                if pos >= 28100:
                    continue
                clutter = ['Rabatt', 'Übertrag']
                s_item = SupplierItem(self.purchase_invoice)
                long_description_lines = \
                    [l for l in item_lines[1:] \
                     if utils.no_substr(clutter, l) and l.strip()]
                s_item.description = " ".join(long_description_lines[0][0:82].split())
                s_item.long_description = ""
                for l in long_description_lines:
                    if "Zwischensumme" in l:
                        break
                    s_item.long_description += l
                if "Vorkasse" in s_item.description:
                    continue
                s_item.item_code = item_str.split()[1]
                q = re.search("([0-9]+) *([A-Za-z]+)", item_str[60:73])
                if not q:
                    continue
                s_item.qty = int(q.group(1))
                s_item.qty_unit = q.group(2)
                if s_item.qty_unit == "ST":
                    s_item.qty_unit = "Stk"
                price = utils.read_float(item_str[98:114].split()[0])
                try:
                    price1 = utils.read_float(item_lines[1][98:114].split()[0])
                except Exception:
                    price1 = 0
                if price1 > price:
                    price = price1
                discount_lines = [line for line in item_lines if 'Rabatt' in line or 'Dieselzuschlag' in line]
                discount = 0
                for discount_line in discount_lines:
                    discount += utils.read_float(discount_line[135:153].split()[0])
                s_item.amount = utils.read_float(item_str[135:153].split()[0]) + discount
                if s_item.description.split()[0] == "Transportkosten":
                    self.purchase_invoice.shipping = s_item.amount
                    continue
                s_item.rate = round(s_item.amount / s_item.qty, 2)
                self.rounding_error += s_item.amount - s_item.rate * s_item.qty
                self.purchase_invoice.items.append(s_item)
        elif self.supplier == 'wagner':
            for item_lines in self.line_items[1:]:
                item_str = item_lines[0]
                words = item_str.split()
                try:
                    pos = int(words[0])
                except Exception:
                    continue
                if pos >= 28100:
                    continue
                clutter = ['Rabatt', 'Übertrag']
                s_item = SupplierItem(self.purchase_invoice)
                long_description_lines = \
                    [l for l in item_lines[1:] \
                     if utils.no_substr(clutter, l) and l.strip()]
                s_item.description = " ".join(long_description_lines[0][0:82].split())
                s_item.long_description = ""
                for l in long_description_lines:
                    if "Zwischensumme" in l:
                        break
                    s_item.long_description += l
                if self.is_rechnung:
                    s_item.item_code = words[1]
                else:
                    ind = words.index("Artikelnr.")
                    s_item.item_code = words[ind + 1]
                ind = words.index("Stück")
                s_item.qty = int(words[ind - 1])
                s_item.qty_unit = "Stk"
                s_item.amount = utils.read_float(words[-1])
                if "Fracht" in s_item.description or "Fracht" in words:
                    self.purchase_invoice.shipping = s_item.amount
                    continue
                s_item.rate = round(s_item.amount / s_item.qty, 2)
                self.rounding_error += s_item.amount - s_item.rate * s_item.qty
                self.purchase_invoice.items.append(s_item)

    def set_totals(self):
        if self.supplier == 'nkk':
            self.purchase_invoice.shipping = 0
        elif self.supplier == 'kornkraft':
            self.purchase_invoice.shipping = 0
        elif self.supplier == 'krannich':
            vat_line = ""
            for i in range(-1, -len(self.line_items) - 1, -1):
                vat_lines = [line for line in self.line_items[i] if 'MwSt' in line]
                if vat_lines:
                    vat_line = vat_lines[0]
                    if self.purchase_invoice.update_stock:
                        self.purchase_invoice.shipping = PurchaseInvoiceParser.get_amount_krannich \
                            ([line for line in self.line_items[i] \
                              if 'Insurance' in line or 'Freight' in line \
                              or 'Neukundenrabatt' in line])
                    break
            for i in range(-1, -len(self.line_items) - 1, -1):
                gross_lines = [line for line in self.line_items[i] if 'Endsumme' in line]
                if gross_lines:
                    self.purchase_invoice.gross_total = utils.read_float(gross_lines[0].split()[-1])
                    break
            self.purchase_invoice.shipping += self.rounding_error
            self.purchase_invoice.totals[self.purchase_invoice.default_vat] = utils.read_float(vat_line[146:162])
            self.purchase_invoice.vat[self.purchase_invoice.default_vat] = PurchaseInvoiceParser.get_amount_krannich([vat_line])
        elif self.supplier == 'pvxchange':
            for i in range(-1, -5, -1):
                try:
                    vat_line = [line for line in self.line_items[i] if 'MwSt' in line][0]
                    total_line = [line for line in self.line_items[i] if 'Nettosumme' in line][0]
                    break
                except Exception:
                    pass
            self.purchase_invoice.vat[self.purchase_invoice.default_vat] = utils.read_float(vat_line.split()[-2])
            self.purchase_invoice.totals[self.purchase_invoice.default_vat] = utils.read_float(total_line.split()[-2])
        elif self.supplier == 'heckert':
            vat_line = ""
            for i in range(-1, -len(self.line_items), -1):
                vat_lines = [line for line in self.line_items[i] if 'MwSt' in line]
                if vat_lines:
                    vat_line = vat_lines[0]
                    break
            for i in range(-1, -len(self.line_items), -1):
                total_lines = [line for line in self.line_items[i] if 'Zwischensumme' in line]
                if total_lines:
                    total_line = total_lines[0]
                    break
            self.purchase_invoice.shipping += self.rounding_error
            self.purchase_invoice.totals[self.purchase_invoice.default_vat] = utils.read_float(total_line[135:153])
            self.purchase_invoice.vat[self.purchase_invoice.default_vat] = utils.read_float(vat_line[135:153])
        elif self.supplier == 'wagner':
            vat_line = ""
            for i in range(len(self.line_items)):
                vat_lines = [line for line in self.line_items[i] if 'MwSt' in line]
                if vat_lines:
                    vat_line = vat_lines[0]
                    break
            for i in range(len(self.line_items)):
                total_lines = [line for line in self.line_items[i] if 'Nettosumme' in line or 'Nettowarenwert' in line]
                if total_lines:
                    total_line = total_lines[0]
                    break
            self.purchase_invoice.shipping += self.rounding_error
            self.purchase_invoice.totals[self.purchase_invoice.default_vat] = utils.read_float(total_line.split()[-1])
            self.purchase_invoice.vat[self.purchase_invoice.default_vat] = utils.read_float(vat_line.split()[-1])

        self.purchase_invoice.compute_total()

    @classmethod
    def get_amount_krannich(cls, lines):
        return sum(map(lambda line: utils.read_float(line[-9:-1]), lines))
