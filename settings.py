from __future__ import annotations

from typing import Any

DEFAULT_ITEM_CODE = "000.000.000"
DEFAULT_ITEMS = ['026.000.315','026.000.600']
DEFAULT_SUPPLIER_GROUP = "Lieferant"
PLANNING_ITEM = '000.000.250'
WAREHOUSE = 'Lagerräume - SoMiKo'
PROJECT_WAREHOUSE = 'Laufende Arbeit/-en - SoMiKo'
STANDARD_PRICE_LIST = 'Standard-Vertrieb'
STANDARD_ITEM_GROUP = 'Produkte'
PROJECT_ITEM_GROUP = 'Material Solaranlagen'
PROJECT_UNIT = 'Materialeinheit 1€'

# when should the pre invoice affect the stock?
STOCK_PROJECT_TYPES =  ['Balkonmodule','Solaranlagenmaterial']
STOCK_PRE_ACCOUNTS = ['Herstellungskosten']

LUMP_SUM_STOCK_PROJECT_TYPES =  ['Solaranlage']
STOCK_ITEM_GROUPS = ['Solarmodul','Balkon-Solarmodule','Wechselrichter','Steckdosen','Batterie','Mikro-Wechselrichter']
BUNDLE_ITEM_GROUPS = ['Balkon-Anlage']
AGGREGATE_ITEMS: dict[str, str] = {'Elektro-Komponenten':'000.100.302','default':'000.100.301'}
AGGREGATE_ITEM_VALUE = 100.0
STANDARD_NAMING_SERIES_PINV = 'EK .YYYY.-'
VAT_DESCRIPTION = 'Umsatzsteuer'
DELIVERY_COST_ACCOUNT = '3800 - Bezugsnebenkosten - SoMiKo'
DELIVERY_COST_DESCRIPTION = 'Bezugsnebenkosten'
VALIDITY_DATE = '2020-10-01'
LEAD_OWNERS = ['Chris','Paul','Henrik']
CLAUDE_MODEL = 'claude-opus-5'       # invoice extraction (claude_parser.py); key via --claude-key or ANTHROPIC_API_KEY
# Check field on Lead: the server script installed by lead_dnc_setup.py keeps flagged leads
# in status "Do Not Contact" although Frappe reopens a lead on every received e-mail
LEAD_DNC_FIELD = 'custom_nicht_kontaktieren'
# Sorting of leads created from e-mails (lead_rules.py, installed by lead_rules_setup.py)
LEAD_RULE_DOCTYPE = 'Lead Absenderregel'          # block/allow list: sender domains and addresses
SUPPLIER_DOMAINS_FIELD = 'custom_email_domains'   # Small Text on Supplier, one domain per line
OWN_DOMAINS = {'bremer-solidarstrom.de', 'solidarische-oekonomie-bremen.de', 'cafe-sunshine.de'}
FREEMAIL_DOMAINS = {'gmail.com', 'googlemail.com', 'web.de', 'gmx.de', 'gmx.net', 'gmx.at', 'gmx.ch', 'gmx.com',
                    't-online.de', 'yahoo.de', 'yahoo.com', 'yahoo.fr', 'yahoo.co.uk', 'hotmail.com', 'hotmail.de',
                    'outlook.com', 'outlook.de', 'live.de', 'live.com', 'icloud.com', 'me.com', 'posteo.de',
                    'posteo.net', 'posteo.org', 'posteo.eu', 'freenet.de', 'aol.com', 'aol.de', 'mail.de', 'arcor.de',
                    'online.de', 'mailbox.org', 'protonmail.com', 'proton.me', 'ewetel.net', 'nord-com.net',
                    'magenta.de', 'vodafone.de', 'kabelmail.de', 'unitybox.de'}
# subject words typical of real requests: never mark automatically, suggest "Lead"
LEAD_POSITIVE_WORDS = ['balkonsolar', 'balkonkraftwerk', 'balkon', 'beratung', 'kontaktanfrage', 'solaranlage',
                       'solarprojekt', 'solarmodul', 'photovoltaik', 'pv-anlage', 'dach', 'installation', 'anfrage',
                       'speicher', 'wallbox', 'termin', 'interesse']
# subject words typical of supplier correspondence
LEAD_TRANSACTIONAL_WORDS = ['rechnung', 'auftragsbestätigung', 'auftragsbestaetigung', 'bestellung', 'bestellbestätigung',
                            'lieferung', 'lieferschein', 'versand', 'sendung', 'gutschrift', 'zahlung', 'mahnung',
                            'invoice', 'order', 'shipment', 'tracking', 'preisliste', 'zahlungserinnerung']
LEAD_NEWSLETTER_PATTERN = r'unsubscribe|abmelden|abbestellen|newsletter|list-unsubscribe|mailing'
# local parts (before the @) of bulk senders
LEAD_BULK_SENDERS = {'noreply', 'no-reply', 'no_reply', 'donotreply', 'do-not-reply', 'newsletter', 'news', 'marketing',
                     'mailer', 'notification', 'notifications', 'info', 'service', 'kundenservice', 'mail', 'bounce',
                     'reply', 'support', 'hello', 'hallo', 'team', 'kontakt', 'contact', 'shop', 'sales', 'vertrieb'}
EBAY_ACCOUNT = '1230 - Guthaben bei EBay - SoMiKo'

NKK_ACCOUNTS: dict[float, str] = {19.0: '3401 - NKK 19% Vorsteuer - Laden',
                7.0: '3301 - NKK 7% Vorsteuer - Laden'}
