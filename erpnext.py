#!/usr/bin/python3

JOURNAL_LIMIT = 100

import purchase_invoice
import bank
import company
from settings import STANDARD_PRICE_LIST, VALIDITY_DATE
from api_wrapper import gui_api_wrapper, api_wrapper_test
from api import Api, LIMIT
import menu
from version import VERSION 

import sys
import os
import json
import easygui
import argparse
import PySimpleGUI as sg


def arg_parser():
    parser = argparse.ArgumentParser\
              (description='ERPNext client für Solidarische Ökonomie Bremen')
    parser.add_argument('-e', dest='e', type=str,
                        help='Einkaufsrechnung einlesen')
    parser.add_argument('-k', dest='k', type=str,
                        help='Kontoauszug einlesen')
    parser.add_argument('-i', dest='i', action='store_true',
                        help='Show all items')
    parser.add_argument('-b', dest='b', action='store_true',
                        help='Process bank transactions')
    parser.add_argument('-v', dest='v', action='store_true',
                        help='Show version')
    parser.set_defaults(i=False)
    parser.set_defaults(p=False)
    parser.set_defaults(b=False)
    parser.add_argument('--server', dest='server', type=str,
                        help='URL for API server')
    parser.add_argument('--key', dest='key', type=str,
                        help='API key')
    parser.add_argument('--secret', dest='secret', type=str,
                        help='API secrect')
    parser.add_argument('--company', dest='company', type=str,
                        help='company to work with')
    parser.add_argument('--update-stock', dest='update_stock', action='store_true',
                        help='Lager aktualisieren')
    parser.set_defaults(update_stock=False)
    parser.add_argument('--all_sales', dest='all_sales', action='store_true',
                        help='Alle Artikelpreise auf Preisliste {0} setzen'.\
                                 format(purchase_invoice.STANDARD_PRICE_LIST))
    parser.set_defaults(all_sales=False)
    parser.add_argument('--price_dates', dest='price_dates',
                        action='store_true',
                        help='Daten aller Artikelpreise auf Datum {0} setzen'.\
                                  format(VALIDITY_DATE))
    parser.set_defaults(price_dates=False)
    return parser

if __name__ == '__main__':
    # process command line arguments
    args = arg_parser().parse_args()
    if args.v:
        print(VERSION)
        exit(0)
    # load sg settings (note that settings.py contains further settings)
    sg.user_settings_filename(filename='erpnext.json')
    settings = sg.UserSettings()
    if args.company:
        settings['-company-'] = args.company
    if args.server:
        settings['-server-'] = args.server
    if args.key:
        settings['-key-'] = args.key
    if args.secret:
        settings['-secret-'] = args.secret
    settings['-setup-'] = not api_wrapper_test(Api.initialize)
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
    elif args.e:
        menu.initial_loads()
        if args.e=="-":
            infile = easygui.fileopenbox("Rechnung auswählen")
        else:
            infile = args.e
        if not infile:
            easygui.msgbox(infile+" existiert nicht")
            exit(1)
        if args.update_stock:
            Api.load_item_data()
        purchase_invoice.PurchaseInvoice.read_and_transfer(infile,args.update_stock)    
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
            b.baccount.company.reconciliate_all()
    elif args.b:
        menu.initial_loads()
        comp = company.Company.get_company(settings['-company-'])
        if comp:
            comp.reconciliate_all()
    elif args.i:
        Api.load_item_data()
        print(Api.item_code_translation)
        print(Api.items_by_code)
    # no arguments given? Then call GUI    
    else:
        menu.main_loop()
    

    
