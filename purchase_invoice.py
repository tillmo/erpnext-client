#!/usr/bin/python3

from settings import WAREHOUSE, STANDARD_PRICE_LIST, STANDARD_ITEM_GROUP, STANDARD_NAMING_SERIES_PINV, VAT_DESCRIPTION, DELIVERY_COST_ACCOUNT, DELIVERY_COST_DESCRIPTION, NKK_ACCOUNTS, KORNKRAFT_ACCOUNTS, SOMIKO_ACCOUNTS

import utils
import PySimpleGUI as sg
import easygui
import subprocess
import re
from api import Api, WAREHOUSE, LIMIT
from api_wrapper import gui_api_wrapper
import settings
import doc
import company
import bank
from invoice import Invoice
from collections import defaultdict
import random
import string
import csv
from pprint import pprint

# extract amounts of form xxx,xx from string
def extract_amounts(s):
    amounts = re.findall(r"([0-9]+,[0-9][0-9])",s)
    return list(map(lambda s: float(s.replace(",",".")),amounts))

# try to extract gross amount and vat from an invoice
def extract_amount_and_vat(lines,vat_rates):
    amounts = extract_amounts(" ".join(lines))
    if not amounts:
        return (None,None)
    amount = max(amounts)
    vat_factors = [vr / 100.0 for vr in vat_rates]
    for vat_factor in vat_factors:
        vat = round(amount / (1+vat_factor) * vat_factor,2)
        if vat in amounts:
            return(amount,vat)
    vat_lines = [l for l in lines if "mwst" in l.lower()]
    for line in vat_lines:
        v_amounts = extract_amounts(line)
        for vat in v_amounts:
            for vat_factor in vat_factors:
                for amount in amounts:
                    if vat == round(amount / (1+vat_factor) * vat_factor,2):
                        return(amount,vat)
    return (max(amounts),0)

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
        if ("Seite" in line and "von" in line) or "Verwendungszweck" in line\
           or "in Rechnung" in line:
            continue
        if "rechnungsnr" in lline\
          or "rechnungs-Nr" in lline\
          or "rechnungsnummer" in lline\
          or ("rechnung" in lline and "nr" in lline)\
          or ("rechnung " in lline)\
          or ("rechnung:" in lline)\
          or ("deine rechnung" in lline)\
          or ("belegnummer" in lline):
            for pattern in ["[nN][rR]","[rR]e.*nummer","Rechnung",
                            "Belegnummer / Document Number",
                            "Belegnummer"]:
                s1 = re.search(pattern+"[:.– ]*([A-Za-z0-9/_–-]+([0-9/_–-]| (?! ))+)",line)
                if s1 and s1.group(1):
                    #print("line:",line)
                    #print("s1:",s1.group(1))
                    nos.append(s1.group(1))
                    continue
        if "EXP-" in line: # ERPNext invoices
            s = re.search(r"EXP-[0-9][0-9]-[0-9][0-9]-[0-9]+",line)
            if s and s.group(0):
                nos.append(s.group(0))
                continue            
    if not nos:        
        return None
    nos.sort(key=lambda s: len(s),reverse=True)
    return nos[0].strip()

def extract_supplier(lines):
    return " ".join(lines[0][0:80].split())

def decode_uft_8(bline):
    try:
        return bline.decode('utf_8')
    except Exception:
        return ""

