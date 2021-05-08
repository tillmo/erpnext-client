#!/usr/bin/env python3
import utils
import PySimpleGUI as sg
import company
import bank
import purchase_invoice
from api import Api
from api_wrapper import gui_api_wrapper, api_wrapper_test, api_wrapper
from version import VERSION 
import traceback
import csv
import tkinter
import os
import tempfile
import easygui

TITLE = "ERPNext-Client für "

def initial_loads():
    company.Company.init_companies()
    bank.BankAccount.init_baccounts()
    settings = sg.UserSettings()
    if not settings['-company-']:
        settings['-company-'] = company.Company.all()[0]
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
        if update_stock:
            Api.load_item_data()
        return purchase_invoice.PurchaseInvoice.read_and_transfer(filename,update_stock)    
    return False

def show_data():
    settings = sg.UserSettings()
    if not settings['-setup-']: 
        comp_name = settings['-company-']
        print("Bereich: "+comp_name)
        for bacc in bank.BankAccount.baccounts_by_company[comp_name]:
            print("Konto:",bacc.name, end="")
            if bacc.doc['last_integration_date']:
                print(", letzter Auszug:",
                      utils.show_date4(bacc.doc['last_integration_date']),
                      end="")
            if bacc.balance:
                print(", Kontostand laut ERPNext: {:.2f}".format(bacc.balance), end="")
            if bacc.statement_balance:
                print(", laut Auszug: {:.2f}".format(bacc.statement_balance),
                      end="")
            print()
        comp = company.Company.get_company(comp_name)
        server_info = "weiter unter Anzeigen oder im ERPNext-Webclient unter {}".format(settings['-server-'])
        if comp:
            num_bts = len(comp.open_bank_transactions())
            if num_bts:
                print("{} offene Banktransaktionen (weiter unter Bearbeiten - Banktransaktionen)"\
                      .format(num_bts))
            num_jes = len(comp.open_journal_entries())
            if num_jes:
                print("{} offene Buchungssätze; {}/desk#List/Journal Entry/List?company={}".\
                      format(num_jes,server_info,comp_name))
            num_pes = len(comp.open_payment_entries())
            if num_pes:
                print("{} offene Zahlungen; {}/desk#List/Payment Entry/List?company={}".\
                      format(num_pes,server_info,comp_name))
            num_pis = len(comp.get_open_purchase_invoices())
            if num_pis:
                print("{} offene Einkaufsrechnungen; {}/desk#List/Purchase Invoice/List?company={}".\
                      format(num_pis,server_info,comp_name))
            num_sis = len(comp.get_open_sales_invoices())
            if num_sis:
                print("{} offene Verkaufsrechnungen; {}/desk#List/Sales Invoice/List?company={}".\
                      format(num_sis,server_info,comp_name))
def to_str(x):
    if type(x)==type(0.1):
        return "{: >9.2f}".format(x).replace(".",",")
    d = utils.show_date4(x)
    if d:
        return d
    else:
        return x

def csv_export(filename,data,headings):
    with open(filename, mode='w') as f:
        writer = csv.writer(f, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headings)
        writer.writerows(data)
    print(filename," exportiert")    

def get(e,k):
    if k in e:
        return e[k]
    else:
        return ""
    
def show_table(entries,keys,headings,title,enable_events=False,max_col_width=60):
    settings = sg.UserSettings()
    data = [[to_str(get(e,k)) for k in keys] for e in entries]
    layout = [[sg.SaveAs(button_text = 'CSV-Export',
                         default_extension = 'csv',enable_events=True)],
              [sg.Table(values=data, headings=headings, max_col_width=max_col_width,
               auto_size_columns=len(data) > 0,
               display_row_numbers=True,
               justification='left',
               num_rows=30,
               key='-TABLE-',
               enable_events=enable_events,
               row_height=25)]]
    window1 = sg.Window(title, layout, finalize=True)
    #window1.Widget.column('#3', anchor='e')
    window1.bring_to_front()
    while True:
        (event,values) = window1.read()
        #print(event,values)
        if event == 'CSV-Export':
            if values['CSV-Export']:
                csv_export(values['CSV-Export'],data,headings)    
            continue
        elif event == '-TABLE-':
            ix = values['-TABLE-'][0]
            if 'disabled' in entries[ix] and entries[ix]['disabled']:
                continue
            else:
                window1.close()
                return ix
        break
    window1.close()
    return False

def format_entry(doc,keys,headings):
    return "\n".join([h+": "+to_str(get(doc,k)) for (k,h) in zip(keys,headings)])
    
