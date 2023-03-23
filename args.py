import json
import PySimpleGUI as sg

import argparse
import purchase_invoice
from api import Api
from api_wrapper import api_wrapper_test
from settings import VALIDITY_DATE
from version import VERSION


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
    parser.add_argument('--invoice-processor', dest='invoice_processor', type=str,
                        help='Google invoice processor id')
    parser.add_argument('--google-json', dest='google_credentials', type=str,
                        help='Google API credentials')
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


def init():
    # process command line arguments
    args = arg_parser().parse_args()
    if args.v:
        print(VERSION)
        exit(0)
    # load sg settings (not that settings.py contains further settings)
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
    if args.invoice_processor:
        settings['-invoice-processor-'] = args.invoice_processor
    if args.google_credentials:
        credentials = json.loads(args.google_credentials)
        for key in credentials.keys():
            credentials[key] = credentials[key].replace("\\n", "\n")
        with open("google-credentials.json", "w") as f:
            json.dump(credentials, f)
        settings['-google-credentials-'] = credentials
    settings['-setup-'] = not api_wrapper_test(Api.initialize)
    return args