def pdf_to_text(file,raw=False):
    cmd = ["pdftotext","-nopgbrk"]
    if raw:
        cmd.append("-raw")
    else:    
        cmd.append("-table")
    cmd += ["-enc","UTF-8"]
    cmd += [file,"-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    return [decode_uft_8(bline) for bline in p.stdout]

def ask_if_to_continue(err,msg=""):
    if err:
        title = "Warnung"
        return easygui.ccbox(err+msg, title) # show a Continue/Cancel dialog
    return True    

class SupplierItem:
    def __init__(self,inv):
        self.purchase_invoice = inv

    def search_item(self,supplier):
        if self.item_code:
            if supplier in Api.item_code_translation:
                trans_table_supplier = Api.item_code_translation[supplier]
                if self.item_code in trans_table_supplier:
                    e_item_code =  trans_table_supplier[self.item_code]
                    e_item = Api.items_by_code[e_item_code]
                    return e_item
        # look for most similar e_items
        sim_items = []
        for e_code, e_item in Api.items_by_code.items():
            sim_items.append((utils.similar(e_item['item_name'],
                                            self.description),
                              e_item))
        top_items = sorted(sim_items,reverse=True,key=lambda x:x[0])[0:20]
        #print(top_items)
        texts = ['Neuen Artikel anlegen']
        texts += [i[1]['item_code']+' '+i[1]['item_name'] for i in top_items]
        title = "Artikel wählen"
        msg = "Artikel in Rechnung:\n{0}\n\n".format(self.long_description)
        msg += "Bitte passenden Artikel in ERPNext auswählen:"
        choice = easygui.choicebox(msg, title, texts)
        if choice:
            choice = texts.index(choice)
        if choice:
            e_item = top_items[choice-1][1]
            if self.item_code:
                doc = gui_api_wrapper(Api.api.get_doc,'Item',
                                      e_item['item_code'])
                doc['supplier_items'].append(\
                     { 'supplier': supplier,
                       'supplier_part_no' : self.item_code})
                #print(doc['supplier_items'])
                gui_api_wrapper(Api.api.update,doc)
            return e_item
        else:
            title = "Neuen Artikel in ERPNext eintragen"
            msg = self.long_description+"\n"
            if self.item_code:
                msg += "Code Lieferant: "+self.item_code+"\n"
            msg += "Einzelpreis: {0:.2f}€".format(self.rate)
            msg += "\n\nDiesen Artikel eintragen?"
            if easygui.ccbox(msg, title):
                item_code = "new"+''.join(random.choices(\
                                string.ascii_uppercase + string.digits, k=8))
                company_name = self.purchase_invoice.company_name
                e_item = {'doctype' : 'Item',
                          'item_code' : item_code,
                          'item_name' : self.description,
                          'description' : self.long_description,
                          'item_group' : STANDARD_ITEM_GROUP,
                          'item_defaults': [{'company': company_name,
                                             'default_warehouse': WAREHOUSE}],
                          'stock_uom' : self.qty_unit}  
                e_item = gui_api_wrapper(Api.api.insert,e_item)
                return e_item
        return None

    def add_item_price(self,e_item,rate,uom,date):
        docs = gui_api_wrapper(Api.api.get_list,'Item Price',
                               filters={'item_code': e_item['item_code']})
        if docs:
            doc = gui_api_wrapper(Api.api.get_doc,'Item Price',docs[0]['name'])
            if abs(float(doc['price_list_rate'])-rate)>0.0005:
                title = "Preis anpassen?"
                msg = "Artikel: {0}\nAlter Preis: {1}\nNeuer Preis: {2:.2f}".\
                      format(e_item['description'],doc['price_list_rate'],rate)
                msg += "\n\nPreis anpassen?"
                if easygui.ccbox(msg, title):
                    doc['price_list_rate'] = rate
                    gui_api_wrapper(Api.api.update,doc)
        else:
            price = {'doctype' : 'Item Price',
                     'item_code' : e_item['item_code'],
                     'selling' : True,
                     'buying' : True,
                     'price_list' : STANDARD_PRICE_LIST,
                     'valid_from' : date,
                     'uom' : uom,
                     'price_list_rate' : rate}
            #print(price,e_item)
            doc = gui_api_wrapper(Api.api.insert,price)
            #print(doc)

    def process_item(self,supplier,date):
        e_item = self.search_item(supplier)
        if e_item:
            self.add_item_price(e_item,self.rate,self.qty_unit,date)
            return {'item_code' : e_item['item_code'],
                    'qty' : self.qty,
                    'rate' : self.rate,
                    'desc' : self.description}
        else:
            return None
        
class PurchaseInvoice(Invoice):
    suppliers = {}
    @classmethod
    def get_amount_krannich(cls,lines):
        return sum(map(lambda line: utils.read_float(line[-9:-1]),lines))
    
    def parse_krannich(self,lines):
        items = []
        item = []
        for line in lines:
            if line[0].isdigit():
                items.append(item)
                item = [line]
            else:
                item.append(line)
        items.append(item)
        self.date = None
        self.no = None
        for line in items[0]:
            if "Rechnung" in line:
                self.no = line.split()[1]
                self.date = utils.convert_date4(line.split()[2])
            elif "Anzahlungsrechnung" in line:
                print("Dies ist eine Anzahlungsrechnung")
                return None
        self.items = []
        self.shipping = 0
        rounding_error = 0
        if self.update_stock:
            mypos = 0
            for item_lines in items[1:]:
                #print("***",item_lines)
                item_str = item_lines[0]
                clutter = ['Einzelpreis','Krannich','IBAN','Rechnung','Übertrag']
                s_item = SupplierItem(self)
                long_description_lines = \
                    [l for l in item_lines[1:] \
                       if utils.no_substr(clutter,l) and l.strip()]
                s_item.description = " ".join(long_description_lines[0][0:82].split())
                s_item.long_description = ""
                for l in long_description_lines:
                    if "Zwischensumme" in l:
                        break
                    s_item.long_description += l
                pos = int(item_str[0:7].split()[0])
                if pos>1000:
                    break
                #if not (pos in [mypos,mypos+1,mypos+2]):
                #    break
                if "Vorkasse" in s_item.description:
                    continue
                mypos = pos
                s_item.item_code = item_str.split()[1]
                q=re.search("([0-9]+) *([A-Za-z]+)",item_str[73:99])
                if not q:
                    continue
                s_item.qty = int(q.group(1))
                s_item.qty_unit = q.group(2)
                price = utils.read_float(item_str[130:142].split()[0])
                try:
                    discount = utils.read_float(item_str[142:152].split()[0])
                except Exception:
                    discount = 0
                s_item.amount = utils.read_float(item_str[157:].split()[0])
                if s_item.qty_unit=="Rol":
                    try:
                        r1 = re.search('[0-9]+ *[mM]', s_item.description)
                        r2 = re.search('[0-9]+', r1.group(0))
                        s_item.qty_unit = "Meter"
                        s_item.qty = int(r2.group(0))
                    except Exception:
                        pass
                s_item.rate = round(s_item.amount/s_item.qty,2)
                rounding_error += s_item.amount-s_item.rate*s_item.qty
                self.items.append(s_item)
                #print("--->",s_item)
        vat_line = ""
        for i in range(-1,-len(items),-1):
            vat_lines = [line for line in items[i] if 'MwSt' in line]
            if vat_lines:
                vat_line = vat_lines[0]
                if self.update_stock:
                    self.shipping = PurchaseInvoice.get_amount_krannich\
                        ([line for line in items[i]\
                           if 'Insurance' in line or 'Freight' in line\
                               or 'Neukundenrabatt' in line])
                break
        self.shipping += rounding_error
        self.totals[self.default_vat] = utils.read_float(vat_line[146:162])
        self.vat[self.default_vat] = PurchaseInvoice.get_amount_krannich([vat_line])
        self.compute_total()
        return self

    def parse_pvxchange(self,lines):
        items = []
        item = []
        preamble = True
        self.date = None
        self.no = None
        for line in lines:
            words = line.split()
            for i in [1,2]:
                if len(words)>i:
                    d = utils.convert_date4(words[i])
                    if d:
                        self.date = d
            if line[0:8] == "Rechnung":
                if len(words)>1:
                    self.no = words[2]
            if preamble:
                if len(line)>=4 and line[0:4]=="Pos.":
                    preamble = False
                continue
            if len(line)>=5 and line[0:5]=="Seite":
                preamble = True
                continue
            try:
                pos_no = int(words[0])
            except Exception:
                pos_no = -1
            if pos_no == 28219:
                break
            if pos_no>=0 or 'Nettosumme' in line:
                items.append(item)
                item = [line]
            else:
                item.append(line)
        items.append(item)
        self.items = []
        self.shipping = 0.0
        if self.update_stock:
            mypos = 0
            for item_lines in items[1:-1]:
                try:
                    parts = " ".join(map(lambda s: s.strip(),item_lines)).split()
                    s_item = SupplierItem(self)
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
                    s_item.item_code = parts[ind+1]
                except Exception:
                    s_item.item_code = None
                if s_item.description.strip()=="Transportkosten":
                    self.shipping = s_item.amount
                    continue
                if not (s_item.description=="Selbstabholer" and s_item.amount==0.0):
                    self.items.append(s_item)
        for i in range(-1,-5,-1):
            try:
                vat_line = [line for line in items[i] if 'MwSt' in line][0]
                total_line = [line for line in items[i] if 'Nettosumme' in line][0]
                break
            except Exception:
                pass
        self.vat[self.default_vat] = utils.read_float(vat_line.split()[-2])
        self.totals[self.default_vat] = utils.read_float(total_line.split()[-2])
        self.compute_total()
        return self

    @classmethod
    def get_amount_heckert(cls,lines):
        return sum(map(lambda line: utils.read_float(line[-12:-4]),lines))

    def parse_heckert(self,lines):
        items = []
        item = []
        preamble = True
        self.date = None
        self.no = None
        for line in lines:
            words = line.split()
            #print(words)
            if "Belegdatum" in line:
                d = utils.convert_date4(words[-1])
                if d:
                    self.date = d
                    #print("Date",d)
            if "Auftrag " in line:
                self.order_id = line[120:].split()[0]
            if "Belegnummer / Document Number" in line:
                self.no = words[-1]
                #print("No.",self.no)
            if words and words[0] and words[0][0].isdigit():
                #print(words)
                items.append(item)
                item = [line]
            else:
                item.append(line)
        items.append(item)
        #print(items)
        self.items = []
        self.shipping = 0.0
        rounding_error = 0
        if self.update_stock:
            mypos = 0
            for item_lines in items[1:]:
                #print(item_lines)
                item_str = item_lines[0]
                #print("str:",item_str)
                try:
                    pos = int(item_str.split()[0])
                except Exception:
                    continue
                #print("pos",pos)
                if pos>=28100:
                    continue
                clutter = ['Rabatt','Übertrag']
                s_item = SupplierItem(self)
                long_description_lines = \
                    [l for l in item_lines[1:] \
                       if utils.no_substr(clutter,l) and l.strip()]
                s_item.description = " ".join(long_description_lines[0][0:82].split())
                s_item.long_description = ""
                for l in long_description_lines:
                    if "Zwischensumme" in l:
                        break
                    s_item.long_description += l
                #if not (pos in [mypos,mypos+1,mypos+2]):
                #    break
                if "Vorkasse" in s_item.description:
                    continue
                mypos = pos
                s_item.item_code = item_str.split()[1]
                #print("code",s_item.item_code)
                q=re.search("([0-9]+) *([A-Za-z]+)",item_str[60:73])
                #print("q",q)
                if not q:
                    continue
                s_item.qty = int(q.group(1))
                s_item.qty_unit = q.group(2)
                if s_item.qty_unit=="ST":
                    s_item.qty_unit="Stk"
                #print("qty ",s_item.qty)
                #print("unit ",s_item.qty_unit)
                #print("str ",item_str[98:113])
                price = utils.read_float(item_str[98:113].split()[0])
                try:
                    price1 = utils.read_float(item_lines[1][98:113].split()[0])
                except Exception:
                    price1 = 0
                if price1 > price:
                    price = price1
                #print("price ",price)
                discount_line = ""
                discount_lines = [line for line in item_lines if 'Rabatt' in line or 'Dieselzuschlag' in line]
                discount = 0
                for discount_line in discount_lines:
                    #print("***"+discount_line+"xxx")
                    #print(len(discount_line))
                    discount += utils.read_float(discount_line[135:153].split()[0])
                #print("discount ",discount)
                #print("amount before discount ",utils.read_float(item_str[135:153].split()[0]))
                s_item.amount = utils.read_float(item_str[135:153].split()[0]) + discount
                #print("amount with discount ",s_item.amount)
                if s_item.description.split()[0]=="Transportkosten":
                    self.shipping = s_item.amount
                    #print("shipping: ",self.shipping)
                    continue
                s_item.rate = round(s_item.amount/s_item.qty,2)
                #print("item rate",s_item.rate)
                rounding_error += s_item.amount-s_item.rate*s_item.qty
                self.items.append(s_item)
        vat_line = ""
        for i in range(-1,-len(items),-1):
            vat_lines = [line for line in items[i] if 'MwSt' in line]
            if vat_lines:
                vat_line = vat_lines[0]
                break
        for i in range(-1,-len(items),-1):
            total_lines = [line for line in items[i] if 'Zwischensumme' in line]
            if total_lines:
                total_line = total_lines[0]
                break
        #print("rounding_error ",rounding_error)
        self.shipping += rounding_error
        self.totals[self.default_vat] = utils.read_float(total_line[135:153])
        self.vat[self.default_vat] = utils.read_float(vat_line[135:153]) # PurchaseInvoice.get_amount_heckert([vat_line])
        self.compute_total()
        return self

    def parse_nkk(self,lines):
        self.date = None
        self.no = None
        for line in lines:
            words = line.split()
            if not self.date:
                for i in range(len(words)):
                    self.date = utils.convert_date4(words[i])
                    if self.date:
                        self.no = words[i-1]
                        break
            elif words:
                for vat in self.vat_rates:
                    vatstr = "{:.2f}%".format(vat).replace(".",",")
                    if words[0]==vatstr:
                        self.vat[vat] = utils.read_float(words[5])
                        self.totals[vat] = utils.read_float(words[1])+\
                                           utils.read_float(words[3])
        self.items = []
        self.shipping = 0.0
        self.compute_total()
        self.assign_default_e_items(NKK_ACCOUNTS)
        return self

    def parse_kornkraft(self,lines):
        self.date = None
        self.no = None
        for vat in self.vat_rates:
            self.vat[vat] = 0
            self.totals[vat] = 0
        vat_rate_strs = ["{:.2f}".format(r).replace(".",",") for r in self.vat_rates]
        for line in lines:
            words = line.split()
            if not self.date:
                for i in range(len(words)):
                    self.date = utils.convert_date4(words[i])
                    if self.date:
                        self.no = words[i-2]
                        break
            else:
                if len(words)>12:
                    words = [w.replace('*','') for w in words]
                    for vat in vat_rate_strs:
                        if vat in words[0:6]:
                            #print(list(zip(words,range(len(words)))))
                            vat = utils.read_float(vat)
                            self.vat[vat] = utils.read_float(words[-4])
                            self.totals[vat] = utils.read_float(words[-2]) - self.vat[vat]
                            break
        #print(self.date,self.no,self.vat,self.totals)
        self.items = []
        self.shipping = 0.0
        self.compute_total()
        self.assign_default_e_items(KORNKRAFT_ACCOUNTS)
        return self

    def parse_generic(self,lines,default_account=None,paid_by_submitter=False,
                      is_test=False):
        amount = ""
        self.vat[self.default_vat] = ""
        self.totals[self.default_vat] = ""
        self.shipping = 0.0
        self.date = ""
        self.no = ""
        self.supplier = ""
        if lines:
            (amount,vat) = extract_amount_and_vat(lines,self.vat_rates)
            self.date = extract_date(lines)
            self.no = extract_no(lines)
            self.supplier = extract_supplier(lines)
        if lines and amount:    
            self.vat[self.default_vat] = vat
            self.totals[self.default_vat] = amount-self.vat[self.default_vat]
            self.shipping = 0.0
            if not is_test:
                if self.check_if_present():
                    return self
        if is_test:
            return self
        suppliers = gui_api_wrapper(Api.api.get_list,"Supplier",
                                    limit_page_length=LIMIT)
        supplier_names = [supp['name'] for supp in suppliers]
        supplier_names.sort()
        supplier_names+=['neu']
        def_supp = self.supplier if self.supplier in supplier_names else "neu"
        def_new_supp = "" if self.supplier in supplier_names else self.supplier
        layout = [  [sg.Text('Lieferant')],
                    [sg.OptionMenu(values=supplier_names, k='-supplier-',
                                   default_value = def_supp)],
                    [sg.Text('ggf. neuer Lieferant')],
                    [sg.Input(default_text = def_new_supp,
                              k='-supplier-name-')],
                    [sg.Text('Rechnungsnr.')],     
                    [sg.Input(default_text = self.no, k='-no-')],
                    [sg.Text('Datum')],     
                    [sg.Input(key='-date-',
                              default_text = utils.show_date4(self.date)),
                     sg.CalendarButton('Kalender', target='-date-',
                                       format = '%d.%m.%Y',
                                       begin_at_sunday_plus=1)],
                    [sg.Text('MWSt')],     
                    [sg.Input(default_text = str(self.vat[self.default_vat]),
                              k='-vat-')],
                    [sg.Text('Brutto')],     
                    [sg.Input(default_text = str(amount), k='-gross-')],
                    [sg.Text('Skonto')],     
                    [sg.Input(k='-skonto-')],
                    [sg.Checkbox('Schon selbst bezahlt',
                                 default=paid_by_submitter, k='-paid-')],
                    [sg.Text('Kommentar')],     
                    [sg.Input(k='-remarks-')],
                    [sg.Button('Speichern')] ]
        window1 = sg.Window("Einkaufsrechnung", layout, finalize=True)
        window1.bring_to_front()
        event, values = window1.read()
        #print(event, values)             
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
                    float(values['-vat-'].replace(",","."))
            if '-gross-' in values:
                self.totals[self.default_vat] = \
                    float(values['-gross-'].replace(",","."))\
                    -self.vat[self.default_vat]
            if '-skonto-' in values and values['-skonto-']:
                self.skonto = float(values['-skonto-'].replace(",","."))
            if '-paid-' in values and values['-paid-']:
                self.paid_by_submitter = True
            if '-remarks-' in values:
                self.remarks = values['-remarks-']
        else:
            return None
        self.compute_total()
        account = None
        if not self.update_stock:
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
                        account_names.remove(j)
                    except Exception:
                        pass
                account_names = paccs + account_names
                title = 'Buchungskonto wählen'
                msg = 'Bitte ein Buchungskonto wählen\n'
                account = easygui.choicebox(msg, title, account_names)
                if not account:
                    return None
        self.assign_default_e_items({self.default_vat:account})
        return self
    
    def parse_invoice(self,infile,account=None,paid_by_submitter=False,
                      is_test=False):
        self.extract_items = False
        lines = pdf_to_text(infile)
        try:        
            if lines:
                head = lines[0][0:140]
                if not head[0:10].split():
                    for line in lines[0:10]:
                        if len(line)>2 and (line[-2]=='£' or line[-3]=='£'):
                            head = "Kornkraft Naturkost GmbH"
                            break
                for supplier,info in PurchaseInvoice.suppliers.items():
                    if supplier in head:
                        self.parser = supplier
                        if info['raw']:
                            self.raw = True
                            lines = pdf_to_text(infile,True)
                        if not info['parser'](self,lines):
                            return None
                        if 'supplier' in info:
                            self.supplier = info['supplier'] 
                        else:    
                            self.supplier = supplier
                        self.multi = info['multi']    
                        self.extract_items = self.update_stock
                        return self
        except Exception as e:
            if self.update_stock:
                raise e
            elif not is_test:
                raise e
                print(e)
                print("Rückfall auf Standard-Rechnungsbehandlung")
        self.parser = "generic"
        return self.parse_generic(lines,account,paid_by_submitter,is_test)
        
    def compute_total(self):
        self.total = sum([t for v,t in self.totals.items()])
        self.total_vat = sum([t for v,t in self.vat.items()])
        self.gross_total = self.total + self.total_vat
        for vat in self.vat_rates:
            if (round(self.totals[vat]*vat/100.0+0.00001,2)-self.vat[vat]):
                print(self.no," Abweichung bei MWSt! ",
                      vat,"% von",self.totals[vat]," = ",
                      round(self.totals[vat]*vat/100.0+0.00001,2),
                      ". MWSt auf der Rechnung: ",
                      self.vat[vat])

    def assign_default_e_items(self,accounts):
        self.e_items = \
            [{'item_code' : settings.DEFAULT_ITEM_CODE,
              'qty' : 1,
              'rate' : self.totals[vat],
              'cost_center' : self.company.cost_center} \
                    for vat in self.vat_rates if vat in accounts and self.totals[vat]]
        if not self.update_stock and self.vat_rates:
            self.e_items[0]['expense_account'] = accounts[self.vat_rates[0]]

    def create_taxes(self):
        self.taxes = []
        for vat,account in self.company.taxes.items():
            if self.vat[vat]:
                self.taxes.append({'add_deduct_tax': 'Add',
                                   'charge_type': 'Actual',
                                   'account_head': account,
                                   'cost_center' : self.company.cost_center,
                                   'description': VAT_DESCRIPTION,
                                   'tax_amount': self.vat[vat]})

    def create_doc(self):
        self.doc = {
            'doctype': 'Purchase Invoice',
            'company': self.company.name,
            'supplier': self.supplier,
            'title': self.supplier.split()[0]+" "+self.no,
            'project': self.project,
            'bill_no': self.no,
            'order_id' : self.order_id,
            'posting_date' : self.date,
            'remarks' : self.remarks,
            'paid_by_submitter' : self.paid_by_submitter,
            'set_posting_time': 1,
            'credit_to' : self.company.payable_account,
            'naming_series' : STANDARD_NAMING_SERIES_PINV,
            'buying_price_list': STANDARD_PRICE_LIST,
            'taxes' : self.taxes,
            'items' : self.e_items,
            'update_stock': 1 if self.update_stock else 0,
            'cost_center' : self.company.cost_center
        }
        if self.skonto:
             self.doc['apply_discount_on'] = 'Grand Total'
             self.doc['discount_amount'] = self.skonto
        if self.shipping:
             self.doc['taxes'].append(\
                                      {'add_deduct_tax': 'Add',
                                       'charge_type': 'Actual',
                                       'account_head': DELIVERY_COST_ACCOUNT,
                                       'description': DELIVERY_COST_DESCRIPTION,
                                       'tax_amount': self.shipping})

    def check_total(self):
        err = ""
        computed_total = self.shipping+sum([item.rate*item.qty for item in self.items])
        if abs(self.total-computed_total) > 0.005 :
            err = "Abweichung! Summe in Rechnung: {0}, Summe der Posten: {1}".format(self.total,computed_total)
            err += "\nDies kann noch durch Preisanpassungen korrigiert werden.\n"
        return err   

    def check_duplicates(self):
        err = ""
        items = defaultdict(list)
        for item in self.e_items:
            items[item['item_code']].append(item) # group items by item_code
        for key in items.keys():
            if len(items[key]) > 1:  #if there is more than one item in a group
                err += "Ein Artikel ist mehrfach in der Rechnung vorhanden:\n"
                err += "\n".join(map(str,items[key]))
                err += "\nVielleicht ist die Zuordnung falsch und dies sollten zwei verschiedene Artikel sein?"
        if err:
            err += "\n\nTrotzdem Rechnung erstellen?"
        return err

    def check_if_present(self):
        upload = None
        invs = gui_api_wrapper(Api.api.get_list,"Purchase Invoice",
                               {'bill_no': self.no, 'status': ['!=','Cancelled']})
        if not invs and self.order_id:
            invs = gui_api_wrapper(Api.api.get_list,"Purchase Invoice",
                               {'order_id': self.order_id, 'status': ['!=','Cancelled']})
            if invs:
                # attach the present PDF to invoice with same order_id
                upload = self.upload_pdfs(invs[0]['name'])
        if invs:
            if upload:
                upload = "Aktuelle Rechnung wurde dort angefügt."
            easygui.msgbox("Einkaufsrechnung {} ist schon als {} in ERPNext eingetragen worden {}".format(self.no,invs[0]['name'],upload))
                
            self.is_duplicate = True
            return True
        return False

    def __init__(self,update_stock=False):
        # do not call super().__init__ here,
        # because there is no doc in ERPNext yet
        self.update_stock = update_stock
        self.order_id = None
        self.company_name = sg.UserSettings()['-company-']
        print("Company: ",self.company_name)
        self.company = company.Company.get_company(self.company_name)
        print("Company: ",self.company.name)
        self.remarks = None
        self.project = None
        self.paid_by_submitter = False
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

    def merge(self,inv):
        if not inv:
            return
        if self.company_name != inv.company_name:
            print("Kann nicht Rechnungen verschiedener Firmen verschmelzen: {} {}".format(self.company_name,inv.company_name))
        if self.supplier != inv.supplier:
            print("Kann nicht Rechnungen verschiedener Lieferanten verschmelzen: {} {}".format(self.supplier,inv.supplier))
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
    def parse_and_dump(cls,infile,update_stock,account=None,paid_by_submitter=False):
        inv = purchase_invoice.PurchaseInvoice(update_stock).parse_invoice(infile,account,paid_by_submitter)
        pprint(vars(inv))
        pprint(list(map(lambda x: pprint(vars(x)),inv.items)))

    @classmethod
    def read_and_transfer(cls,infile,update_stock,account=None,paid_by_submitter=False,project=None):
        one_more = True
        inv = None
        while one_more:
            one_more = False
            inv_new = PurchaseInvoice(update_stock).\
                        read_pdf(infile,account,paid_by_submitter)
            if (inv is None) and inv_new and inv_new.is_duplicate:
                return inv_new
            if inv_new and not inv_new.is_duplicate:
                inv_new.merge(inv)
                inv = inv_new
                if inv.total<0:
                    one_more = True
                    easygui.msgbox('Negativer Gesamtbetrag. Eine weitere Rechnung muss eingelesen werden.')
                elif inv.multi:
                    title = "Mit einer weiteren Rechnung verschmelzen?"
                    one_more = easygui.buttonbox(title, title,["Ja","Nein"])=="Ja"
                if one_more:
                    infile = utils.get_file('Weitere Einkaufsrechnung als PDF')
        if inv and not inv.is_duplicate:
            inv.project = project
            inv = inv.send_to_erpnext()
        if not inv:
            print("Keine Einkaufsrechnung angelegt")
        return inv

    def read_pdf(self,infile,account=None,paid_by_submitter=False):
        self.infiles = [infile]
        if not self.parse_invoice(infile,account,paid_by_submitter):
            return None
        print("Prüfe auf doppelte Rechung")
        if self.check_if_present():
            return self
        if self.extract_items:
            Api.load_item_data()
            print("Hole Lagerdaten")
            yesterd = utils.yesterday(self.date)
            self.e_items = list(map(lambda item: \
                item.process_item(self.supplier,yesterd),
                self.items))
            if None in self.e_items:
                print("Nicht alle Artikel wurden eingetragen.\n Deshalb kann keine Einkaufsrechnung in ERPNext erstellt werden.")
                return None
            if not ask_if_to_continue(self.check_total(),"Fortsetzen?"):
                return None
            if not ask_if_to_continue(self.check_duplicates()):
                return None
        elif not self.e_items:
            self.assign_default_e_items(SOMIKO_ACCOUNTS)
        self.create_taxes()    
        return self    

    def summary(self):
        if not self.doc:
            create_doc()
        fields = [('Rechnungsnr.','bill_no'),
                  ('Unternehmen','company'),
                  ('Lieferant','supplier'),
                  ('Datum','posting_date'),
                  ('Bemerkungen','remarks'),
                  ('schon bezahlt','paid_by_submitter'),
                  ('Gegenkonto','credit_to'),
                  ('Lagerhaltung','update_stock')]
        lines = ["{}: {}".format(d,self.doc[f]) for (d,f) in fields]
        lines.append('Artikel:')
        total = 0.0
        for item in self.doc['items']:
            amount = item['qty']*item['rate']
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

    def upload_pdfs(self,inv_name=None):
        print("Übertrage PDF der Rechnung")
        if not inv_name:
            inv_name = self.doc['name']
        upload = None
        for infile in self.infiles:
            upload = gui_api_wrapper(Api.api.read_and_attach_file,
                                     "Purchase Invoice",inv_name,
                                     infile,True)
        return upload    

    def send_to_erpnext(self):        
        print("Stelle ERPNext-Rechnung zusammen")
        self.create_doc()
        Api.create_supplier(self.supplier)
        #print(self.doc)
        print("Übertrage ERPNext-Rechnung")
        if not self.insert():
            return None
        # now we have a doc and can init class Invoice
        super().__init__(self.doc,False)
        #print(self.doc)
        self.company.purchase_invoices[self.doc['supplier']].append(self.doc)
        upload = self.upload_pdfs()
        # currently, we can only link to the last PDF    
        self.doc['supplier_invoice'] = upload['file_url']
        self.update()
        choices = ["Sofort buchen","Später buchen"]
        msg = "Einkaufsrechnung {0} wurde als Entwurf an ERPNext übertragen:\n{1}\n\n".format(self.doc['title'],self.summary())
        title = "Rechnung {}".format(self.no)
        filters={'company':self.company_name,
                 'party':self.supplier,
                 'docstatus':1,
                 'paid_amount':self.gross_total}
        py = gui_api_wrapper(Api.api.get_list,
                             "Payment Entry",
                             filters=filters,
                             limit_page_length=1)
        if py:
            py = doc.Doc(name=py[0]['name'],doctype='Payment Entry')
            bt = None
        else:
            bt = bank.BankTransaction.find_bank_transaction(self.company_name,
                                                            -self.gross_total)
        if py:
            msg += "\n\nZugehörige Anzahlung gefunden: {}\n".\
                     format(py.name)
            choices[0] = "Sofort buchen und zahlen"
        if bt:
            msg += "\n\nZugehörige Bank-Transaktion gefunden: {}\n".\
                     format(bt.description)
            choices[0] = "Sofort buchen und zahlen"
        if easygui.buttonbox(msg,title,choices) in \
             ["Sofort buchen","Sofort buchen und zahlen"]:
            print("Buche Rechnung")
            if py:
                self.use_advance_payment(py)
            self.submit()
            if bt:
                self.payment(bt)
        return self    


heckert_info = {'parser' : PurchaseInvoice.parse_heckert,
         'raw' : False, 'multi' : False,
         'supplier' : 'Heckert Solar GmbH'}
PurchaseInvoice.suppliers = \
    {'Krannich Solar GmbH & Co KG' :
        {'parser' : PurchaseInvoice.parse_krannich,
         'raw' :  False, 'multi' : False},
     'pvXchange Trading GmbH' :
        {'parser' : PurchaseInvoice.parse_pvxchange,
         'raw' : True, 'multi' : False},
     'Schlußrechnung' : heckert_info,
     'Vorausrechnung' : heckert_info,
     'Rechnung' :
        {'parser' : PurchaseInvoice.parse_nkk,
         'raw' :  False, 'multi' : False,
         'supplier' : 'Naturkost Kontor Bremen Gmbh'},
     'Kornkraft Naturkost GmbH' :
        {'parser' : PurchaseInvoice.parse_kornkraft,
         'raw' : False, 'multi' : True}}


