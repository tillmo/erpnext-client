#!/usr/bin/python3
from purchase_invoice_google_parser import PurchaseInvoiceGoogleParser
from purchase_invoice_parser import PurchaseInvoiceParser, SupplierItem
from settings import STANDARD_PRICE_LIST, STANDARD_NAMING_SERIES_PINV, VAT_DESCRIPTION, DELIVERY_COST_ACCOUNT, \
    DELIVERY_COST_DESCRIPTION, SOMIKO_ACCOUNTS

import os
import utils
import PySimpleGUI as sg
import easygui
import subprocess
import re
from api import Api, LIMIT
from api_wrapper import gui_api_wrapper
import settings
import doc
import company
import bank
import stock
from invoice import Invoice
from collections import defaultdict
from pprint import pprint
import jsondiff
from jsondiff.symbols import insert, delete
import jsoneditor


# extract amounts of form xxx,xx from string
def extract_amounts(s):
    amounts = re.findall(r"([0-9]+,[0-9][0-9])", s)
    return list(map(lambda s: float(s.replace(",", ".")), amounts))


# try to extract gross amount and vat from an invoice
def extract_amount_and_vat(lines, vat_rates):
    amounts = extract_amounts(" ".join(lines))
    if not amounts:
        return (None, None)
    amount = max(amounts)
    vat_factors = [vr / 100.0 for vr in vat_rates]
    for vat_factor in vat_factors:
        vat = round(amount / (1 + vat_factor) * vat_factor, 2)
        if vat in amounts:
            return (amount, vat)
    vat_lines = [l for l in lines if "mwst" in l.lower()]
    for line in vat_lines:
        v_amounts = extract_amounts(line)
        for vat in v_amounts:
            for vat_factor in vat_factors:
                for amount in amounts:
                    if vat == round(amount / (1 + vat_factor) * vat_factor, 2):
                        return (amount, vat)
    return (max(amounts), 0)


def extract_date(lines):
    for line in lines:
        for word in line.split():
            d = utils.convert_date4(word)
            if d:
                return d
    return None


def extract_no(lines):
    nos = []
    for line in lines:
        lline = line.lower()
        if ("Seite" in line and "von" in line) or "Verwendungszweck" in line \
                or "in Rechnung" in line:
            continue
        if "rechnungsnr" in lline \
                or "rechnungs-Nr" in lline \
                or "rechnungsnummer" in lline \
                or ("rechnung" in lline and "nr" in lline) \
                or ("rechnung " in lline) \
                or ("rechnung:" in lline) \
                or ("deine rechnung" in lline) \
                or ("belegnummer" in lline):
            for pattern in ["[nN][rR]", "[rR]e.*nummer", "Rechnung",
                            "Belegnummer / Document Number",
                            "Belegnummer"]:
                s1 = re.search(pattern + "[:.– ]*([A-Za-z0-9/_–-]+([0-9/_–-]| (?! ))+)", line)
                if s1 and s1.group(1):
                    # print("line:",line)
                    # print("s1:",s1.group(1))
                    nos.append(s1.group(1))
                    continue
        if "EXP-" in line:  # ERPNext invoices
            s = re.search(r"EXP-[0-9][0-9]-[0-9][0-9]-[0-9]+", line)
            if s and s.group(0):
                nos.append(s.group(0))
                continue
    if not nos:
        return None
    nos.sort(key=lambda s: len(s), reverse=True)
    return nos[0].strip()


def extract_supplier(lines):
    return " ".join(lines[0][0:80].split())


def decode_uft_8(bline):
    try:
        return bline.decode('utf_8')
    except Exception:
        return ""