# ------ Process menu choices ------ #
def event_handler(event,window):
    settings = sg.UserSettings()
    show_company_data = False
    if event in (sg.WIN_CLOSED, 'Exit'):
        return "exit"
    if event in company.Company.all():
        settings['-company-'] = event
        company.Company.current_load_data()
        show_company_data = True
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
        print('Danach unter Bearbeiten - Banktransaktionen die Banktransaktionen zuordnen')
        print('Jeder Banktransaktion muss ein ERPNext-Buchungskonto oder eine offene Rechnung zugeordnet werden')
        print('- Dadurch entsteht ein ERPNext-Buchungssatz oder eine ERPNext-Zahlung')
        print('- Man kann die Bearbeitung einer Banktransaktion auch abbrechen und mit der nächsten weitermachen')
        print('  - Die Banktransaktion bleibt dann offen und kann später bearbeitet werden')
        print('Schließlich müssen die ERPNext-Buchungssätze und ERPNext-Zahlungen noch gebucht werden')
        print('-> Das geht unter Anzeigen - Buchungssätze bzw. Anzeigen - Zahlungen, oder auf der ERPNext-Seite')
    elif event == 'Hilfe Rechnungen':
        print()
        print('Einlesen von Einkaufsrechnungen:')
        suppliers = ", ".join(purchase_invoice.PurchaseInvoice.suppliers.keys())
        print('Derzeit können Rechnungen von folgenden Lieferanten eingelesen werden: '+suppliers)
        print('(Für andere Lieferanten bitte im ERPNext-Webclient manuell eine Rechnung anlegen. Die Liste der hier möglichen Lieferanten kann ggf. erweitert werden.)')
        print('Das Einlesen einer Rechnung geht hier wie folgt:')
        print('- Unter Einlesen - Einkaufsrechnung das PDF hochladen (bitte keinen Scan einer Rechnung und keine Auftragsbestätigung!)')
        print('- oder unter Einlesen - Einkaufsrechnung Balkonmodule')
        print('Bei Balkonmodul-Rechnungen wird das Lager aktualisiert, d.h.:')
        print('- Für jeden Rechnungenartikel muss ein ERPNext-Artikel gefunden werden')
        print('- Es kann auch ein neuer ERPNext-Artikel angelegt werden, mit den Daten aus der Rechnung')
        print('- Ggf. muss der Preis angepasst werden')
        print('Für alle Rechnungen (ob Balkonmodul oder nicht) wird schließlich die Einkaufsrechnungen in ERPNext hochgeladen.')
        print('Dort muss sie noch geprüft und gebucht werden')
    elif event == 'Hilfe Buchen':
        print()
        print('In ERPNext werden Dokumente wie Rechnungen, Buchungssätze und Zahlungen zunächst als Entwurf gespeichert.')
        print('Im Entwurfsstadium kann ein Dokument noch bearbeitet oder auch gelöscht werden.')
        print('Schließlich muss das Dokument gebucht werden. Nur dann wird es für die Abrechnung wirksam.')
        print('Ein einmal gebuchtes Dokument bleibt für immer im System. Es kann nicht mehr bearbeitet werden. Das ist gesetzlich so vorgeschrieben.')
        print('Es kann allerdings abgebrochen und abgeändert werden. Dadurch entsteht ein neues Dokument (eine Kopie).')
        print('Das alte Dokument bleibt aber als abgebrochenes Dokument im System.')
    elif event == 'ERPNext-Server':
        layout = [  [sg.Text('Adresse des ERPNext-Servers')],     
                    [sg.Input(default_text = settings['-server-'])],
                    [sg.Text('API-Schlüssel für Server-API')],     
                    [sg.Input(default_text = settings['-key-'])],
                    [sg.Text('API-Geheimnis für Server-API')],     
                    [sg.Input(default_text = settings['-secret-'])],
                    [sg.Button('Testen')] ]
        window1 = sg.Window("ERPNext-Server-Einstellungen", layout, finalize=True)
        window1.bring_to_front()
        event, values = window1.read()
        if values:
            if len(values)>0 and values[0]:
                settings['-server-'] = values[0]
            if len(values)>1 and values[1]:
                settings['-key-'] = values[1]
            if len(values)>2 and values[2]:
                settings['-secret-'] = values[2]
            window1.close()
            if "http:" in settings['-server-']:
                settings['-server-'] = settings['-server-'].replace('http','https')
            print()
            print("Teste API ...")
            result = api_wrapper(Api.initialize)
            if result['err_msg'] or result['exception']:
                if result['err_msg']:
                    print(result['err_msg'])
                elif result['exception']:  
                    print(result['exception'])
                print("API-Test fehlgeschlagen!")
                settings['-setup-'] = True
            else:    
                print("API-Test erfolgreich!")
                settings['-setup-'] = False
                initial_loads()
                window.close()
                return "outer"
    elif event == 'Update':
        print()
        print("Aktualisiere dieses Programm...")
        tmp = tempfile.mktemp()
        os.system("cd {}; git pull --rebase > {} 2>&1".format(settings['-folder-'],tmp))
        f = open(tmp,'r')
        print(f.read())
        f.close()
        print("Bitte Programm neu starten.")
    elif event == 'Sofort buchen':
        c = checkbox_input('Buchungseinstellungen',
                           'Ein Dokument muss gebucht werden, um für die Abrechnung wirksam zu werden.\nEin einmal gebuchtes Dokument bleibt für immer im System. Es kann nicht mehr bearbeitet werden. Das ist gesetzlich so vorgeschrieben.\nBei einer Einkaufsrechnung wird in jedem Fall gefragt, ob diese gebucht werden soll.',
                           'Alle Dokumente immer gleich einbuchen',
                           default=settings['-buchen-'])
        if c is not None:
            settings['-buchen-'] = c            
    elif settings['-setup-']:
        print()
        print("Bitte erst ERPNext-Server einstellen (unter Einstellungen)")
        return "inner"
    elif event == 'Daten neu laden':
        company.Company.clear_companies()
        bank.BankAccount.clear_baccounts()
        initial_loads()
    elif event == 'Kontoauszug':
        filename = utils.get_file('Kontoauszug als csv')
        if filename:
            print()
            print("Lese {} ein ...".format(filename))
            b = bank.BankStatement.process_file(filename)
            if b:
                comp = b.baccount.company.name
                if settings['-company-'] != comp:
                    print("Kontoauszug ist für "+comp)
                settings['-company-'] = comp
                show_company_data = True
                print("{} Banktransaktionen eingelesen, davon {} neu".\
                      format(len(b.entries),len(b.transactions)))
            else:
                print("Konnte keinen Kontoauszug einlesen")
    elif event == 'Einkaufsrechnung':
        if purchase_inv(False):
            show_company_data = True
    elif event == 'Einkaufsrechnung Balkonmodule':
        if purchase_inv(True):
            show_company_data = True
    elif event == 'Banktransaktionen bearbeiten':
        comp = company.Company.get_company(settings['-company-'])
        if comp:
            comp.reconciliate_all()
            show_company_data = True
    elif event == 'Banktransaktionen':
        keys = ['date','amount','description']
        headings = ['Datum','Betrag','Bemerkung']
        comp = company.Company.get_company(settings['-company-'])
        while True:
            bts = comp.open_bank_transactions()
            for bt in bts:
                bt['amount'] = bt['deposit']-bt['withdrawal']
            title = "Banktransaktionen"
            ix = show_table(bts,keys,headings,title,enable_events=True,max_col_width=120)
            if ix is False:
                break
            comp.reconciliate(bts[ix])
            show_company_data = True
    elif event == 'Buchungssätze':
        keys = ['posting_date','account','caccount','total_debit','user_remark']
        headings = ['Datum','Buchungskonto','Gegenkonto','Betrag','Bemerkung']
        while True:
            comp = company.Company.get_company(settings['-company-'])
            jes = comp.open_journal_entries()
            jes1 = []
            for j in jes:
                j1 = gui_api_wrapper(Api.api.get_doc,'Journal Entry',j['name'])
                j1['account'] = j1['accounts'][0]['account']
                j1['caccount'] = j1['accounts'][1]['account']
                jes1.append(j1)
            title = "Buchungssätze"
            ix = show_table(jes1,keys,headings,title,enable_events=True)
            if ix is False:
                break
            je = jes[ix]
            details = format_entry(jes1[ix],keys,headings)
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
    elif event == 'Zahlungen':
        while True:
            keys = ['posting_date','paid_amount','party','reference_no']
            headings = ['Datum','Betrag','Gezahlt an','Referenz.']
            comp = company.Company.get_company(settings['-company-'])
            pes = comp.open_payment_entries()
            title = "Zahlungen"
            ix = show_table(pes,keys,headings,title,enable_events=True)
            if ix is False:
                break
            pe = pes[ix]
            details = format_entry(pe,keys,headings)
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
    elif event in ['Einkaufsrechnungen','Verkaufsrechnungen']:
        while True:
            keys = ['posting_date','grand_total','bill_no','status','account','supplier']
            headings = ['Datum','Betrag','Rechungsnr.','Status','Buchungskonto','Lieferant']
            comp = company.Company.get_company(settings['-company-'])
            if event == 'Einkaufsrechnungen':
                inv_type = 'Purchase Invoice'
            else:
                inv_type = 'Sales Invoice'
            invs = comp.get_open_invoices_of_type(inv_type)
            inv_docs = []
            for inv in invs:
                inv_doc = gui_api_wrapper(Api.api.get_doc,
                                      inv_type,
                                      inv.name)
                if not 'bill_no' in inv_doc:
                    inv_doc['bill_no'] = inv.name
                accounts = list(set(map(lambda i:i['expense_account'],
                                    inv_doc['items'])))
                inv_doc['account'] = accounts[0]
                if len(accounts)>1:
                    inv_doc['account']+" + weitere"
                total = inv_doc['grand_total']
                if inv_type=='Purchase Invoice':
                    total = -total
                bt = bank.BankTransaction.find_bank_transaction(\
                       comp.name,total,
                       inv_doc['bill_no'] if 'bill_no' in inv_doc else "")
                if bt:
                    inv_doc['bt'] = bt
                    inv_doc['btname'] = bt.name
                inv_doc['disabled'] = not (bt or inv_doc['status'] == 'Draft')
                inv_docs.append(inv_doc)
            ix = show_table(inv_docs,keys+['btname'],headings+['Bank'],event,
                            enable_events=True)
            if ix is False:
                break
            inv_doc = inv_docs[ix]
            details = format_entry(inv_doc,keys,headings)
            msg = "{} {}\n{} ".\
                      format(event[:-2],inv_doc['name'],details)
            choices = ["Buchen","Löschen","Buchungskonto bearbeiten",
                       "Nichts tun"]
            if 'bt' in inv_doc:
                bt = inv_doc['bt']
                msg += "\n\nZugehörige Bank-Transaktion gefunden: {}\n".\
                         format(bt.description)
                choices[0] = "Sofort buchen und zahlen"
            if bt or inv_doc['status'] == 'Draft':    
                choice = easygui.buttonbox(msg,
                                           event[:-2],
                                           choices)
                print(choice)
                if choice == "Buchen" or choice == "Sofort buchen und zahlen":
                    gui_api_wrapper(Api.submit_doc,inv_type,inv_doc['name'])
                    show_company_data = True
                    if choice == "Sofort buchen und zahlen":
                        company.Invoice(inv_doc,False).payment(bt)
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
    if show_company_data:
        print()
        show_data()
        window.set_title(TITLE+ settings['-company-'])
        show_company_data = False
    return "inner"    