KORNKRAFT_ACCOUNTS: dict[float, str] = {19.0: '3402 - Kornkraft 19% Vorsteuer - Laden',
                7.0: '3302 - Kornkraft 7% Vorsteuer - Laden'}
SOMIKO_ACCOUNTS: dict[float, str] = {19.0: '4996 - Herstellungskosten - SoMiKo'}
SOMIKO_STOCK_ACCOUNT = '3980 - Warenbestand unsere Lager - SoMiKo'

BALANCE_ACCOUNTS: dict[str, dict[str, tuple[list[str], int]]] = \
 {'Bremer SolidarStrom':
   {
    'Einlage': (['A. Eigenkapital - SoMiKo'],1),
    'Lager':(['I. Vorräte - SoMiKo'],1),
    'Bank':(['Bank - SoMiKo'],1),
    'Anzahlungen Verkauf':(['1400 - Forderungen aus Lieferungen und Leistungen - SoMiKo'],1),
    'Anzahlungen Einkauf':(['1600 - IV. Verbindlichkeiten aus Lieferungen und Leistungen - SoMiKo'],1),
    'Summe Aktiva': (['I. Vorräte - SoMiKo','Bank - SoMiKo','1600 - IV. Verbindlichkeiten aus Lieferungen und Leistungen - SoMiKo'],1),
    'Summe Passiva': (['A. Eigenkapital - SoMiKo','1400 - Forderungen aus Lieferungen und Leistungen - SoMiKo'],1),
   }
 }

PAYABLE_ACCOUNTS: dict[str, dict[str, str]] = \
 {'Bremer SolidarStrom':
  {'advance' : '1518 - Geleistete Anzahlungen, 19 % Vorsteuer - SoMiKo',
   'post' : '1600 - IV. Verbindlichkeiten aus Lieferungen und Leistungen - SoMiKo'}
 }

RECEIVABLE_ACCOUNTS: dict[str, dict[str, str]] = \
 {'Bremer SolidarStrom':
  {'advance' : '1718 - Erhaltene, versteuerte Anzahlungen 19 % USt (Verbindlichkeiten) - SoMiKo',
   'post' : '1400 - Forderungen aus Lieferungen und Leistungen - SoMiKo'}
 }

TAX_ACCOUNTS: dict[str, dict[str, Any]] = \
 {'Bremer SolidarStrom':
  {'tax_pay_account' : '1780 - Umsatzsteuer-Vorauszahlung - SoMiKo',
   'pre_tax_accounts' : ['1576 - Abziehbare VSt. 19% - SoMiKo'],
   'tax_accounts' : ['1776 - Umsatzsteuer 19% - SoMiKo']},
  'Laden':
  {'tax_pay_account' : '1780 - Umsatzsteuer-Vorauszahlung - Laden',
   'pre_tax_accounts' : ['1576 - Abziehbare VSt. 19% - Laden',
                         '1571 - Abziehbare VSt. 7% - Laden'],
   'tax_accounts' : ['1776 - Umsatzsteuer 19% - Laden',
                     '1771 - Umsatzsteuer 7% - Laden']},
  'Soli e.V.':
  {'tax_pay_account' : None,
   'pre_tax_accounts' : [],
   'tax_accounts' : []
  }
 }

INCOME_DIST_ACCOUNTS: dict[str, dict[str, Any]] = \
 {'Laden':
    {'income' : [{'unclear' : '8503 - Ladenkasse Ust. noch unklar - Laden',
                  7 : '8301 - Ladenkasse Ust.7% - Laden',
                  19: '8401 - Ladenkasse Ust.19% - Laden'},
                 {'unclear' :  '8502 - Café an Laden USt. noch unklar - Laden',
                  7 : '8302 - Café an Laden Ust.7% - Laden',
                  19 : '8402 - Café an Laden Ust.19% - Laden'}, 
                 {'unclear' : '8501 - Bieterrunde USt. noch unklar - Laden',
                  7 : '8303 - Bieterrunde Laden Ust.7% - Laden',
                  19 :'8403 - Bieterrunde Laden Ust.19% - Laden'}],
     'expense' : { 7 : '3300 - Wareneingang 7% Vorsteuer - Laden',
                   19 : '3400 - Wareneingang 19% Vorsteuer - Laden'},
     'tax' : {7 : '1771 - Umsatzsteuer 7% - Laden',
              19 : '1776 - Umsatzsteuer 19% - Laden'}
    }
 }

INCOME_ACCOUNTS: dict[str, dict[int, list[str]]] = \
 {'Laden':
    {7 : ['8301 - Ladenkasse Ust.7% - Laden',
          '8302 - Café an Laden Ust.7% - Laden', 
          '8303 - Bieterrunde Laden Ust.7% - Laden'],
     19: ['8401 - Ladenkasse Ust.19% - Laden',
          '8402 - Café an Laden Ust.19% - Laden',
          '8403 - Bieterrunde Laden Ust.19% - Laden']},
  'Bremer SolidarStrom':
    {0: ['8291 - Selbstbauanlagen 0% - SoMiKo',
          '8292 - Selbstbausets 0% - SoMiKo',
          '8293 - Balkonmodule 0% - SoMiKo'],
    19: ['8401 - Selbstbauanlagen 19% - SoMiKo',
          '8402 - Selbstbausets 19% - SoMiKo',
          '8403 - Balkonmodule 19% - SoMiKo',
          '8404 - Neukund*innen Ökostrom 19% - SoMiKo']},
  'Soli e.V.': {}
 }
