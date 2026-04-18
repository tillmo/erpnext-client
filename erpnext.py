#!/usr/bin/python3

JOURNAL_LIMIT = 100

from args import init
import purchase_invoice
import bank
import company
from settings import STANDARD_PRICE_LIST, VALIDITY_DATE
from api_wrapper import gui_api_wrapper
from api import Api, LIMIT
import menu
import easygui
import PySimpleGUI as sg
import prerechnung


if __name__ == '__main__':
    args = init()
    # load sg settings (note that settings.py contains further settings)
    sg.user_settings_filename(filename='erpnext.json')
    settings = sg.UserSettings()
    # choose action according to command line arguments
    if args.all_sales:
        for item_price in gui_api_wrapper(Api.api.get_list,'Item Price',
                                          limit_page_length=LIMIT):
            if not item_price['price_list'] == STANDARD_PRICE_LIST:
                name = item_price['name']
                print("Adapting {0} to {1}".format(name,STANDARD_PRICE_LIST))
                doc = gui_api_wrapper(Api.api.get_doc,'Item Price', name)
                doc['price_list'] = STANDARD_PRICE_LIST
                gui_api_wrapper(Api.api.update,doc)
    elif args.price_dates:
        for item_price in gui_api_wrapper(Api.api.get_list,'Item Price',
                                          limit_page_length=LIMIT):
            name = item_price['name']
            doc = gui_api_wrapper(Api.api.get_doc,'Item Price', name)
            doc['valid_from'] = VALIDITY_DATE
            gui_api_wrapper(Api.api.update,doc)
    elif args.p is not None:
        menu.initial_loads()
        overrides = {
            'betrag': args.betrag,
            'mwst': args.mwst,
            'rechnungsnr': args.rechnungsnr,
            'datum': args.datum,
            'konto': args.konto,
            'lieferant': args.lieferant,
            'projekt': args.projekt,
        }
        overrides = {k: v for k, v in overrides.items() if v is not None}
        if args.selbst_bezahlt:
            overrides['selbst_bezahlt'] = True
        prerechnung.cli_read_and_transfer(
            name=args.p or None,
            advance=args.anzahlung,
            overrides=overrides or None
        )
    elif args.e:
        menu.initial_loads()
        if args.e=="-":
            infile = easygui.fileopenbox("Rechnung auswählen")
        else:
            infile = args.e
        if not infile:
            easygui.msgbox(infile+" existiert nicht")
            exit(1)
        prerechnung.read_and_transfer_pdf(infile,args.update_stock)    
    elif args.k:
        menu.initial_loads()
        if args.k=="-":
            infile = easygui.fileopenbox("Kontoauszugs-Datei auswählen")
        else:
            infile = args.k
        if not infile:
            easygui.msgbox("Keine Datei angegeben")
            exit(1)
        b = bank.BankStatement.process_file(infile)
        if b:
            b.baccount.company.reconcile_all()
    elif args.b:
        menu.initial_loads()
        comp = company.Company.get_company(settings['-company-'])
        if comp:
            comp.reconcile_all()
    elif args.i:
        import json
        Api.load_item_data()
        item_dict = {'items': Api.items_by_code, 'translations': Api.item_code_translation}
        print(json.dumps(item_dict, ensure_ascii=False, indent=2))
    # no arguments given? Then call GUI    
    else:
        menu.main_loop()
