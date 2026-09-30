from __future__ import annotations

import PySimpleGUI as sg

import argparse
import purchase_invoice
from api import Api
from api_wrapper import api_wrapper_test
from settings import VALIDITY_DATE
from version import VERSION


def arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser\
              (description='ERPNext client für Solidarische Ökonomie Bremen')
    parser.add_argument('-e', dest='e', type=str,
                        help='Einkaufsrechnung einlesen')
    parser.add_argument('-p', dest='p', type=str, nargs='?', const='',
                        help='PreRechnung verarbeiten (optional: Name der PreRechnung)')
    parser.add_argument('-k', dest='k', type=str,
                        help='Kontoauszug einlesen')
    parser.add_argument('-i', dest='i', action='store_true',
                        help='Show all items')
    parser.add_argument('-b', dest='b', action='store_true',
                        help='Process bank transactions')
    parser.add_argument('-v', dest='v', action='store_true',
                        help='Show version')
    parser.set_defaults(i=False)
    parser.set_defaults(b=False)
    parser.add_argument('--server', dest='server', type=str,
                        help='URL for API server')
    parser.add_argument('--key', dest='key', type=str,
                        help='API key')
    parser.add_argument('--secret', dest='secret', type=str,
                        help='API secrect')
    parser.add_argument('--claude-key', dest='claude_key', type=str,
                        help='Anthropic API key for invoice extraction with Claude')
    parser.add_argument('--claude-model', dest='claude_model', type=str,
                        help='Claude model for invoice extraction (default: settings.CLAUDE_MODEL)')
    parser.add_argument('--company', dest='company', type=str,
                        help='company to work with')
    parser.add_argument('--update-stock', dest='update_stock', action='store_true',
                        help='Lager aktualisieren')
    parser.set_defaults(update_stock=False)
    parser.add_argument('--betrag', dest='betrag', type=float,
                        help='Bruttobetrag überschreiben')
    parser.add_argument('--mwst', dest='mwst', type=float,
                        help='MWSt-Betrag überschreiben')
    parser.add_argument('--rechnungsnr', dest='rechnungsnr', type=str,
                        help='Rechnungsnummer überschreiben')
    parser.add_argument('--datum', dest='datum', type=str,
                        help='Rechnungsdatum überschreiben (TT.MM.JJJJ)')
    parser.add_argument('--konto', dest='konto', type=str,
                        help='Buchungskonto (Abkürzung)')
    parser.add_argument('--lieferant', dest='lieferant', type=str,
                        help='Lieferant')
    parser.add_argument('--projekt', dest='projekt', type=str,
                        help='Projekt')
    parser.add_argument('--selbst-bezahlt', dest='selbst_bezahlt', action='store_true',
                        help='Rechnung schon selbst bezahlt')
    parser.set_defaults(selbst_bezahlt=False)
    parser.add_argument('--anzahlung', dest='anzahlung', action='store_true',
                        help='Anzahlungsrechnungen anzeigen')
    parser.set_defaults(anzahlung=False)
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

def init() -> argparse.Namespace:
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
    if args.claude_key:
        settings['-claude-key-'] = args.claude_key
    if args.claude_model:
        settings['-claude-model-'] = args.claude_model
    settings['-setup-'] = not Api.initialize()
    return args