def menus():
    settings = sg.UserSettings()

    sg.theme('LightGreen')
    sg.set_options(element_padding=(0, 0))

    # ------ Menu Definition ------ #
    menu_def = [['&Einlesen', ['&Kontoauszug', '&Einkaufsrechnung', '&Einkaufsrechnung Balkonmodule']],
                ['&Bearbeiten', ['Banktransaktionen bearbeiten']],
                ['&Anzeigen', ['Buchungssätze','Zahlungen','Einkaufsrechnungen','Verkaufsrechnungen','Banktransaktionen']],
                ['Bereich', company.Company.all()], 
                ['&Einstellungen', ['Daten neu laden','Sofort buchen','&ERPNext-Server', 'Update']], 
                ['&Hilfe', ['Hilfe Server', 'Hilfe Banktransaktionen', 'Hilfe Rechnungen', 'Hilfe Buchen', 'Über']], ]


    # ------ GUI Defintion ------ #
    layout = [
        [sg.Menu(menu_def, tearoff=False, pad=(200, 1))],
        [sg.Output(size=(130, 30))],
    ]
    company_name = settings['-company-']
    if not company_name:
        company_name = "... <Bitte erst Server-Einstellungen setzen>"
    window = sg.Window(TITLE+company_name,
                       layout,
                       default_element_size=(12, 1),
                       default_button_element_size=(12, 1),
                       finalize=True)

    # ------ Loop & Process button menu choices ------ #
    window.bring_to_front()
    initial_loads()
    show_data()
    while True:
        event, values = window.read()
        try:
            res = event_handler(event,window)
        except Exception as e:
            res = str(e)+"\n"+traceback.format_exc()
        if res=="exit":
            window.close()
            return True
        elif res=="outer":
            window.close()
            return True
        elif res!="inner":
            print(res)

#  loop needed for re-display of window in case of changed server settings
def main_loop():
    company.Company.init_companies()
    while True:
        if menus():
            break
        
