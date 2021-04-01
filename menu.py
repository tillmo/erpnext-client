#!/usr/bin/env python3
import PySimpleGUI as sg
import company
import bank
import purchase_invoice
import utils
from api import Api
from api_wrapper import gui_api_wrapper, api_wrapper_test, api_wrapper
from version import VERSION 
import traceback
import csv
import tkinter
import os
import tempfile

TITLE = "ERPNext-Client für "

def initial_loads():
    company.Company.init_companies()
    bank.BankAccount.init_baccounts()

def text_input(text,default_text =""):
    layout = [  [sg.Text(text)],     
                [sg.Input(default_text = default_text)],
                [sg.Button('Ok')] ]
    window = sg.Window(text, layout)
    event, values = window.read()
    window.close()
    return values[0]

def purchase_inv(update_stock):
    filename = sg.popup_get_file('Einkaufsrechnung als PDF', no_window=True)
    if filename:
        print("Lese ein ...")
        Api.load_item_data()
        return purchase_invoice.PurchaseInvoice.create_and_read_pdf(filename,update_stock)    
    return False

def show_data():
    settings = sg.UserSettings()
    if not settings['-setup-']: 
        comp_name = settings['-company-']
        print("Bereich: "+comp_name)
        for bacc in bank.BankAccount.baccounts_by_company[comp_name]:
            if bacc.doc['last_integration_date']:
                print("Konto :",bacc.name,"letzter Auszug",bacc.doc['last_integration_date'])
            else:    
                print("Konto :",bacc.name)
        comp = company.Company.get_company(comp_name)
        server_info = "weiter im ERPNext-Webclient unter {}".format(settings['-server-'])
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
            num_pis = len(comp.open_purchase_invoices())
            if num_pis:
                print("{} offene Einkaufsrechnungen; {}/desk#List/Purchase Invoice/List?company={}".\
                      format(num_pis,server_info,comp_name))
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
    
def show_table(entries,keys,headings,title,enable_events=False,max_col_width=60):
    settings = sg.UserSettings()
    data = [[to_str(e[k]) for k in keys] for e in entries]
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
            window1.close()
            return ix
        break
    window1.close()
    return False

# ------ Process menu choices ------ #
def event_handler(event,window):
    settings = sg.UserSettings()
    show_company_data = False
    if event in (sg.WIN_CLOSED, 'Exit'):
        return "exit"
    if event in company.Company.all():
        settings['-company-'] = event
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
    elif settings['-setup-']:
        print()
        print("Bitte erst ERPNext-Server einstellen (unter Einstellungen)")
        return "inner"
    if event == 'Kontoauszug':
        filename = sg.popup_get_file('Kontoauszug als csv', no_window=True)
        if filename:
            print()
            b = bank.BankStatement.process_file(filename)
            comp = b.baccount.company.name
            if settings['-company-'] != comp:
                print("Kontoauszug ist für "+comp)
            settings['-company-'] = comp
            show_company_data = True
            print("{} Banktransaktionen eingelesen, davon {} neu".\
                  format(len(b.entries),len(b.transactions))) 
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
                if bt['debit']:
                    bt['amount'] = -bt['debit']
                else:    
                    bt['amount'] = bt['credit']
            title = "Banktransaktionen"
            ix = show_table(bts,keys,headings,title,enable_events=True,max_col_width=120)
            if not ix:
                break
            comp.reconciliate(bts[ix])
    elif event == 'Buchungssätze':
        keys = ['posting_date','account','caccount','total_debit','user_remark']
        headings = ['Datum','Buchungskonto','Gegenkonto','Betrag','Bemerkung']
        comp = company.Company.get_company(settings['-company-'])
        jes = comp.open_journal_entries()
        jes1 = []
        for j in jes:
            j1 = gui_api_wrapper(Api.api.get_doc,'Journal Entry',j['name'])
            j1['account'] = j1['accounts'][0]['account']
            j1['caccount'] = j1['accounts'][1]['account']
            jes1.append(j1)
        title = "Buchungssätze"
        show_table(jes1,keys,headings,title)
    elif event == 'Zahlungen':
        keys = ['posting_date','paid_amount','party','reference_no']
        headings = ['Datum','Betrag','Gezahlt an','Referenz.']
        comp = company.Company.get_company(settings['-company-'])
        pes = comp.open_payment_entries()
        title = "Zahlungen"
        show_table(pes,keys,headings,title)
    elif event == 'Einkaufsrechnungen':
        keys = ['posting_date','grand_total','supplier','bill_no']
        headings = ['Datum','Betrag','Lieferant','Rechungsnr.']
        comp = company.Company.get_company(settings['-company-'])
        invs = comp.open_purchase_invoices()
        title = "Einkaufsrechnungen"
        show_table(invs,keys,headings,title)
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
                ['&Anzeigen', ['Buchungssätze','Zahlungen','Einkaufsrechnungen','Banktransaktionen']],
                ['Bereich', company.Company.all()], 
                ['&Einstellungen', ['&ERPNext-Server', 'Update']], 
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
    show_data()
    window.bring_to_front()
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
    while True:
        if menus():
            break
        
