import datefinder
from supplier_item import SupplierItem


def get_element_with_high_confidence(invoice_json, element_type):
    elements = [el for el in invoice_json['entities'] if el.get('type') == element_type]
    sorted_list = sorted(elements, key=lambda k: -float(k['confidence']))
    best_elem = sorted_list[0]['value'] if len(sorted_list) > 0 else None
    if type(best_elem) == str:
        best_elem = best_elem.strip()
    return best_elem


def get_float_number(float_str: str):
    float_str = float_str.replace('USD', '').replace('EUR', '')
    if ',' in float_str:
        float_str = float_str.replace('.', '').replace(',', '.')
    return float(float_str.replace(' ', ''))


def find_date(date_string: str):
    matches = list(datefinder.find_dates(date_string))
    return matches[0].strftime('%Y-%m-%d') if matches else None


class PurchaseInvoiceGoogleParser:
    def __init__(self, purchase_invoice, invoice_json, supplier, is_test):
        self.purchase_invoice = purchase_invoice
        self.invoice_json = invoice_json
        self.supplier = supplier
        self.is_test = is_test

    def get_purchase_data(self):
        supplier = self.purchase_invoice.supplier
        bill_no = self.purchase_invoice.no
        order_id = self.purchase_invoice.order_id
        shipping = self.purchase_invoice.shipping
        posting_date = self.purchase_invoice.date
        total = self.purchase_invoice.totals[self.purchase_invoice.default_vat] if self.purchase_invoice.totals[self.purchase_invoice.default_vat] else 0
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
        try:
            rounding_error = 0
            self.purchase_invoice.items = []
            self.purchase_invoice.shipping = 0
            self.purchase_invoice.extract_items = self.purchase_invoice.update_stock
            self.purchase_invoice.no = get_element_with_high_confidence(self.invoice_json, 'bill_no')
            if type(self.purchase_invoice.no) is str:
                self.purchase_invoice.no = self.purchase_invoice.no.replace(" ", "")
            self.purchase_invoice.supplier = self.supplier or get_element_with_high_confidence(self.invoice_json, 'supplier')
            self.purchase_invoice.supplier_address = get_element_with_high_confidence(self.invoice_json, 'supplier_address')
            self.purchase_invoice.shipping_address = get_element_with_high_confidence(self.invoice_json, 'ship_to_address')
            self.purchase_invoice.order_id = get_element_with_high_confidence(self.invoice_json, 'order_id')
            self.purchase_invoice.gross_total = get_element_with_high_confidence(self.invoice_json, 'total_amount')
            if self.purchase_invoice.gross_total:
                self.purchase_invoice.gross_total = get_float_number(self.purchase_invoice.gross_total)
            net_amount = get_element_with_high_confidence(self.invoice_json, 'net_amount')
            if net_amount:
                self.purchase_invoice.totals[self.purchase_invoice.default_vat] = get_float_number(net_amount)
            total_tax_amount = get_element_with_high_confidence(self.invoice_json, 'total_tax_amount')
            if total_tax_amount:
                self.purchase_invoice.vat[self.purchase_invoice.default_vat] = get_float_number(total_tax_amount)
                if self.purchase_invoice.gross_total and (not net_amount or self.purchase_invoice.gross_total - self.purchase_invoice.vat[self.purchase_invoice.default_vat] > self.purchase_invoice.totals[self.purchase_invoice.default_vat]):
                    self.purchase_invoice.totals[self.purchase_invoice.default_vat] = round(self.purchase_invoice.gross_total - self.purchase_invoice.vat[self.purchase_invoice.default_vat], 2)
            else:
                if self.purchase_invoice.gross_total:
                    if not net_amount or self.purchase_invoice.gross_total == self.purchase_invoice.totals[self.purchase_invoice.default_vat]:
                        self.purchase_invoice.vat[self.purchase_invoice.default_vat] = round(self.purchase_invoice.gross_total * 0.19 / 1.19, 2)
                        self.purchase_invoice.totals[self.purchase_invoice.default_vat] = round(self.purchase_invoice.gross_total - self.purchase_invoice.vat[self.purchase_invoice.default_vat], 2)
                elif net_amount:
                    self.purchase_invoice.gross_total = self.purchase_invoice.totals[self.purchase_invoice.default_vat]
                    self.purchase_invoice.vat[self.purchase_invoice.default_vat] = round(self.purchase_invoice.totals[self.purchase_invoice.default_vat] * 0.19 / 1.19, 2)
                    self.purchase_invoice.totals[self.purchase_invoice.default_vat] = round(self.purchase_invoice.gross_total - self.purchase_invoice.vat[self.purchase_invoice.default_vat], 2)

            due_date = get_element_with_high_confidence(self.invoice_json, 'due_date')
            if due_date:
                due_date = find_date(due_date)
            posting_date = get_element_with_high_confidence(self.invoice_json, 'posting_date')
            if posting_date:
                posting_date = find_date(posting_date)
            if due_date:
                if posting_date and self.purchase_invoice.supplier != 'Heckert Solar GmbH':
                    self.purchase_invoice.date = min(posting_date, due_date)
                else:
                    self.purchase_invoice.date = due_date
            else:
                self.purchase_invoice.date = posting_date

            if self.purchase_invoice.update_stock:
                line_items = [el for el in self.invoice_json['entities'] if el.get('type') in ['item', 'line_item']]
                sum_amount = 0
                for line_item in line_items:
                    s_item = SupplierItem(self)
                    for prop in line_item.get('properties'):
                        if prop['type'] in ['item-description', 'line_item/description'] and s_item.description is None:
                            s_item.description = prop['value']
                            s_item.long_description = prop['value']
                        elif prop['type'] in ['item-code', 'line_item/product_code'] and s_item.item_code is None:
                            s_item.item_code = prop['value']
                        elif prop['type'] in ['item-pos', 'line_item/pos'] and s_item.pos is None:
                            s_item.pos = prop['value']
                        elif prop['type'] in ['item-quantity', 'line_item/quantity'] and s_item.qty is None:
                            quantity_str = prop['value']
                            if quantity_str:
                                if 'STX' in quantity_str:
                                    quantity_str = quantity_str.replace('STX', '')
                                if 'Stk' in quantity_str:
                                    quantity_str = quantity_str.replace('Stk', '')
                                if 'ST' in quantity_str:
                                    quantity_str = quantity_str.replace('ST', '')
                                if 'X' in quantity_str:
                                    quantity_str = quantity_str.replace('X', '')
                                s_item.qty = get_float_number(quantity_str)
                            else:
                                s_item.qty = 0
                            if s_item.qty < 0:
                                s_item.qty = 0
                            s_item.qty_unit = 'Stk'
                        elif prop['type'] in ['item-amount', 'line_item/amount'] and s_item.amount is None:
                            s_item.amount = round(get_float_number(prop['value']), 2) if prop['value'] else 0
                        elif prop['type'] in ['item-unit-price', 'line_item/unit_price'] and s_item.rate is None:
                            s_item.rate = get_float_number(prop['value']) if prop['value'] else None
                            if s_item.qty and not s_item.amount:
                                s_item.amount = round(s_item.rate * s_item.qty, 2) if prop['value'] else 0
                            elif not s_item.qty and s_item.amount:
                                s_item.qty = s_item.amount / s_item.rate if prop['value'] else 0
                    if s_item.description and "Vorkasse" in s_item.description:
                        continue
                    if s_item.description and (
                            "Fracht" in s_item.description or "Transportkosten" in s_item.description or "Versand" in s_item.description):
                        self.purchase_invoice.shipping = s_item.amount if s_item.amount else 0
                        continue
                    if s_item.qty and s_item.amount:
                        if not s_item.rate:
                            s_item.rate = round(s_item.amount / s_item.qty, 2)
                        # rounding_error += s_item.amount - s_item.rate * s_item.qty
                        sum_amount += s_item.amount
                        self.purchase_invoice.items.append(s_item)
                    elif s_item.description:
                        print("Keine Mengenangabe gefunden für", s_item.description)
                if self.purchase_invoice.gross_total and self.purchase_invoice.vat[self.purchase_invoice.default_vat]:
                    diff = self.purchase_invoice.gross_total - self.purchase_invoice.vat[self.purchase_invoice.default_vat] - sum_amount
                    if diff >= 1:
                        s_item = SupplierItem(self)
                        s_item.qty = 1
                        s_item.amount = round(diff, 2)
                        s_item.rate = round(s_item.amount, 2)
                        self.purchase_invoice.items.append(s_item)
            self.purchase_invoice.shipping += rounding_error
            self.purchase_invoice.shipping = round(self.purchase_invoice.shipping, 2)
            if self.purchase_invoice.shipping and self.purchase_invoice.totals[self.purchase_invoice.default_vat]:
                self.purchase_invoice.totals[self.purchase_invoice.default_vat] -= self.purchase_invoice.shipping
                self.purchase_invoice.totals[self.purchase_invoice.default_vat] = round(self.purchase_invoice.totals[self.purchase_invoice.default_vat], 2)
            self.purchase_invoice.compute_total()
        except Exception as e:
            if self.purchase_invoice.update_stock:
                raise e
            elif not self.is_test:
                print(e)
                print("Rückfall auf Standard-Rechnungsbehandlung")
        return self.purchase_invoice
