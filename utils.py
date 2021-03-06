TITLE = "ERPNext-Client für "

from version import VERSION 
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import csv
import codecs
import sys
import time
import numpy as np
import tempfile
import os

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
        s1 = '-'+s1[:-1]
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

def title():
    settings = sg.UserSettings()
    company = settings.get('-company-', 'Unbekannt')
    server = settings.get('-server-', 'unbekannt')
    return f'{TITLE}{company}@{server} {VERSION}'

def find_ref(line):
    for w in line.split():
        if "TAN" in w:
            return "unbekannt"
        if len(w)>4:
            if sum(c.isdigit() for c in w)>3:
                return w
    return "unbekannt"

def to_str(x):
    if type(x) in [float,np.float32,np.float64]:
        return "{: >9.2f}".format(x).replace(".",",")
    d = show_date4(x)
    if d:
        return d
    else:
        return x

def get(e,k):
    if k in e:
        return e[k]
    else:
        return ""

def format_entry(doc,keys,headings):
    return "\n".join([h+": "+to_str(get(doc,k)) for (k,h) in zip(keys,headings)])

def format_dic(bool_fields,path_fields,dic):
    for field in bool_fields:
        if field in dic:
            if dic[field]:
                dic[field] = "✓"
            else:
                dic[field] = " "
    for field in path_fields:
        dic["short_"+field] = dic[field].split("/")[-1]
    return dic

def store_temp_file(data,ext):
    new_file, filename = tempfile.mkstemp(suffix=ext)
    with os.fdopen(new_file,'wb') as f:
        f.write(data)
    return filename
    
def get_current_location(window):
    import inspect
    if 'more_accurate' in inspect.signature(window.current_location).parameters:
        return window.current_location(more_accurate=True)

    # return invalid location because an inaccurate location is more annoying than no location
    return (None, None)
