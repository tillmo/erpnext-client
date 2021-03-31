#!/usr/bin/python3

from settings import WAREHOUSE, COMPANY, STANDARD_PRICE_LIST, STANDARD_ITEM_GROUP, STANDARD_NAMING_SERIES_PINV, CREDIT_TO_ACCOUNT, VAT_ACCOUNT, VAT_DESCRIPTION, DELIVERY_COST_ACCOUNT, DELIVERY_COST_DESCRIPTION

import utils
import easygui
import subprocess
import re
from api import Api, COMPANY, WAREHOUSE
from api_wrapper import gui_api_wrapper
from collections import defaultdict
import random
import string

def pdf_to_text(file,raw=False):
    cmd = ["pdftotext","-nopgbrk","-layout"]
    if raw:
        cmd.append("-raw")
    cmd += [file,"-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    return [bline.decode('utf_8') for bline in p.stdout]

def ask_if_to_continue(err,msg=""):
    if err:
        title = "Warnung"
        return easygui.ccbox(err+msg, title) # show a Continue/Cancel dialog
    return True    

class SupplierItem(object):
    def __init__(self):
        pass

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
                e_item = {'doctype' : 'Item',
                          'item_code' : item_code,
                          'item_name' : self.description,
                          'description' : self.long_description,
                          'item_group' : STANDARD_ITEM_GROUP,
                          'item_defaults': [{'company': COMPANY,
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
                    'desc' : self.description}
        else:
            return None
        
class PurchaseInvoice(object):
    suppliers = {}
    @classmethod
    def get_amount_krannich(cls,lines):
        return sum(map(lambda line: utils.read_float(line[-9:-1]),lines))
    
    def parse_krannich(self,lines,file):
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
        self.items = []
        mypos = 0
        rounding_error = 0
        for item_lines in items[1:]:
            item_str = item_lines[0]
            clutter = ['Einzelpreis','Krannich','IBAN','Rechnung','Übertrag']
            s_item = SupplierItem()
            s_item.description = " ".join(item_lines[1][0:82].split())
            long_description_lines = \
                [l for l in item_lines[1:] \
                   if utils.no_substr(clutter,l) and l.strip()]
            s_item.long_description = ""
            for l in long_description_lines:
                if "Zwischensumme" in l:
                    break
                s_item.long_description += l
            pos = int(item_str[0:7].split()[0])
            if not (pos in [mypos,mypos+1,mypos+2]):
                break
            if "Vorkasse" in s_item.description:
                continue
            mypos = pos
            s_item.item_code = item_str[9:20].split()[0]
            q=re.search("([0-9]+) *([A-Za-z]+)",item_str[91:113])
            s_item.qty = int(q.group(1))
            s_item.qty_unit = q.group(2)
            price = utils.read_float(item_str[123:138].split()[0])
            try:
                discount = utils.read_float(item_str[142:152].split()[0])
            except Exception:
                discount = 0
            s_item.amount = utils.read_float(item_str[165:].split()[0])
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
        self.shipping = PurchaseInvoice.get_amount_krannich\
                            ([line for line in items[-2]\
                    if 'Insurance' in line or 'Freight' in line\
                                           or 'Neukundenrabatt' in line])
        mwst_line = [line for line in items[-2] if 'MwSt' in line][0]
        self.total = utils.read_float(mwst_line[145:157])
        self.mwst = PurchaseInvoice.get_amount_krannich([mwst_line])
        self.shipping += rounding_error

    def parse_pvxchange(self,lines,file):
        items = []
        item = []
        preamble = True
        self.date = None
        self.no = None
        for line in lines:
            if "Bremen, den" in line:
                self.date = utils.convert_date4(line.split()[2])
            if line[0:8] == "Rechnung":
                if len(line.split())>1:
                    self.no = line.split()[2]
            if preamble:
                if len(line)>=4 and line[0:4]=="Pos.":
                    preamble = False
                continue
            if len(line)>=5 and line[0:5]=="Seite":
                preamble = True
                continue
            try:
                pos_no = int(line.split()[0])
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
        mypos = 0
        for item_lines in items[1:-1]:
            parts = " ".join(map(lambda s: s.strip(),item_lines)).split()
            s_item = SupplierItem()
            s_item.qty = int(parts[1])
            s_item.rate = utils.read_float(parts[-4])
            s_item.amount = utils.read_float(parts[-2])
            s_item.qty_unit = "Stk"
            s_item.description = " ".join(parts[2:-4])
            s_item.long_description = s_item.description
            try:
                ind = parts.index('Artikelnummer:')
                s_item.item_code = parts[ind+1]
            except Exception:
                s_item.item_code = None
            if not (s_item.description=="Selbstabholer" and s_item.amount==0.0):
                self.items.append(s_item)
        self.shipping = 0.0
        mwst_line = [line for line in items[-1] if 'MwSt' in line][0]
        self.mwst = utils.read_float(mwst_line.split()[-2])
        total_line = [line for line in items[-1] if 'Nettosumme' in line][0]
        self.total = utils.read_float(total_line.split()[-2])

    def parse_invoice(self,infile):
        lines = pdf_to_text(infile)
        head = lines[0]
        for supplier,info in PurchaseInvoice.suppliers.items():
            if supplier in head:
                if info['raw']:
                    lines = pdf_to_text(infile,True)
                info['parser'](self,lines,infile)
                self.supplier = supplier

    def create_e_invoice(self,update_stock):
        self.e_invoice = {
            'doctype': 'Purchase Invoice',
            'supplier': self.supplier,
            'title': self.supplier.split()[0]+" "+self.no,
            'bill_no': self.no,
            'posting_date' : self.date,
            'set_posting_time': 1,
            'credit_to' : CREDIT_TO_ACCOUNT,
            'naming_series' : STANDARD_NAMING_SERIES_PINV,
            'buying_price_list': STANDARD_PRICE_LIST,
            'taxes' : [{'add_deduct_tax': 'Add',
                        'charge_type': 'Actual',
                        'account_head': VAT_ACCOUNT,
                        'description': VAT_DESCRIPTION,
                        'tax_amount': self.mwst}],
            'items' : self.e_items,
            'update_stock': 1 if update_stock else 0
        }
        if self.shipping:
             self.e_invoice['taxes'].append(\
                                      {'add_deduct_tax': 'Add',
                                       'charge_type': 'Actual',
                                       'account_head': DELIVERY_COST_ACCOUNT,
                                       'description': DELIVERY_COST_DESCRIPTION,
                                       'tax_amount': self.shipping})

    def check_total(self):
        err = ""
        computed_total = self.shipping+sum([item.amount for item in self.items])
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
        invs = gui_api_wrapper(Api.api.get_list,"Purchase Invoice",
                               {'bill_no': self.no, 'status': ['!=','Cancelled']})
        if invs:
            easygui.msgbox("Einkaufsrechnung {} ist schon als {} in ERPNext eingetragen worden".format(self.no,invs[0]['name']))
            return True
        return False

    def __init__(self):
        pass

    @classmethod
    def create_and_read_pdf(cls,infile,update_stock):
        return PurchaseInvoice().read_pdf(infile,update_stock)

    def read_pdf(self,infile,update_stock):
        self.parse_invoice(infile)
        if self.check_if_present():
            return None
        yesterd = utils.yesterday(self.date)
        self.e_items = list(map(lambda item: \
            item.process_item(self.supplier,yesterd),
            self.items))
        if None in self.e_items:
            easygui.msgbox("Nicht alle Artikel wurden eingetragen.\n Deshalb kann keine Einkaufsrechnung in ERPNext erstellt werden.")
            return None
        if not ask_if_to_continue(self.check_total(),"Fortsetzen?"):
            return None
        if not ask_if_to_continue(self.check_duplicates()):
            return None
        self.create_e_invoice(update_stock)
        #print(e_invoice)
        self.doc = gui_api_wrapper(Api.api.insert,self.e_invoice)
        #print(self.doc)
        upload = gui_api_wrapper(Api.api.read_and_attach_file,
                                 "Purchase Invoice",self.doc['name'],
                                 infile,True)
        self.doc['supplier_invoice'] = upload['file_url']
        self.doc = gui_api_wrapper(Api.api.update,self.doc)
        #doc = gui_api_wrapper(Api.api.get_doc,'Purchase Invoice',self.doc['name'])
        if easygui.buttonbox("Einkaufsrechnung {0} als Entwurf an ERPNext übertragen.\n\nSoll die Rechnung auch gleich gebucht werden oder nicht?".format(self.e_invoice['title']),"Sofort buchen?",["Sofort buchen","Später buchen"]) == "Sofort buchen":
            gui_api_wrapper(Api.api.submit,self.doc)
        return self    

            
PurchaseInvoice.suppliers = \
    {'Krannich Solar GmbH & Co KG' :
        {'parser' : PurchaseInvoice.parse_krannich, 'raw' :  False},
     'pvXchange Trading GmbH' :
        {'parser' : PurchaseInvoice.parse_pvxchange, 'raw' : True}}
        

