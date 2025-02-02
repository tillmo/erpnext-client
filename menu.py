#!/usr/bin/env python3
import utils
import PySimpleGUI as sg
import report
import company
import bank
from invoice import Invoice
import purchase_invoice
import project
import lead
import sales_invoice
from api import Api, LIMIT
from api_wrapper import gui_api_wrapper, api_wrapper
import table
from version import VERSION 
import traceback
import os
import tempfile
import easygui
import numpy as np
from collections import defaultdict
import subprocess
import sys
from datetime import datetime
import settings
import journal
import prerechnung
import args
import json

def initial_loads():
    if sg.UserSettings()['-setup-']:
        return
    company.Company.init_companies()
    bank.BankAccount.init_baccounts()
    user_settings = sg.UserSettings()
    if not user_settings['-company-']:
        user_settings['-company-'] = company.Company.all()[0]
    company.Company.current_load_data()

def text_input(text,default_text =""):
    layout = [  [sg.Text(text)],     
                [sg.Input(default_text = default_text)],
                [sg.Button('Ok')] ]
    window = sg.Window(text, layout)
    event, values = window.read()
    window.close()
    return values[0]

def checkbox_input(title,window_text,button_text,default=False):
    layout = [  [sg.Text(window_text)],     
                [sg.Checkbox(button_text,default=default)],
                [sg.Button('Ok')] ]
    window = sg.Window(title, layout)
    event, values = window.read()
    window.close()
    return values[0]

def purchase_inv(update_stock):
    filename = utils.get_file('Einkaufsrechnung als PDF')
    if filename:
        print("Lese {} ein ...".format(filename))
        return purchase_invoice.PurchaseInvoice.read_and_transfer(None,filename,update_stock)
    return False

def show_data():
    user_settings = sg.UserSettings()
    if not user_settings['-setup-']: 
        comp_name = user_settings['-company-']
        print("Bereich: "+comp_name)
        for bacc in bank.BankAccount.baccounts_by_company[comp_name]:
            print(bacc.name, end="")
            if bacc.doc['last_integration_date']:
                print(", letzter Auszug:",
                      utils.show_date4(bacc.doc['last_integration_date']),
                      end="")
            if bacc.balance:
                print(", Kontostand laut ERPNext: {:.2f}".format(bacc.balance), end="")
            if bacc.statement_balance:
                print(", laut Auszug: {:.2f}".format(bacc.statement_balance),
                      end="")
            if bacc.balance and bacc.statement_balance and bacc.balance-bacc.statement_balance > 1e-04:
                print("\n********* Differenz: {:.2f}".format(bacc.balance-bacc.statement_balance),
                      " *********")
                print("Bitte Kontoauszug und ERPNext-Banktransaktionen abgleichen!")    
            print()
        comp = company.Company.get_company(comp_name)
        if comp:
            num_bts = len(comp.open_bank_transactions())
            if num_bts:
                print("{} offene Banktransaktionen"\
                      .format(num_bts))
            num_jes = len(comp.open_journal_entries())
            if num_jes:
                print("{} offene Buchungssätze".format(num_jes))
            num_pes = len(comp.unbooked_payment_entries())\
                      +len(comp.unassigned_payment_entries())
            if num_pes:
                print("{} offene (An)Zahlungen".format(num_pes))
            num_pres = len(comp.get_open_pre_invoices(True))+len(comp.get_open_pre_invoices(False))
            if num_pres:
                print("{} offene Prerechnungen".format(num_pres))
            num_pis = len(comp.get_purchase_invoices(True))
            if num_pis:
                print("{} offene Einkaufsrechnungen".format(num_pis))
            num_sis = len(comp.get_sales_invoices(True))
            if num_sis:
                print("{} offene Verkaufsrechnungen".format(num_sis))
            num_bg_jobs = len(Api.api.get_background_jobs())
            if num_bg_jobs:
                print("{} offene Hintergrund-Jobs".format(num_bg_jobs))

