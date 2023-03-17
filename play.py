import argparse
import json

from api import Api
from api_wrapper import api_wrapper_test
import prerechnung
import PySimpleGUI as sg


def arg_parser():
    parser = argparse.ArgumentParser(description='ERPNext client für Solidarische Ökonomie Bremen')
    parser.add_argument('--server', dest='server', type=str,
                        help='URL for API server')
    parser.add_argument('--key', dest='key', type=str,
                        help='API key')
    parser.add_argument('--secret', dest='secret', type=str,
                        help='API secrect')
    parser.add_argument('--google-json', dest='google_credentials', type=str,
                        help='Google API credentials')
    return parser


def init():
    args = arg_parser().parse_args()
    # load sg settings (not that settings.py contains further settings)
    sg.user_settings_filename(filename='erpnext.json')
    settings = sg.UserSettings()
    if args.server:
        settings['-server-'] = args.server
    if args.key:
        settings['-key-'] = args.key
    if args.secret:
        settings['-secret-'] = args.secret
    if args.google_credentials:
        credentials = json.loads(args.google_credentials)
        for key in credentials.keys():
            credentials[key] = credentials[key].replace("\\n", "\n")
        with open("google-credentials.json", "w") as f:
            json.dump(credentials, f)
        settings['-google-credentials-'] = credentials
    settings['-setup-'] = not api_wrapper_test(Api.initialize)


init()
pr = Api.api.get_list("PreRechnung", filters={'processed': False}, limit_page_length=1)[0]
doc = Api.api.get_doc("PreRechnung", pr['name'])
prerechnung.process_inv(doc)


for pr in Api.api.get_list(
        "PreRechnung", filters={'processed': False}, limit_page_length=1):  # later on, replace 1 with LIMIT
    doc = Api.api.get_doc("PreRechnung", pr['name'])
    prerechnung.process_inv(doc)  # this method should be adapted
