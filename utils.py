from __future__ import annotations

TITLE = "ERPNext-Client für "

from version import VERSION 
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
from difflib import SequenceMatcher
import csv
import codecs
import sys
import time
import numpy as np
import tempfile
import os
import locale
from collections import defaultdict
import subprocess
from typing import Any, Iterable, Iterator, Mapping

def running_linux() -> bool:
    return sys.platform.startswith('linux')

import PySimpleGUI as sg
if running_linux():
    import PySimpleGUIWx as sgwx
else:
    sgwx = sg


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def convert_date_written_month(date: str) -> str | None:
    try:
        locale.setlocale(locale.LC_ALL, 'de_DE.utf8')
        d = datetime.strptime(date, '%d. %B %Y')
        return d.strftime('%Y-%m-%d')
    except Exception:
        return None

def convert_date4(date: str) -> str | None:
    try:
        d = datetime.strptime(date, '%d.%m.%Y')
        return d.strftime('%Y-%m-%d')
    except Exception:
        try:
            d = datetime.strptime(date, '%m/%d/%Y')
            return d.strftime('%Y-%m-%d')
        except Exception:
            return None

def convert_date2(date: str) -> str | None:
    try:
        d = datetime.strptime(date, '%d.%m.%y')
        return d.strftime('%Y-%m-%d')
    except Exception:
        return None

def show_date4(date: Any) -> str | None:
    try:
        d = datetime.strptime(date, '%Y-%m-%d')
        return d.strftime('%d.%m.%Y')
    except Exception:
        return None

def yesterday(date: str) -> str:
    d = datetime.strptime(date, '%Y-%m-%d')
    d = d-timedelta(1)
    return d.strftime('%Y-%m-%d')

def last_quarter(date: date) -> str:
    d = date-timedelta(days=90)
    return "{}-{:02d}".format(d.year,(d.month+2)//3) 

def quarter_to_dates(quarter: str) -> tuple[str, str]:
    year,q = quarter.split("-")
    d = date(int(year),int(q)*3-2,1)
    start_date = d.strftime('%Y-%m-%d')
    d += relativedelta(months=3) - relativedelta(days=1)
    end_date = d.strftime('%Y-%m-%d')
    return (start_date,end_date)


def no_substr(l1: Iterable[str], l2: str) -> bool:
    for s in l1:
        if s in l2:
            return False
    return True    

def read_float(s: str | None, sign: str = "H") -> float:
    if not s:
        return 0.0
    s = s.replace("*","")
    try:
        english = len(s.split()[0].split('.')[-1])==2
    except:
        english = False
    if english:
        s = s.replace(",","")
    else:    
        s = s.replace(".","").replace(",",".")
    if s[-1]=='-':
        s = '-'+s[:-1]
    res = float(s.split()[0])
    if sign=="S":
        res = -res
    return res

def remove_space(str: str) -> str:
    return " ".join(str.split())

def get_csv(codec: str, infile: str, delimiter: str = ";", replacenl: bool = False) -> Iterator[list[str]]:
    f = codecs.open(infile, 'r', codec)
    if replacenl:
        lines = f.read().replace('\r\n','§#')\
                        .replace('\n',' ')\
                        .replace('§#','\n')\
                        .split('\n')
    else:
        lines = f.readlines()
    return csv.reader(lines,delimiter=delimiter)

def iban_de(blz: int, kto: int) -> str:
    lnd = 131400
    bak = blz*10000000000 + kto
    ban = bak*1000000 + lnd
    prf = 98 - ban % 97
    return "DE{0:02d}{1:08d}{2:010d}".format(prf,blz,kto)

def showlist(l: Iterable[Any]) -> str:
    res = ""
    for item in l:
        if item:
            res += " / "+str(item)
    return res[3:]    

def get_file(title: str) -> str | None:
    fname = sgwx.PopupGetFile(title, no_window=True)
#    if running_linux():
#        time.sleep(2)
    return fname

def title() -> str:
    settings = sg.UserSettings()
    company = settings.get('-company-', 'Unbekannt')
    server = settings.get('-server-', 'unbekannt')
    return f'{TITLE}{company}@{server} {VERSION}'

def find_ref(line: str) -> str:
    for w in line.split():
        if "TAN" in w:
            return "unbekannt"
        if len(w)>4:
            if sum(c.isdigit() for c in w)>3:
                return w
    return "unbekannt"

def to_str(x: Any) -> Any:
    if type(x) in [float,np.float32,np.float64]:
        return "{: >9.2f}".format(x).replace(".",",")
    d = show_date4(x)
    if d:
        return d
    else:
        return x

def get(e: Mapping[str, Any], k: str) -> Any:
    if k in e:
        return e[k]
    else:
        return ""

def format_entry(doc: Mapping[str, Any], keys: Iterable[str], headings: Iterable[str]) -> str:
    return "\n".join([h+": "+to_str(get(doc,k)) for (k,h) in zip(keys,headings)])

def format_dic(bool_fields: Iterable[str], path_fields: Iterable[str], dic: dict[str, Any]) -> dict[str, Any]:
    for field in bool_fields:
        if field in dic:
            if dic[field]:
                dic[field] = "✓"
            else:
                dic[field] = " "
    for field in path_fields:
        dic["short_"+field] = dic[field].split("/")[-1]
    for k in dic.keys():
        if type(dic[k])==str and len(dic[k])>35:
            dic[k]=dic[k][:35]
    return dic

def store_temp_file(data: bytes, ext: str) -> str:
    new_file, filename = tempfile.mkstemp(suffix=ext)
    with os.fdopen(new_file,'wb') as f:
        f.write(data)
    return filename
    
def get_current_location(window: Any) -> tuple[int | None, int | None]:
    import inspect
    if 'more_accurate' in inspect.signature(window.current_location).parameters:
        return window.current_location(more_accurate=True)

    # return invalid location because an inaccurate location is more annoying than no location
    return (None, None)

def sum_dict(dic: Mapping[Any, Mapping[Any, float]]) -> defaultdict[Any, float]:
    sums: defaultdict[Any, float] = defaultdict(lambda: 0.0)
    for c,d in dic.items():
        for k,v in d.items():
            sums[k] += v
    return sums        

def print_dict(dic: Mapping[Any, float]) -> None:
    for x,y in dic.items():
        print("{} : {:.2f}".format(x,y))

def print_dict2(dic: Mapping[Any, Mapping[Any, float]]) -> None:
    for x in dic:
        print (x)
        for y in dic[x]:
            print("{} : {:.2f}".format(y,dic[x][y]))


from bs4 import BeautifulSoup
import re

def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, features="html.parser")
    for tag in soup.find_all('style'):
        tag.decompose()
    for br in soup.find_all("br"):        # line breaks and block ends become newlines, inline tags do not
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"]):
        block.append("\n")
    text = soup.get_text()
    text = re.sub(r"[\t ]*\n\s*","\n",text)
    text = re.sub(r"[\t ]+"," ",text)
    return text.strip("\n")

# extract no. of PreRechnung
def extract_prnr(text: str) -> str | None:
    prnr = re.search(r"Pre(\d+)",text)
    if prnr:
        return prnr.group(1)
    return None

def evince(filename: str) -> None:
    subprocess.Popen(["evince", filename],
                     stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE,
                     stdin=subprocess.PIPE)