# ------ Process menu choices ------ #
def event_handler(event,window):
    user_settings = sg.UserSettings()
    show_company_data = False
    if event in (sg.WIN_CLOSED, 'Exit'):
        return "exit"
    if event in company.Company.all():
        user_settings['-company-'] = event
        company.Company.current_load_data()
        return "outer"
    #print(event, values)
    elif event == 'Über':
        print()
        print('ERPNext Client für Solidarische Ökonomie Bremen', 'Version '+VERSION)
    elif event == 'Hilfe Server':
        print()
        print('Anleitung für Einstellungen ERPNext-Server:')
        print('- Adresse des ERPNext-Servers: z.B. https://erpnext.cafesunshine.de')
        print('- API-Schlüssel und -Geheimnis bekommt man im ERPNext-Webclient')
        print('- (d.h. im Browser unter eben jener Adresse)')
        print('  - unter Einstellungen - My Settings')
        print('  - API-Zugriff (ganz unten auf der Seite)')
        print('  - dann "Schlüssel generieren" anklicken')
        print('  - das API-Geheimnis wird nur einmal angezeigt!')
        print('  - der API-Schlüssel wird stets angezeigt')
        print('- Diese Daten hier unter "Einstellungen" eingeben.')
    elif event == 'Hilfe Banktransaktionen':
        print()
        print('Das Datum des letzten Kontoauszugs wird angezeigt')
        print('Im Homebanking die Banktransaktionen seit diesem Datum herunterladen und als csv-Datein speichern')
        print('- Doppelungen werden erkannt, also lieber einen zu großen statt zu kleinen Zeitraum wählen')
        print('Dann hier unter Einlesen - Kontoauszug die csv-Datei hochladen')
        print('Danach unter Offene Dokumente - Banktransaktionen die Banktransaktionen zuordnen')
        print('Jeder Banktransaktion muss ein ERPNext-Buchungskonto oder eine offene Rechnung zugeordnet werden')
        print('- Dadurch entsteht ein ERPNext-Buchungssatz oder eine ERPNext-(An)Zahlung')
        print('- Man kann die Bearbeitung einer Banktransaktion auch abbrechen und mit der nächsten weitermachen')
        print('  - Die Banktransaktion bleibt dann offen und kann später bearbeitet werden')
        print('Schließlich müssen die ERPNext-Buchungssätze und ERPNext-(An)Zahlungen noch gebucht werden')
        print('-> Das geht unter Offene Dokumente - Buchungssätze bzw. Offene Dokumente - (An)Zahlungen, oder auf der ERPNext-Seite')
    elif event == 'Hilfe Rechnungen':
        print()
        print('Einlesen von Einkaufsrechnungen:')
        suppliers = ", ".join(purchase_invoice.PurchaseInvoice.suppliers.keys())
        print('Derzeit können Rechnungen von folgenden Lieferanten eingelesen werden: '+suppliers)
        print('(Für andere Lieferanten bitte im ERPNext-Webclient manuell eine Rechnung anlegen. Die Liste der hier möglichen Lieferanten kann ggf. erweitert werden.)')
        print('Das Einlesen einer Rechnung geht hier wie folgt:')
        print('- Unter Einlesen - Einkaufsrechnung das PDF hochladen (bitte keinen Scan einer Rechnung und keine Auftragsbestätigung!)')
        print('- oder unter Einlesen - Einkaufsrechnung Lager')
        print('Bei "einkaufsrechnung Lager" wird das Lager aktualisiert, d.h.:')
        print('- Für jeden Rechnungenartikel muss ein ERPNext-Artikel gefunden werden')
        print('- Es kann auch ein neuer ERPNext-Artikel angelegt werden, mit den Daten aus der Rechnung')
        print('- Ggf. muss der Preis angepasst werden')
        print('Für alle Rechnungen (ob mit Lager oder nicht) wird schließlich die Einkaufsrechnungen in ERPNext hochgeladen.')
        print('Dort muss sie noch geprüft und gebucht werden')
    elif event == 'Hilfe Buchen':
        print()
        print('In ERPNext werden Dokumente wie Rechnungen, Buchungssätze und (An)Zahlungen zunächst als Entwurf gespeichert.')
        print('Im Entwurfsstadium kann ein Dokument noch bearbeitet oder auch gelöscht werden.')
        print('Schließlich muss das Dokument gebucht werden. Nur dann wird es für die Abrechnung wirksam.')
        print('Ein einmal gebuchtes Dokument bleibt für immer im System. Es kann nicht mehr bearbeitet werden. Das ist gesetzlich so vorgeschrieben.')
        print('Es kann allerdings abgebrochen und abgeändert werden. Dadurch entsteht ein neues Dokument (eine Kopie).')
        print('Das alte Dokument bleibt aber als abgebrochenes Dokument im System.')
    elif event == 'ERPNext-Server':
        layout = [  [sg.Text('Adresse des ERPNext-Servers')],     
                    [sg.Input(default_text = user_settings['-server-'])],
                    [sg.Text('API-Schlüssel für Server-API')],     
                    [sg.Input(default_text = user_settings['-key-'])],
                    [sg.Text('API-Geheimnis für Server-API')],     
                    [sg.Input(default_text = user_settings['-secret-'])],
                    [sg.Button('Testen')] ]
        window1 = sg.Window("ERPNext-Server-Einstellungen", layout, finalize=True)
        window1.bring_to_front()
        event, values = window1.read()
        if values:
            if len(values)>0 and values[0]:
                user_settings['-server-'] = values[0]
            if len(values)>1 and values[1]:
                user_settings['-key-'] = values[1]
            if len(values)>2 and values[2]:
                user_settings['-secret-'] = values[2]
            window1.close()
            if "http:" in user_settings['-server-']:
                user_settings['-server-'] = user_settings['-server-'].replace('http','https')
            print()
            print("Teste API ...")
            result = api_wrapper(Api.initialize)
            if result['err_msg'] or result['exception']:
                if result['err_msg']:
                    print(result['err_msg'])
                elif result['exception']:  
                    print(result['exception'])
                print("API-Test fehlgeschlagen!")
                user_settings['-setup-'] = True
            else:    
                print("API-Test erfolgreich!")
                user_settings['-setup-'] = False
                initial_loads()
                window.close()
                return "outer"
    elif event == 'Google':
        layout = [  [sg.Text('Google invoice processor id')],     
                    [sg.Input(default_text = user_settings['-invoice-processor-'])],
                    [sg.Text('Google API credentials')],     
                    [sg.Input(default_text = json.dumps(user_settings['-google-credentials-']))],
                    [sg.Button('Speichren')] ]
        window1 = sg.Window("Google-Einstellungen", layout, finalize=True)
        window1.bring_to_front()
        event, values = window1.read()
        if values:
            if len(values)>0 and values[0]:
                user_settings['-invoice-processor-'] = values[0]
                print("Neue Einstellung gespeichert")
            if len(values)>1 and values[1]:
                args.set_google_credentials(values[1])
                print("Neue Einstellung gespeichert")
            window1.close()
    elif event == 'Update':
        print()
        print("Aktualisiere dieses Programm...")
        tmp = tempfile.mktemp()
        os.system("cd {}; git pull --rebase > {} 2>&1".format(user_settings['-folder-'],tmp))
        f = open(tmp,'r')
        print(f.read())
        f.close()

        print()
        print("Aktualisiere die Python-Umgebung...")
        python = sys.executable
        requirements_file = os.path.join(user_settings['-folder-'], 'requirements.txt')
        result = subprocess.run([python, '-m', 'pip', 'install', '-r', requirements_file],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                cwd=user_settings['-folder-'],
                                text=True)  # for automatic decoding of stdout/stderr
        print(result.stdout)
        print()
        if result.returncode != 0:
            print('Die Aktualisierung der Python-Umgebung scheint fehlgeschlagen zu sein.')
            print('Bitte Programm beenden, dann "pip3 install -r {requirements_file}" ausführen und schließlich das Programm neu starten.')
        else:
            print("Bitte Programm neu starten.")
    elif event == 'Sofort buchen':
        c = checkbox_input('Buchungseinstellungen',
                           'Ein Dokument muss gebucht werden, um für die Abrechnung wirksam zu werden.\nEin einmal gebuchtes Dokument bleibt für immer im System. Es kann nicht mehr bearbeitet werden. Das ist gesetzlich so vorgeschrieben.\nBei einer Einkaufsrechnung wird in jedem Fall gefragt, ob diese gebucht werden soll.',
                           'Alle Dokumente immer gleich einbuchen',
                           default=user_settings['-buchen-'])
        if c is not None:
            user_settings['-buchen-'] = c            
    elif event == 'Jahr':
        j = easygui.choicebox('Bitte Jahr für den Berichtszeitraum wählen, aktuell: {}'.format(user_settings['-year-']),
                              'Kalenderjahr wählen',
                               map(str,range(2020,datetime.today().year+1)))
        if j is not None:
            user_settings['-year-'] = int(j)            
    elif user_settings['-setup-']:
        print()
        print("Bitte erst ERPNext-Server einstellen (unter Einstellungen)")
        return "inner"
    elif event == 'Daten neu laden':
        company.Company.clear_companies()
        bank.BankAccount.clear_baccounts()
        initial_loads()
        show_company_data = True
    elif event == 'Kontoauszug':
        filename = utils.get_file('Kontoauszug als csv')
        if filename:
            print()
            print("Lese {} ein ...".format(filename))
            b = bank.BankStatement.process_file(filename)
            if b:
                comp = b.baccount.company.name
                if user_settings['-company-'] != comp:
                    print("Kontoauszug ist für "+comp)
                user_settings['-company-'] = comp
                show_company_data = True
                print("{} Banktransaktionen eingelesen, davon {} neu".\
                      format(len(b.entries),len(b.transactions)))
            else:
                print("Konnte keinen Kontoauszug einlesen")
    elif event == 'Einkaufsrechnung':
        if purchase_inv(False):
            show_company_data = True
    elif event == 'Einkaufsrechnung Lager':
        if purchase_inv(True):
            show_company_data = True
    elif event == 'Banktransaktionen einzeln':
        comp = company.Company.get_company(user_settings['-company-'])
        if comp:
            comp.reconcile_all()
            show_company_data = True
    elif event == 'Buchungssätze':
        keys = ['posting_date','account','caccount','total_debit','user_remark']
        headings = ['Datum','Buchungskonto','Gegenkonto','Betrag','Bemerkung']
        while True:
            comp = company.Company.get_company(user_settings['-company-'])
            jes = comp.open_journal_entries()
            jes1 = []
            for j in jes:
                j1 = gui_api_wrapper(Api.api.get_doc,'Journal Entry',j['name'])
                j1['account'] = j1['accounts'][0]['account']
                j1['caccount'] = j1['accounts'][1]['account']
                jes1.append(j1)
            title = "Buchungssätze"
            tbl = table.Table(jes1,keys,headings,title,enable_events=True,display_row_numbers=True)
            ix = tbl.display()
            if ix is False:
                break
            je = jes[ix]
            details = utils.format_entry(jes1[ix],keys,headings)
            choice = easygui.buttonbox("Buchungssatz {}\n{} ".\
                                           format(je['name'],details),
                                       "Buchungssatz",
                                       ["Buchen","Löschen","Nichts tun"])
            if choice == "Buchen":
                bank.BankTransaction.submit_entry(je['name'])
                show_company_data = True
            elif choice == "Löschen":
                bank.BankTransaction.delete_entry(je['name'])
                show_company_data = True
    elif event == 'Unverbuchte (An)Zahlungen':
        while True:
            keys = ['posting_date','name','paid_amount','party','reference_no']
            headings = ['Datum','Name','Betrag','Gezahlt an','Referenz.']
            comp = company.Company.get_company(user_settings['-company-'])
            pes = comp.unbooked_payment_entries()
            for pe in pes:
                if pe['payment_type']=='Pay':
                    pe['paid_amount'] = -pe['paid_amount']
            title = "Offene (An)Zahlungen"
            tbl = table.Table(pes,keys,headings,title,enable_events=True,display_row_numbers=True)
            ix = tbl.display()
            if ix is False:
                break
            pe = pes[ix]
            details = utils.format_entry(pe,keys,headings)
            choice = easygui.buttonbox("Zahlung {}\n{} ".\
                                           format(pe['name'],details),
                                       "Zahlung",
                                       ["Buchen","Löschen","Nichts tun"])
            if choice == "Buchen":
                bank.BankTransaction.submit_entry(pe['name'],is_journal=False)
                show_company_data = True
            elif choice == "Löschen":
                bank.BankTransaction.delete_entry(pe['name'],is_journal=False)
                show_company_data = True
    elif event == 'Unzugeordnete (An)Zahlungen':
        while True:
            keys = ['posting_date','name','unallocated_amount','party','reference_no']
            headings = ['Datum','Name','offener Betrag','Gezahlt an','Referenz.']
            comp = company.Company.get_company(user_settings['-company-'])
            pes = comp.unassigned_payment_entries()
            for pe in pes:
                if pe['payment_type']=='Pay':
                    pe['unallocated_amount'] = -pe['unallocated_amount']
            pes.sort(key=lambda x:x['posting_date'],reverse=True)        
            title = "Unzugeordnete (An)Zahlungen"
            tbl = table.Table(pes,keys,headings,title,enable_events=True,display_row_numbers=True)
            ix = tbl.display()
            if ix is False:
                break
            pe = pes[ix]
            details = utils.format_entry(pe,keys,headings)
            if pe['payment_type']=='Pay':
                invs = comp.get_purchase_invoices(True)
            else:    
                invs = comp.get_sales_invoices(True)
            if not invs:
                continue
            invs.sort(key=lambda inv: abs(inv.outstanding-abs(pe['unallocated_amount'])))
            inv_texts = list(map(lambda inv: utils.showlist([inv.name,inv.party,inv.reference,inv.outstanding]),invs))
            if len(inv_texts)<=1:
                inv_texts.append("Nichts")
            title = "Zugehörige Rechnung wählen"
            msg = details+"\n\n"+title+"\n"
            choice = easygui.choicebox(msg, title, inv_texts)
            if choice in inv_texts:
                pass # todo: reconcile payment and invoice
                #bank.BankTransaction.submit_entry(pe['name'],is_journal=False)
    elif event in ['Prerechnungen','Prerechnungen Anzahlung']:
        while True:
            keys = ['datum','name','chance','lieferant','short_pdf','balkonmodule','selbst_bezahlt','vom_konto_überwiesen','typ']
            headings = ['Datum','Name','Projekt','Lieferant','pdf','Balkon','selbst bez.','überwiesen','Typ']
            comp = company.Company.get_company(user_settings['-company-'])
            invs = comp.get_open_pre_invoices(event=='Prerechnungen Anzahlung')
            invs_f = [utils.format_dic(['balkonmodule','selbst_bezahlt',
                                        'vom_konto_überwiesen'],['pdf'],
                                        inv.copy())\
                      for inv in invs]
            invs.sort(key=lambda x:x['datum'],reverse=True)
            invs_f.sort(key=lambda x:x['datum'],reverse=True)
            tbl = table.Table(invs_f,keys,headings,event,
                            enable_events=True,display_row_numbers=True)
            ix = tbl.display()
            if ix is False:
                break
            inv = invs[ix]
            prerechnung.read_and_transfer(inv)
    elif event == 'Unzugeordnete (An)Zahlungen (Summen)':
        keys = ['party','sum']
        headings = ['Kund:in/Lieferant','Summe']
        comp = company.Company.get_company(user_settings['-company-'])
        pes = comp.unassigned_payment_entries()
        sums = defaultdict(float)
        for pe in pes:
            if pe['payment_type']=='Pay':
                pe['unallocated_amount'] = -pe['unallocated_amount']
            sums[pe['party']] += pe['unallocated_amount']
        sums = [{'party':p,'sum':s} for p,s in sums.items()]
        sums.sort(key=lambda s:s['sum'])
        title = "Unzugeordnete (An)Zahlungen (Summen)"
        tbl = table.Table(sums,keys,headings,title,display_row_numbers=True)
        tbl.display()
    elif event in ['offene Einkaufsrechnungen','offene Verkaufsrechnungen','Einkaufsrechnungen','Verkaufsrechnungen']:
        event_words = event.split(" ")
        open_invs = event_words[0]=='offene'
        if open_invs:
            add_keys = ['btname']
            add_heads = ['Bank']
            amount_key = ['outstanding_amount']
            amount_head = ['Ausstehend']
        else:    
            add_keys = []
            add_heads = []
            amount_key = ['grand_total']
            amount_head = ['Betrag']
        if event_words[-1] == 'Einkaufsrechnungen':
            inv_type = 'Purchase Invoice'
            inv_key = 'supplier'
            inv_heading = 'Lieferant'
        else:
            inv_type = 'Sales Invoice'
            inv_key = 'customer'
            inv_heading = 'Kunde'
        while True:
            keys = ['posting_date']+amount_key+['bill_no','status',inv_key,'owner']
            headings = ['Datum']+amount_head+['Rechungsnr.','Status',inv_heading,'Ersteller']
            comp = company.Company.get_company(user_settings['-company-'])
            invs = comp.get_invoices_of_type(inv_type,open_invs)
            inv_docs = []
            bt_dict = defaultdict(list)
            for i in range(len(invs)):
                name = invs[i].name
                inv_doc = gui_api_wrapper(Api.api.get_doc,
                                      inv_type,
                                      name)
                if not 'bill_no' in inv_doc:
                    inv_doc['bill_no'] = name
                if open_invs and inv_doc['status'] != 'Draft' and not inv_doc.get('custom_ebay'):
                    accounts = list(set(map(lambda i:i['expense_account'],
                                        inv_doc['items'])))
                    inv_doc['account'] = accounts[0]
                    if len(accounts)>1:
                        inv_doc['account']+" + weitere"
                    total = inv_doc['outstanding_amount']
                    if inv_type=='Purchase Invoice':
                        total = -total
                    bt = bank.BankTransaction.find_bank_transaction(\
                           comp.name,total,
                           inv_doc['bill_no'] if 'bill_no' in inv_doc else "")
                    if bt:
                        ref = None
                        if 'customer' in inv_doc:
                            ref = inv_doc['customer']
                        if 'supplier' in inv_doc:
                            ref = inv_doc['supplier']
                        if ref:
                            inv_doc['similarity'] = \
                                utils.similar(bt.description.lower(),
                                              ref.lower())
                            #print("Desc: ",bt.description.lower(),"\nRef: ",ref.lower(),"\nSimilarity",inv_doc['similarity'])
                            bt_dict[bt.name].append((i,inv_doc['similarity']))
                            inv_doc['bt'] = bt
                            inv_doc['btname'] = bt.name
                    inv_doc['disabled'] = not bt 
                elif inv_doc.get('custom_ebay'):
                    inv_doc['btname'] = 'EBay'
                    inv_doc['disabled'] = False                    
                else:
                    inv_doc['disabled'] = not (inv_doc['status'] == 'Draft')
                inv_docs.append(inv_doc)
            # handle duplicate bank transactions, use best matching invoice
            for bt,entries in bt_dict.items():
                entries.sort(key=lambda e:e[1],reverse=True)
                for (i,s) in entries[1:]:
                    del inv_docs[i]['bt']
                    del inv_docs[i]['btname']
            tbl = table.Table(inv_docs,keys+add_keys,headings+add_heads,event,
                            enable_events=True,display_row_numbers=True)
            ix = tbl.display()
            if ix is False:
                break
            inv_doc = inv_docs[ix]
            details = utils.format_entry(inv_doc,keys,headings)
            msg = "{} {}\n{} ".\
                      format(event[:-2],inv_doc['name'],details)
            choices = []
            if inv_doc['status'] == 'Draft':
                choices = ["Buchen","Löschen","Buchungskonto bearbeiten",
                           "Nichts tun"]
            elif inv_doc['custom_ebay']:
                choices = ["Zahlung erstellen"]    
            elif 'bt' in inv_doc:
                bt = inv_doc['bt']
                msg += "\n\nZugehörige Bank-Transaktion gefunden: {}\n".\
                         format(bt.description)
                choices = ["Sofort buchen und zahlen","Löschen","Buchungskonto bearbeiten","Nichts tun"]
            else:
                bt = None
            if choices:
                choice = easygui.buttonbox(msg,
                                           event[:-2],
                                           choices)
                #print(choice)
                inv = Invoice(inv_doc,inv_type=='Sales Invoice')
                if choice == "Zahlung erstellen":
                    inv.payment(settings.EBAY_ACCOUNT,inv.amount,inv.date)
                if choice == "Buchen" or choice == "Sofort buchen und zahlen":
                    gui_api_wrapper(Api.submit_doc,inv_type,inv_doc['name'])
                    show_company_data = True
                    if choice == "Sofort buchen und zahlen":
                        inv.payment_from_bank_transaction(bt)
                elif choice == "Löschen":
                    gui_api_wrapper(Api.api.delete,inv_type,inv_doc['name'])
                    show_company_data = True
                elif choice == "Buchungskonto bearbeiten":
                    if inv_doc['account'][-10:]!=' + weitere':
                        title = "Buchungskonto ändern"
                        msg = "Bitte ein Buchungskonto auswählen"
                        accounts = comp.leaf_accounts_for_credit
                        account_names = [acc['name'] for acc in accounts]
                        account_names.remove(inv_doc['account'])
                        texts = [inv_doc['account']]+account_names
                        account = easygui.choicebox(msg, title, texts)
                        del inv_doc['account']
                        nitems = []
                        for item in inv_doc['items']:
                            item['expense_account'] = account
                            nitems.append(item)
                        inv_doc['items'] = nitems
                        gui_api_wrapper(Api.api.update,inv_doc)
    elif event == 'Banktransaktionen':
        keys = ['date','amount','description']
        headings = ['Datum','Betrag','Bemerkung']
        comp = company.Company.get_company(user_settings['-company-'])
        while True:
            bts = comp.open_bank_transactions()
            for bt in bts:
                bt['amount'] = bt['unallocated_amount']*np.sign(bt['deposit']-bt['withdrawal'])
            title = "Banktransaktionen"
            tbl = table.Table(bts,keys,headings,title,enable_events=True,max_col_width=120,
                              display_row_numbers=True)
            ix = tbl.display()
            if ix is False:
                break
            comp.reconcile(bts[ix])
            show_company_data = True
    elif event == 'Banktransaktionen für abgebr. Links bereinigen':
        bank.BankTransaction.unreconcile_for_cancelled_links()
        print("Banktransaktionen für abgebrochene Links bereinigt")
    elif event in bank.BankAccount.get_baccount_names():
        keys = ['date','open','amount','balance','description']
        headings = ['Datum','Offen','Betrag','Stand','Bemerkung']
        while True:
            bts = gui_api_wrapper(Api.api.get_list,'Bank Transaction',
                              fields=bank.BT_FIELDS,
                              filters={'bank_account':event,
                                       'docstatus': ['!=', 2],
                                       'status': ['!=', 'Cancelled']},
                                       order_by='date asc',
                                       limit_page_length=LIMIT)
            balance = 0.0
            for bt in bts:
                bt['amount'] = bt['deposit']-bt['withdrawal']
                balance += bt['amount']
                bt['balance'] = balance
                bt['disabled'] = (bt['status'] == 'Reconciled')
                if bt['disabled']:
                    bt['open'] = ''
                else:    
                    bt['open'] = '*'
            bts.reverse()    
            title = "Banktransaktionen für "+event
            tbl = table.Table(bts,keys,headings,title,enable_events=True,max_col_width=120,
                              display_row_numbers=True)
            ix = tbl.display()
            if ix is False:
                break
            comp = company.Company.get_company(user_settings['-company-'])
            comp.reconcile(bts[ix])
            show_company_data = True
    elif event in ['Abrechnung', 'Quartalsabrechnung', 'Monatsabrechnung', 'Bilanz']:
        comp = user_settings['-company-']
        if event=='Abrechnung':
            consolidated = True
            periodicity = 'Yearly'
        elif event=='Quartalsabrechnung':
            consolidated = False
            periodicity = 'Quarterly'
        elif event=='Monatsabrechnung':
            consolidated = False
            periodicity = 'Monthly'
        else:
            consolidated = False
            periodicity = None
        balance = event=='Bilanz'   
        tbl = report.build_report(comp,consolidated=consolidated,balance=balance,
                                  periodicity=periodicity)
        # in PDF, always also display balance
        if event != 'Bilanz':
            child = report.build_report(comp,consolidated=False,balance=True)
            tbl.child = child
            tbl.child_title = " mit Bilanz"
        while True:
            ix = tbl.display()
            if ix is False:
                break
            account = tbl.entries[ix]['account']
            tbl1 = report.general_ledger(comp,account)
            if tbl1:
                tbl1.display()
    elif event == 'Bilanz grafisch':
        comp = user_settings['-company-']
        if comp in settings.BALANCE_ACCOUNTS:
            report.balances(comp,settings.BALANCE_ACCOUNTS[comp])
        else:
            easygui.msgbox("Für {} ist leider noch keine grafische Bilanz eingerichtet".format(comp))
    elif event == 'USt-Buchungen':
        comp = user_settings['-company-']
        q = utils.last_quarter(datetime.today())
        print("Erstelle Buchungen für Umsatzsteuer "+q)
        journal.create_tax_journal_entries(comp,q)
    elif event == 'Einnahmen nach Steuersätzen umverteilen':
        comp = user_settings['-company-']
        q = utils.last_quarter(datetime.today())
        print("Erstelle Buchungen für Umverteilung der Einnahmen "+q)
        journal.create_income_dist_journal_entries(comp,q)
        print("\nBitte diese Buchungssätze noch buchen")
    elif event == 'USt-Voranmeldung':
        comp = user_settings['-company-']
        q = utils.last_quarter(datetime.today())
        print("USt-Voranmeldung für Quartal ",q)
        journal.vat_declaration(comp,q)
    elif event == 'USt-Rechnungen zusammenstellen':
        comp = user_settings['-company-']
        q = utils.last_quarter(datetime.today())
        dir = journal.save_pretax_details(comp,q)
        print("Rechnungen in {} gespeichert".format(dir))
    elif event == 'Prerechnungen vorprozessieren':
        prerechnung.process(user_settings['-company-'])
    elif event == 'zu bezahlende Prerechnungen':
        prs = prerechnung.to_pay(user_settings['-company-'])
        keys = ['zu_zahlen_am','name','lieferant','auftragsnr','betrag','summe','typ','datum','kommentar']
        headings = ['Frist','Name','Lieferant','Auftragsnr.','Betrag','Summe','Typ','Datum','Kommentar']
        title = 'Zu bezahlende Prerechnungen'
        tbl = table.Table(prs,keys,headings,title,display_row_numbers=True)
        tbl.display()
    elif event == 'Balkonmodulverkauf (grafisch)':
        report.balkonmodule(user_settings['-company-'])
    elif event == 'Balkonmodulverkauf (csv)':
        report.balkonmodule_csv(user_settings['-company-'])
    elif event == 'Kontenblätter':
        report.general_ledger(user_settings['-company-'])
    elif event == 'EK-Rechnungen nach Konto':
        comp_name = user_settings['-company-']
        comp = company.Company.get_company(comp_name)
        accounts = comp.leaf_accounts
        account_names = [acc['name'] for acc in accounts]
        account_names.sort()
        title = 'Buchungskonto wählen'
        msg = 'Bitte ein Buchungskonto wählen\n'
        account = easygui.choicebox(msg, title, account_names)
        if account:
            journal.save_purchase_invoices(comp_name,account)
    elif event == 'Leads bearbeiten':
        lead.process_open_leads()
    elif event == 'Leadübersicht':
        lead.show_open_leads()
    elif event == 'Zahlungen für EBay-Rechnungen':
        sales_invoice.ebay_sales(user_settings['-company-'],
                                 user_settings['-buchen-'])
    elif event == 'PreRechnungs-Überweisungen zuordnen': 
        bank.BankTransaction.reconcile_pre_invoices()   
    elif event in ['Projekte']:
        while True:
            tbl = report.projects()
            ix = tbl.display()
            if ix is False:
                break
            pname = tbl.entries[ix]['Name']
            ptitle = tbl.entries[ix]['Titel']
            pstatus = tbl.entries[ix]['Status']
            msg = "Projekt {} {}".format(pname,ptitle)
            if pstatus == 'Open':
                choices = ["Abschließen","Verkaufte Artikel anzeigen","Nichts tun"]
                choice = easygui.buttonbox(msg,msg,choices)
                if choice == "Abschließen":
                    project.complete_project(pname)
                if choice == "Verkaufte Artikel anzeigen":
                    items = report.sold_items(pname)
                    items.sort(key=lambda x:x['item_name'])
                    keys = ['item_code','item_name','qty']
                    headings = ['Artikelnr.','Artikel','Anzahl']
                    title = 'Verkaufte Artikel'
                    tbl_p = table.Table(items,keys,headings,title,display_row_numbers=True)
                    tbl_p.display()
    if show_company_data:
        print()
        show_data()
        window.set_title(utils.title())
        show_company_data = False
    return "inner"