def pdf_to_text(file, raw=False):
    cmd = ["pdftotext", "-nopgbrk"]
    if raw:
        cmd.append("-raw")
    else:
        cmd.append("-table")
    cmd += ["-enc", "UTF-8"]
    cmd += [file, "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    return [decode_uft_8(bline) for bline in p.stdout]


def ask_if_to_continue(err, msg=""):
    if err:
        title = "Warnung"
        return easygui.ccbox(err + msg, title)  # show a Continue/Cancel dialog
    return True


class PurchaseInvoice(Invoice):
    suppliers = {}

    def extract_order_id(self, str, line):
        if str in line:
            try:
                lsplit = line.split()
                i = lsplit.index(str.split()[-1])
                self.order_id = lsplit[i + 1]
            except:
                pass

    def parse_generic(self, lines, default_account=None, paid_by_submitter=False, is_test=False):
        self.parser = "generic"
        self.extract_items = False
        amount = ""
        self.vat[self.default_vat] = ""
        self.totals[self.default_vat] = ""
        self.shipping = 0.0
        self.date = ""
        self.no = ""
        if not self.supplier:
            self.supplier = ""
        if lines:
            (amount, vat) = extract_amount_and_vat(lines, self.vat_rates)
            self.date = extract_date(lines)
            self.no = extract_no(lines)
            if not self.supplier:
                self.supplier = extract_supplier(lines)
        if lines and amount:
            self.vat[self.default_vat] = vat
            self.totals[self.default_vat] = amount - self.vat[self.default_vat]
            self.shipping = 0.0
            if not is_test:
                if self.check_if_present():
                    return self
        if is_test:
            return self
        suppliers = gui_api_wrapper(Api.api.get_list, "Supplier",
                                    limit_page_length=LIMIT)
        supplier_names = [supp['name'] for supp in suppliers]
        supplier_names.sort()
        supplier_names += ['neu']
        def_supp = self.supplier if self.supplier in supplier_names else "neu"
        def_new_supp = "" if self.supplier in supplier_names else self.supplier
        layout = [[sg.Text('Lieferant')],
                  [sg.OptionMenu(values=supplier_names, k='-supplier-',
                                 default_value=def_supp)],
                  [sg.Text('ggf. neuer Lieferant')],
                  [sg.Input(default_text=def_new_supp,
                            k='-supplier-name-')],
                  [sg.Text('Rechnungsnr.')],
                  [sg.Input(default_text=self.no, k='-no-')],
                  [sg.Text('Datum')],
                  [sg.Input(key='-date-',
                            default_text=utils.show_date4(self.date)),
                   sg.CalendarButton('Kalender', target='-date-',
                                     format='%d.%m.%Y',
                                     begin_at_sunday_plus=1)],
                  [sg.Text('MWSt')],
                  [sg.Input(default_text=str(self.vat[self.default_vat]),
                            k='-vat-')],
                  [sg.Text('Brutto')],
                  [sg.Input(default_text=str(amount), k='-gross-')],
                  [sg.Text('Skonto')],
                  [sg.Input(k='-skonto-')],
                  [sg.Checkbox('Schon selbst bezahlt',
                               default=paid_by_submitter, k='-paid-')],
                  [sg.Text('Kommentar')],
                  [sg.Input(k='-remarks-')],
                  [sg.Button('Speichern')]]
        window1 = sg.Window("Einkaufsrechnung", layout, finalize=True)
        window1.bring_to_front()
        event, values = window1.read()
        # print(event, values)
        window1.close()
        if values:
            if '-supplier-' in values:
                self.supplier = values['-supplier-']
                if self.supplier == 'neu' and '-supplier-name-' in values:
                    self.supplier = values['-supplier-name-']
            if '-no-' in values:
                self.no = values['-no-']
            if '-date-' in values:
                date = utils.convert_date4(values['-date-'])
                if date:
                    self.date = date
            if '-vat-' in values:
                self.vat[self.default_vat] = \
                    utils.read_float(values['-vat-'])
            if '-gross-' in values:
                self.totals[self.default_vat] = \
                    utils.read_float(values['-gross-']) \
                    - self.vat[self.default_vat]
            if '-skonto-' in values and values['-skonto-']:
                self.skonto = utils.read_float(values['-skonto-'])
            if '-paid-' in values and values['-paid-']:
                self.paid_by_submitter = True
            if '-remarks-' in values:
                self.remarks = values['-remarks-']
        else:
            return None
        self.compute_total()
        account = None
        accounts = self.company.leaf_accounts_for_credit
        account_names = [acc['name'] for acc in accounts]
        if default_account:
            for acc in account_names:
                if default_account in acc:
                    account = acc
        if not account:
            pinvs = self.company.purchase_invoices[self.supplier]
            paccs = [pi['expense_account'] \
                     for pi in pinvs if 'expense_account' in pi]
            paccs = list(set(paccs))
            for acc in paccs:
                try:
                    account_names.remove(acc)
                except Exception:
                    pass
            account_names = paccs + account_names
            title = 'Buchungskonto wählen'
            msg = 'Bitte ein Buchungskonto wählen\n'
            account = easygui.choicebox(msg, title, account_names)
            if not account:
                return None
        self.assign_default_e_items({self.default_vat: account})
        return self

    def parse_invoice(self, invoice_json, infile, account=None, paid_by_submitter=False, given_supplier=None,
                      is_test=False, check_dup=True):
        if invoice_json:
            print("Nutze Google invoice parser")
            return self.parse_invoice_json(invoice_json, account, paid_by_submitter, given_supplier, is_test, check_dup)
        print("Nutze internen Parser")
        self.extract_items = False
        lines = pdf_to_text(infile)
        try:
            if lines:
                head = lines[0][0:140]
                if not head[0:10].split():
                    for line in lines[0:10]:
                        if self.company.name != 'Bremer SolidarStrom' and len(line) > 2 and (
                                line[-2] == '£' or line[-3] == '£'):
                            head = "Kornkraft Naturkost GmbH"
                            break
                supps = dict(PurchaseInvoice.suppliers)
                if self.company.name != 'Laden':
                    del supps['Rechnung']
                for supplier, info in supps.items():
                    if supplier in head:
                        self.parser = supplier
                        self.extract_items = self.update_stock
                        if info['raw']:
                            self.raw = True
                            lines = pdf_to_text(infile, True)
                        if 'supplier' in info:
                            self.supplier = info['supplier']
                        else:
                            self.supplier = supplier
                        print("Verwende Rechnungsparser für ", self.supplier)
                        if given_supplier and self.supplier != given_supplier:
                            print("abweichend von PreRechnung: ", given_supplier)
                        self.multi = info['multi']
                        purchase_invoice_parser = PurchaseInvoiceParser(self, info['parser'], lines)
                        if not purchase_invoice_parser.set_purchase_info():
                            return None
                        return self
        except Exception as e:
            # print(e)
            if self.update_stock:
                raise e
            elif not is_test:
                # raise e
                print(e)
                print("Rückfall auf Standard-Rechnungsbehandlung")
        print("Verwende generischen Rechnungsparser")
        self.supplier = given_supplier
        return self.parse_generic(lines, account, paid_by_submitter, is_test)

    def apply_info_changes(self, diff, new_data_model):
        for key in diff.keys():
            value = diff[key]
            if key == insert:
                for new_key in value.keys():
                    if new_key == 'supplier':
                        self.supplier = value[new_key]
                    elif new_key == 'taxes':
                        for tax_info in value[new_key]:
                            self.vat[tax_info['rate']] = tax_info['tax_amount']
                            self.total_vat += tax_info['tax_amount']
                        if self.total_vat == 0 and self.default_vat:
                            self.vat[self.default_vat] = 0
                    elif new_key == 'items':
                        for item in value[new_key]:
                            s_item = SupplierItem(self)
                            s_item.description = item.get('description')
                            s_item.qty = item.get('qty')
                            s_item.qty_unit = item.get('uom')
                            s_item.rate = item.get('rate')
                            s_item.amount = item.get('amount')
                            self.items.append(s_item)
                    elif new_key == 'total':
                        self.totals[self.default_vat] = value[new_key]
                    elif new_key == 'grand_total':
                        self.gross_total = value[new_key]
                    elif new_key == 'bill_no':
                        self.bill_no = value[new_key]
                    elif new_key == 'order_id':
                        self.order_id = value[new_key]
                    elif new_key == 'posting_date':
                        self.posting_date = value[new_key]
                    elif new_key == 'shipping':
                        self.shipping = value[new_key]
            elif key == delete:
                for deleted_key in value.keys():
                    if deleted_key == 'supplier':
                        self.supplier = None
                    elif deleted_key == 'taxes':
                        self.vat[self.default_vat] = 0
                        self.total_vat = 0
                    elif deleted_key == 'items':
                        self.items = []
                        if new_data_model and new_data_model.get('items'):
                            for item in new_data_model.get('items'):
                                s_item = SupplierItem(self)
                                s_item.description = item.get('description')
                                s_item.qty = item.get('qty')
                                s_item.qty_unit = item.get('uom')
                                s_item.rate = item.get('rate')
                                s_item.amount = item.get('amount')
                                self.items.append(s_item)
                    elif deleted_key == 'total':
                        self.totals[self.default_vat] = 0
                    elif deleted_key == 'grand_total':
                        self.gross_total = 0
                    elif deleted_key == 'bill_no':
                        self.bill_no = None
                    elif deleted_key == 'order_id':
                        self.order_id = None
                    elif deleted_key == 'posting_date':
                        self.posting_date = None
                    elif deleted_key == 'shipping':
                        self.shipping = 0
            else:
                if key == 'supplier':
                    self.supplier = value[1]
                elif key == 'taxes':
                    self.total_vat = 0
                    if type(value) is list:
                        for tax_info in value[1]:
                            self.vat[tax_info['rate']] = tax_info['tax_amount']
                            self.total_vat += tax_info['tax_amount']
                    elif new_data_model:
                        for tax_info in new_data_model['taxes']:
                            self.vat[tax_info['rate']] = tax_info['tax_amount']
                            self.total_vat += tax_info['tax_amount']
                    if self.total_vat == 0 and self.default_vat:
                        self.vat[self.default_vat] = 0
                elif key == 'items':
                    self.items = []
                    if new_data_model and new_data_model.get('items'):
                        for item in new_data_model.get('items'):
                            s_item = SupplierItem(self)
                            s_item.description = item.get('description')
                            s_item.qty = item.get('qty')
                            s_item.qty_unit = item.get('uom')
                            s_item.rate = item.get('rate')
                            s_item.amount = item.get('amount')
                            self.items.append(s_item)
                elif key == 'total':
                    self.totals[self.default_vat] = value[1]
                elif key == 'grand_total':
                    self.gross_total = value[1]
                elif key == 'bill_no':
                    self.bill_no = value[1]
                elif key == 'order_id':
                    self.order_id = value[1]
                elif key == 'posting_date':
                    self.posting_date = value[1]
                elif key == 'shipping':
                    self.shipping = value[1]

    def edit_data_model_manually(self, data_model, infile):
        diff = None
        new_data_model = None

        if utils.running_linux():
            os.system("evince " + infile + " &")

        def store_json(json_data: dict):
            nonlocal diff, new_data_model
            new_data_model = json_data
            diff = jsondiff.diff(data_model, json_data, syntax='symmetric')

        jsoneditor.editjson(data_model, callback=store_json)

        if diff:
            self.apply_info_changes(diff, new_data_model)

        return new_data_model

    def parse_invoice_json(self, invoice_json, default_account=None, paid_by_submitter=False, given_supplier=None,
                           is_test=False, check_dup=True):
        try:
            purchase_invoice_parser = PurchaseInvoiceGoogleParser(self, invoice_json, given_supplier)
            purchase_invoice_parser.set_purchase_info()
            self.compute_total()
        except Exception as e:
            if self.update_stock:
                raise e
            elif not is_test:
                print(e)
                print("Rückfall auf Standard-Rechnungsbehandlung")

        if not check_dup:
            if not self.supplier:
                self.supplier = "???"
            if not self.date:
                self.date = "1970-01-01"
            if not self.no:
                self.no = "???"
            if not self.vat[self.default_vat]:
                self.vat[self.default_vat] = 0.0
            if not self.gross_total:
                self.gross_total = 0.0
        if not check_dup or (
                self.supplier and self.date and self.no and self.vat[self.default_vat] and self.gross_total):
            self.compute_total()
            return self

        if is_test or self.check_if_present(check_dup):
            self.compute_total()
            return self

        if not self.supplier:
            print("Lieferant nicht erkannt")
        if not self.date:
            print("Datum nicht erkannt")
        if not self.no:
            print("Rechnungsnr. nicht erkannt")
        if not self.vat[self.default_vat]:
            print("MWSt nicht erkannt")
        if not self.gross_total:
            print("Bruttobetrag nicht erkannt")
        print("Rückfall auf manuelle Eingabe")

        suppliers = gui_api_wrapper(Api.api.get_list, "Supplier", limit_page_length=LIMIT)
        supplier_names = [supp['name'] for supp in suppliers]
        supplier_names.sort()
        supplier_names += ['neu']
        def_supp = self.supplier if self.supplier in supplier_names else "neu"
        def_new_supp = "" if self.supplier in supplier_names else self.supplier
        layout = [
            [sg.Text('Lieferant')],
            [sg.OptionMenu(values=supplier_names, k='-supplier-',
                           default_value=def_supp)],
            [sg.Text('ggf. neuer Lieferant')],
            [sg.Input(default_text=def_new_supp,
                      k='-supplier-name-')],
            [sg.Text('Rechnungsnr.')],
            [sg.Input(default_text=self.no, k='-no-')],
            [sg.Text('Datum')],
            [sg.Input(key='-date-',
                      default_text=utils.show_date4(self.date)),
             sg.CalendarButton('Kalender', target='-date-',
                               format='%d.%m.%Y',
                               begin_at_sunday_plus=1)],
            [sg.Text('MWSt')],
            [sg.Input(default_text=str(self.vat[self.default_vat]),
                      k='-vat-')],
            [sg.Text('Brutto')],
            [sg.Input(default_text="", k='-gross-')],
            [sg.Text('Skonto')],
            [sg.Input(k='-skonto-')],
            [sg.Checkbox('Schon selbst bezahlt',
                         default=paid_by_submitter, k='-paid-')],
            [sg.Text('Kommentar')],
            [sg.Input(k='-remarks-')],
            [sg.Button('Speichern')]
        ]
        window1 = sg.Window("Einkaufsrechnung", layout, finalize=True)
        window1.bring_to_front()
        event, values = window1.read()
        window1.close()
        if values:
            if '-supplier-' in values:
                self.supplier = values['-supplier-']
                if self.supplier == 'neu' and '-supplier-name-' in values:
                    self.supplier = values['-supplier-name-']
            if '-no-' in values:
                self.no = values['-no-']
            if '-date-' in values:
                date = utils.convert_date4(values['-date-'])
                if date:
                    self.date = date
            if '-vat-' in values:
                self.vat[self.default_vat] = utils.read_float(values['-vat-'])
            if '-gross-' in values:
                self.totals[self.default_vat] = utils.read_float(values['-gross-']) - self.vat[self.default_vat]
            if '-skonto-' in values and values['-skonto-']:
                self.skonto = utils.read_float(values['-skonto-'])
            if '-paid-' in values and values['-paid-']:
                self.paid_by_submitter = True
            if '-remarks-' in values:
                self.remarks = values['-remarks-']
        else:
            return None
        self.compute_total()
        account = None
        accounts = self.company.leaf_accounts_for_credit
        account_names = [acc['name'] for acc in accounts]
        if default_account:
            for acc in account_names:
                if default_account in acc:
                    account = acc
        if not account:
            pinvs = self.company.purchase_invoices[self.supplier]
            paccs = [pi['expense_account'] for pi in pinvs if 'expense_account' in pi]
            paccs = list(set(paccs))
            for acc in paccs:
                try:
                    account_names.remove(acc)
                except Exception:
                    pass
            account_names = paccs + account_names
            title = 'Buchungskonto wählen'
            msg = 'Bitte ein Buchungskonto wählen\n'
            account = easygui.choicebox(msg, title, account_names)
            if not account:
                return None
        self.assign_default_e_items({self.default_vat: account})
        return self

    def compute_total(self):
        self.total = sum([t for v, t in self.totals.items()])
        self.total_vat = sum([t for v, t in self.vat.items()])
        self.gross_total = self.total + self.total_vat
        for vat in self.vat_rates:
            if (round(self.totals[vat] * vat / 100.0 + 0.00001, 2) - self.vat[vat]):
                print(self.no, " Abweichung bei MWSt! ",
                      vat, "% von", self.totals[vat], " = ",
                      round(self.totals[vat] * vat / 100.0 + 0.00001, 2),
                      ". MWSt auf der Rechnung: ",
                      self.vat[vat])

    def assign_default_e_items(self, accounts):
        self.e_items = []
        for vat in self.vat_rates:
            if vat in accounts.keys() and self.totals[vat] is not None:
                self.e_items.append(
                    {'item_code': settings.DEFAULT_ITEM_CODE,
                     'qty': 1,
                     'rate': self.totals[vat],
                     'cost_center': self.company.cost_center}
                )
        if not self.update_stock and self.vat_rates:
            self.e_items[0]['expense_account'] = accounts[self.vat_rates[0]]

    def create_taxes(self):
        self.taxes = []
        for vat, account in self.company.taxes.items():
            if self.vat[vat]:
                self.taxes.append({'add_deduct_tax': 'Add',
                                   'charge_type': 'Actual',
                                   'account_head': account,
                                   'cost_center': self.company.cost_center,
                                   'description': VAT_DESCRIPTION,
                                   'tax_amount': self.vat[vat]})

    def create_doc(self):
        self.doc = {
            'doctype': 'Purchase Invoice',
            'company': self.company.name,
            'supplier': self.supplier,
            'title': self.supplier.split()[0] + " " + self.no,
            'project': self.project,
            'bill_no': self.no,
            'order_id': self.order_id,
            'posting_date': self.date,
            'remarks': self.remarks,
            'paid_by_submitter': self.paid_by_submitter,
            'set_posting_time': 1,
            'credit_to': self.company.payable_account,
            'naming_series': STANDARD_NAMING_SERIES_PINV,
            'buying_price_list': STANDARD_PRICE_LIST,
            'taxes': self.taxes,
            'items': self.e_items,
            'update_stock': 1 if self.update_stock else 0,
            'cost_center': self.company.cost_center
        }
        if self.skonto:
            self.doc['apply_discount_on'] = 'Grand Total'
            self.doc['discount_amount'] = self.skonto
        if self.shipping:
            self.doc['taxes'].append({'add_deduct_tax': 'Add',
                                      'charge_type': 'Actual',
                                      'account_head': DELIVERY_COST_ACCOUNT,
                                      'description': DELIVERY_COST_DESCRIPTION,
                                      'tax_amount': self.shipping})

    def check_total(self, check_dup=True):
        err = ""
        computed_total = self.shipping + sum([item.rate * item.qty for item in self.items])
        if check_dup and abs(self.total - computed_total) > 0.005:
            err = "Abweichung! Summe in Rechnung: {0}, Summe der Posten: {1}".format(self.total, computed_total)
            err += "\nDies kann noch durch Preisanpassungen korrigiert werden.\n"
        return err

    def check_duplicates(self):
        err = ""
        items = defaultdict(list)
        for item in self.e_items:
            items[item['item_code']].append(item)  # group items by item_code
        for key in items.keys():
            if key != MATERIAL_ITEM_CODE and len(items[key]) > 1:  # if there is more than one item in a group
                err += "Ein Artikel ist mehrfach in der Rechnung vorhanden:\n"
                err += "\n".join(map(str, items[key]))
                err += "\nVielleicht ist die Zuordnung falsch und dies sollten zwei verschiedene Artikel sein?"
        if err:
            err += "\n\nTrotzdem Rechnung erstellen?"
        return err

    def check_if_present(self, check_dup=True):
        if not check_dup or not self.no or not self.no.strip():
            return False
        upload = None
        invs = gui_api_wrapper(Api.api.get_list, "Purchase Invoice",
                               filters={'bill_no': self.no, 'status': ['!=', 'Cancelled']})
        if not invs and self.order_id:
            invs1 = gui_api_wrapper(Api.api.get_list, "Purchase Invoice",
                                    filters={'order_id': self.order_id, 'status': ['!=', 'Cancelled']})
            if invs1:
                easygui.msgbox(
                    "Einkaufsrechnung {} ist möglicherweise schon als {} in ERPNext eingetragen worden. Möglicherweise ist der Auftrag aber auch in mehrere Rechnungen gesplittet worden.".format(
                        self.no, invs1[0]['name']))
        if invs:
            # attach the present PDF to invoice with same bill_no
            upload = self.upload_pdfs(invs[0]['name'])
            if upload:
                upload = "Aktuelle Rechnung wurde dort angefügt."
            easygui.msgbox("Einkaufsrechnung {} ist schon als {} in ERPNext eingetragen worden. {}".format(self.no,
                                                                                                           invs[0][
                                                                                                               'name'],
                                                                                                           upload))
            self.is_duplicate = True
            self.doc = invs[0]
            return True
        return False

    def __init__(self, update_stock=False):
        # do not call super().__init__ here,
        # because there is no doc in ERPNext yet
        self.update_stock = update_stock
        self.order_id = None
        self.company_name = sg.UserSettings()['-company-']
        # print("Company: ",self.company_name)
        self.company = company.Company.get_company(self.company_name)
        # print("Company: ",self.company.name)
        self.remarks = None
        self.project = None
        self.paid_by_submitter = False
        self.total = 0
        self.gross_total = 0
        self.default_vat = self.company.default_vat
        self.vat_rates = list(self.company.taxes.keys())
        self.vat = {}
        self.totals = {}
        for vat in self.vat_rates:
            self.vat[vat] = 0.0
            self.totals[vat] = 0.0
        self.multi = False
        self.infiles = []
        self.is_duplicate = False
        self.e_items = []
        self.raw = False
        self.skonto = 0
        self.parser = None

    def merge(self, inv):
        if not inv:
            return
        if self.company_name != inv.company_name:
            print("Kann nicht Rechnungen verschiedener Firmen verschmelzen: {} {}".format(self.company_name,
                                                                                          inv.company_name))
        if self.supplier != inv.supplier:
            print("Kann nicht Rechnungen verschiedener Lieferanten verschmelzen: {} {}".format(self.supplier,
                                                                                               inv.supplier))
        self.no += " " + inv.no
        self.taxes += inv.taxes
        self.e_items += inv.e_items
        self.infiles += inv.infiles
        self.shipping += inv.shipping
        if self.remarks:
            self.remarks += inv.remarks
        else:
            self.remarks = inv.remarks
        self.total += inv.total
        self.gross_total += inv.gross_total
        self.total_vat += inv.total_vat
        # note that self.compute_total() would give a wrong result here,
        # because self.totals and self.vat are not merged

    # for testing
    @classmethod
    def parse_and_dump(cls, infile, update_stock, account=None, paid_by_submitter=False):
        inv = PurchaseInvoice(update_stock).parse_invoice(infile, account, paid_by_submitter)
        pprint(vars(inv))
        pprint(list(map(lambda x: pprint(vars(x)), inv.items)))

    @classmethod
    def read_and_transfer(cls, invoice_json, infile, update_stock, account=None, paid_by_submitter=False, project=None,
                          supplier=None, check_dup=True):
        one_more = True
        inv = None
        while one_more:
            one_more = False
            inv_new = PurchaseInvoice(update_stock).read_pdf(invoice_json, infile, account, paid_by_submitter, supplier,
                                                             check_dup=check_dup)
            if (inv is None) and inv_new and inv_new.is_duplicate:
                return inv_new
            if inv_new and not inv_new.is_duplicate:
                inv_new.merge(inv)
                inv = inv_new
                if inv.total < 0:
                    one_more = True
                    easygui.msgbox('Negativer Gesamtbetrag. Eine weitere Rechnung muss eingelesen werden.')
                elif inv.multi:
                    title = "Mit einer weiteren Rechnung verschmelzen?"
                    one_more = easygui.buttonbox(title, title, ["Ja", "Nein"]) == "Ja"
                if one_more:
                    infile = utils.get_file('Weitere Einkaufsrechnung als PDF')
        if inv and not inv.is_duplicate:
            inv.project = project
            inv = inv.send_to_erpnext(not check_dup)
        if not inv:
            print("Keine Einkaufsrechnung angelegt")
        return inv

    def read_pdf(self, invoice_json, infile, account=None, paid_by_submitter=False, supplier=None, check_dup=True):
        self.infiles = [infile]
        if not self.parse_invoice(invoice_json, infile, account, paid_by_submitter, supplier, check_dup=check_dup):
            return None
        print("Prüfe auf doppelte Rechung")
        if self.check_if_present(check_dup):
            return self
        if self.extract_items:
            Api.load_item_data()
            print("Hole Lagerdaten")
            yesterd = utils.yesterday(self.date)
            self.e_items = [item.process_item(self.supplier, yesterd, check_dup) for item in self.items]  # if item.description]
            if None in self.e_items:
                print(
                    "Nicht alle Artikel wurden eingetragen.\n Deshalb kann keine Einkaufsrechnung in ERPNext erstellt werden.")
                return None
            if not ask_if_to_continue(self.check_total(check_dup), "Fortsetzen?"):
                return None
            if not ask_if_to_continue(self.check_duplicates()):
                return None
        elif not self.e_items:
            self.assign_default_e_items(SOMIKO_ACCOUNTS)
        self.create_taxes()
        return self

    def summary(self):
        if not self.doc:
            self.create_doc()
        fields = [('Rechnungsnr.', 'bill_no'),
                  ('Unternehmen', 'company'),
                  ('Lieferant', 'supplier'),
                  ('Datum', 'posting_date'),
                  ('Bemerkungen', 'remarks'),
                  ('schon bezahlt', 'paid_by_submitter'),
                  ('Gegenkonto', 'credit_to'),
                  ('Lagerhaltung', 'update_stock')]
        lines = ["{}: {}".format(d, self.doc[f]) for (d, f) in fields]
        lines.append('Artikel:')
        total = 0.0
        for item in self.doc['items']:
            amount = item['qty'] * item['rate']
            total += amount
            if Api.items_by_code:
                try:
                    item_name = Api.items_by_code[item['item_code']]['item_name']
                except Exception:
                    item_name = ""
            else:
                item_name = ""
            if 'expense_account' in item:
                expense_account = item['expense_account']
            else:
                expense_account = ""
            lines.append("  {}x {} {} à {:.2f}€ = {:.2f}€ auf {}".format(item['qty'],
                                                                         item['item_code'],
                                                                         item_name,
                                                                         item['rate'],
                                                                         amount,
                                                                         expense_account))
        lines.append('Steuern und Kosten:')
        for tax in self.doc['taxes']:
            total += tax['tax_amount']
            lines.append("  {:.2f}€ auf {}".format(tax['tax_amount'],
                                                   tax['account_head']))
        lines.append("Summe: {:.2f}€".format(total))
        lines = [line[0:70] for line in lines]
        return "\n".join(lines)

    def upload_pdfs(self, inv_name=None):
        print("Übertrage PDF der Rechnung")
        if not inv_name:
            inv_name = self.doc['name']
        upload = None
        for infile in self.infiles:
            upload = gui_api_wrapper(Api.api.read_and_attach_file,
                                     "Purchase Invoice", inv_name,
                                     infile, True)
        return upload

    def send_to_erpnext(self, silent=False):
        print("Stelle ERPNext-Rechnung zusammen")
        self.create_doc()
        Api.create_supplier(self.supplier)
        # print(self.doc)
        print("Übertrage ERPNext-Rechnung")
        if not self.insert():
            return None
        # now we have a doc and can init class Invoice
        super().__init__(self.doc, False)
        # print(self.doc)
        self.company.purchase_invoices[self.doc['supplier']].append(self.doc)
        upload = self.upload_pdfs()
        # currently, we can only link to the last PDF
        self.doc['supplier_invoice'] = upload['file_url']
        self.update()
        # enter purchased material separately into stock, if needed
        stock.purchase_invoice_into_stock(self.doc['name'])
        # fallback on manual creation of invoice if necessary
        if self.update_stock and self.parser == "generic":
            easygui.msgbox(
                "Einkaufsrechnung {0} wurde als Entwurf an ERPNext übertragen. Bitte Artikel in ERPNext manuell eintragen. Künftig könnte dies ggf. automatisiert werden.".format(
                    self.no))
            return self
        if silent:
            return self
        choices = ["Sofort buchen", "Später buchen"]
        msg = "Einkaufsrechnung {0} wurde als Entwurf an ERPNext übertragen:\n{1}\n\n".format(self.doc['title'],
                                                                                              self.summary())
        title = "Rechnung {}".format(self.no)
        filters = {'company': self.company_name,
                   'party': self.supplier,
                   'docstatus': 1,
                   'unallocated_amount': self.gross_total}
        py = gui_api_wrapper(Api.api.get_list,
                             "Payment Entry",
                             filters=filters,
                             limit_page_length=1)
        if py:
            py = doc.Doc(name=py[0]['name'], doctype='Payment Entry')
            bt = None
        else:
            bt = bank.BankTransaction.find_bank_transaction(self.company_name,
                                                            -self.gross_total,
                                                            self.no)
        if py:
            msg += "\n\nZugehörige Anzahlung gefunden: {}\n". \
                format(py.name)
            choices[0] = "Sofort buchen und zahlen"
        if bt:
            msg += "\n\nZugehörige Bank-Transaktion gefunden: {}\n". \
                format(bt.description)
            choices[0] = "Sofort buchen und zahlen"
        if easygui.buttonbox(msg, title, choices) in \
                ["Sofort buchen", "Sofort buchen und zahlen"]:
            print("Buche Rechnung")
            if py:
                self.use_advance_payment(py)
            self.submit()
            if bt:
                self.payment(bt)
        return self


heckert_info = {'parser': 'heckert',
                'raw': False, 'multi': False,
                'supplier': 'Heckert Solar GmbH'}

PurchaseInvoice.suppliers = {
    'Krannich Solar GmbH & Co KG': {
        'parser': 'krannich',
        'raw': False, 'multi': False
    },
    'pvXchange Trading GmbH': {
        'parser': 'pvxchange',
        'raw': True, 'multi': False
    },
    'Schlußrechnung': heckert_info,
    'Vorausrechnung': heckert_info,
    'Teilrechnung': heckert_info,
    'SOLARWATT': {
        'parser': 'generic',
        'raw': False, 'multi': False,
        'supplier': 'Solarwatt GmbH'
    },
    'Seite': {
        'parser': 'wagner',
        'raw': False, 'multi': False,
        'supplier': 'Wagner Solar'
    },
    'Rechnung': {
        'parser': 'nkk',
        'raw': False, 'multi': False,
        'supplier': 'Naturkost Kontor Bremen Gmbh'
    },
    'Kornkraft Naturkost GmbH': {
        'parser': 'kornkraft',
        'raw': False, 'multi': True
    }
}
