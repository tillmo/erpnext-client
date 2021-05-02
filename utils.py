from datetime import datetime, timedelta
from difflib import SequenceMatcher
import csv
import codecs
import sys
import time

def running_linux():
    return sys.platform.startswith('linux')

import PySimpleGUI as sg
if running_linux():
    import PySimpleGUIWx as sgwx
else:
    sgwx = sg


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def convert_date4(date):
    try:
        d = datetime.strptime(date, '%d.%m.%Y')
        return d.strftime('%Y-%m-%d')
    except Exception:
        return None

def convert_date2(date):
    try:
        d = datetime.strptime(date, '%d.%m.%y')
        return d.strftime('%Y-%m-%d')
    except Exception:
        return None

def show_date4(date):
    try:
        d = datetime.strptime(date, '%Y-%m-%d')
        return d.strftime('%d.%m.%Y')
    except Exception:
        return None

def yesterday(date):
    d = datetime.strptime(date, '%Y-%m-%d')
    d = d-timedelta(1)
    return d.strftime('%Y-%m-%d')


def no_substr(l1,l2):
    for s in l1:
        if s in l2:
            return False
    return True    

def read_float(s,sign="H"):
    s1 = s.replace(".","").replace(",",".")
    if s1[-1]=='-':
        s1 = '-'+s1[:-2]
    res = float(s1)
    if sign=="S":
        res = -res
    return res

def remove_space(str):
    return " ".join(str.split())

def get_csv(codec,infile,delimiter=";",replacenl=False):
    f = codecs.open(infile, 'r', codec)
    if replacenl:
        lines = f.read().replace('\r\n','§#')\
                        .replace('\n',' ')\
                        .replace('§#','\n')\
                        .split('\n')
    else:
        lines = f.readlines()
    return csv.reader(lines,delimiter=delimiter)

def iban_de(blz,kto):
    lnd = 131400
    bak = blz*10000000000 + kto
    ban = bak*1000000 + lnd
    prf = 98 - ban % 97
    return "DE{0}{1:08d}{2:010d}".format(prf,blz,kto)

def showlist(l):
    res = ""
    for item in l:
        if item:
            res += " / "+str(item)
    return res[3:]    

def get_file(title):
    fname = sgwx.PopupGetFile(title, no_window=True)
#    if running_linux():
#        time.sleep(2)
    return fname