def menus():
    user_settings = sg.UserSettings()

    sg.set_options(element_padding=(0, 0))

    # ------ Menu Definition ------ #
    menu_def = [['&Einlesen', ['&Kontoauszug', '&Einkaufsrechnung', '&Einkaufsrechnung Lager']],
                ['&Offene Dokumente', ['Buchungssätze','Unverbuchte (An)Zahlungen','Unzugeordnete (An)Zahlungen',
                                       'Unzugeordnete (An)Zahlungen (Summen)','Prerechnungen','Prerechnungen Anzahlung',
                                       'offene Einkaufsrechnungen','offene Verkaufsrechnungen','Banktransaktionen',
                                       'Banktransaktionen einzeln','Prerechnungen vorprozessieren',
                                       'Zahlungen für EBay-Rechnungen','PreRechnungs-Überweisungen zuordnen',
                                       'Banktransaktionen für abgebr. Links bereinigen']],
                ['Fertige Dokumente', ['Einkaufsrechnungen','Verkaufsrechnungen']+bank.BankAccount.get_baccount_names()], 
                ['Berichte', ['Jahr','Abrechnung', 'Quartalsabrechnung', 'Monatsabrechnung', 'Bilanz', 'Bilanz grafisch', 'Projekte','Balkonmodulverkauf (grafisch)','Balkonmodulverkauf (csv)','zu bezahlende Prerechnungen','Kontenblätter']], 
                ['Bereich', company.Company.all()], 
                ['Steuer', ['Einnahmen nach Steuersätzen umverteilen','USt-Voranmeldung','USt-Buchungen','USt-Rechnungen zusammenstellen','EK-Rechnungen nach Konto']],
                ['Lead',['Leads bearbeiten', 'Leadübersicht']],
                ['&Einstellungen', ['Daten neu laden','Sofort buchen','&ERPNext-Server', 'Google', 'Update']], 
                ['&Hilfe', ['Hilfe Server', 'Hilfe Banktransaktionen', 'Hilfe Rechnungen', 'Hilfe Buchen', 'Über']], ]


    # ------ GUI Defintion ------ #
    layout = [
        [sg.Menu(menu_def, tearoff=False, pad=(200, 1))],
        [sg.Output(size=(120, 25))],
    ]
    company_name = user_settings['-company-']
    if not company_name:
        company_name = "... <Bitte erst Server-Einstellungen setzen>"
    last_window_location = tuple(sg.UserSettings().get('-last-window-location-', (None, None)))
    window = sg.Window(utils.title(),
                       layout,
                       default_element_size=(12, 1),
                       default_button_element_size=(12, 1),
                       location=last_window_location,
                       font=('Any 11'),
                       finalize=True)

    # ------ Loop & Process button menu choices ------ #
    window.bring_to_front()
    last_window_location = utils.get_current_location(window)
    initial_loads()
    show_data()
    while True:
        event, values = window.read()
        current_window_location = utils.get_current_location(window)
        if current_window_location != (None, None):
            last_window_location = current_window_location
        try:
            res = event_handler(event,window)
        except Exception as e:
            res = utils.title()+"\n"+str(e)+"\n"+traceback.format_exc()
        if res=="exit":
            sg.UserSettings().set('-last-window-location-', last_window_location)
            window.close()
            return True
        elif res=="outer":
            window.close()
            return False
        elif res!="inner":
            print(res)

#  loop needed for re-display of window in case of changed server settings
def main_loop():
    # Use only colors in the format of #RRGGBB
    MyAmber = {"BACKGROUND": "#ebb41c",
               "TEXT": "#000000",
               "INPUT": "#FDFFF7",
               "TEXT_INPUT": "#000000",
               "SCROLL": "#FDFFF7",
               "BUTTON": ("#000000",
                          "#fdcb52"),
               "PROGRESS": ('#000000', '#000000'),
               "BORDER": 1,
               "SLIDER_DEPTH": 0,
               "PROGRESS_DEPTH": 0,}

    # Add your dictionary to the PySimpleGUI themes
    sg.theme_add_new('MyAmber', MyAmber)

    # Switch your theme to use the newly added one
    sg.theme('My Amber')

    if not sg.UserSettings()['-setup-']: 
        company.Company.init_companies()
    while True:
        try:
            if menus():
                break
        except Exception as e:
            print(utils.title()+"\n"+str(e)+"\n"+traceback.format_exc())
            print("Fataler Fehler - angehalten.")
            while True:
                pass
        
