
DEFAULT_ITEM_CODE = "000.000.000"
MATERIAL_ITEM_CODE = '000.100.301'
DEFAULT_ITEMS = ['026.000.315','026.000.600']
MATERIAL_ITEM_VALUE = 100.0
DEFAULT_SUPPLIER_GROUP = "Lieferant"
WAREHOUSE = 'Lagerräume - SoMiKo'
PROJECT_WAREHOUSE = 'Laufende Arbeit/-en - SoMiKo'
STANDARD_PRICE_LIST = 'Standard-Vertrieb'
STANDARD_ITEM_GROUP = 'Produkte'
PROJECT_ITEM_GROUP = 'Material Solaranlagen'
PROJECT_UNIT = 'Materialeinheit 1€'
STOCK_PROJECT_TYPES =  ['Balkonmodule','Solaranlagenmaterial']
LUMP_SUM_STOCK_PROJECT_TYPES =  ['Solaranlage']
STOCK_ITEM_GROUPS = ['Solarmodul','Balkon-Solarmodule','Wechselrichter','Steckdosen','Batterie']
STANDARD_NAMING_SERIES_PINV = 'EK .YYYY.-'
VAT_DESCRIPTION = 'Umsatzsteuer'
DELIVERY_COST_ACCOUNT = '3800 - Bezugsnebenkosten - SoMiKo'
DELIVERY_COST_DESCRIPTION = 'Bezugsnebenkosten'
VALIDITY_DATE = '2020-10-01'

NKK_ACCOUNTS = {19.0: '3401 - NKK 19% Vorsteuer - Laden',
                7.0: '3301 - NKK 7% Vorsteuer - Laden'}
KORNKRAFT_ACCOUNTS = {19.0: '3402 - Kornkraft 19% Vorsteuer - Laden',
                7.0: '3302 - Kornkraft 7% Vorsteuer - Laden'}
SOMIKO_ACCOUNTS = {19.0: '4996 - Herstellungskosten - SoMiKo'}

BALANCE_ACCOUNTS = \
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

PAYABLE_ACCOUNTS = \
 {'Bremer SolidarStrom':
  {'advance' : '1518 - Geleistete Anzahlungen, 19 % Vorsteuer - SoMiKo',
   'post' : '1600 - IV. Verbindlichkeiten aus Lieferungen und Leistungen - SoMiKo'}
 }

RECEIVABLE_ACCOUNTS = \
 {'Bremer SolidarStrom':
  {'advance' : '1718 - Erhaltene, versteuerte Anzahlungen 19 % USt (Verbindlichkeiten) - SoMiKo',
   'post' : '1400 - Forderungen aus Lieferungen und Leistungen - SoMiKo'}
 }

TAX_ACCOUNTS = \
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

INCOME_DIST_ACCOUNTS = \
 {'Laden':
    {'income' : [{'unclear' : '8503 - Ladenkasse Ust. noch unklar - Laden',
                  7 : '8301 - Ladenkasse Ust.7% - Laden',
                  19: '8401 - Ladenkasse Ust.19% - Laden'},
                 {'unclear' :  '8502 - Café an Laden USt. noch unklar - Laden',
                  7 : '8402 - Café an Laden Ust.19% - Laden',
                  19 : '8403 - Bieterrunde Laden Ust.19% - Laden'}, 
                 {'unclear' : '8501 - Bieterrunde USt. noch unklar - Laden',
                  7 : '8302 - Café an Laden Ust.7% - Laden',
                  19 :'8303 - Bieterrunde Laden Ust.7% - Laden'}],
     'expense' : { 7 : '3300 - Wareneingang 7% Vorsteuer - Laden',
                   19 : '3400 - Wareneingang 19% Vorsteuer - Laden'},
     'tax' : {7 : '1771 - Umsatzsteuer 7% - Laden',
              19 : '1776 - Umsatzsteuer 19% - Laden'}
    }
 }

INCOME_ACCOUNTS = \
 {'Laden':
    {7 : ['8301 - Ladenkasse Ust.7% - Laden',
          '8402 - Café an Laden Ust.19% - Laden',
          '8302 - Café an Laden Ust.7% - Laden'],
     19: ['8401 - Ladenkasse Ust.19% - Laden',
          '8403 - Bieterrunde Laden Ust.19% - Laden', 
          '8303 - Bieterrunde Laden Ust.7% - Laden']},
  'Bremer SolidarStrom':
    {19: ['8401 - Selbstbauanlagen - SoMiKo',
          '8402 - Selbstbausets - SoMiKo',
          '8403 - Balkonmodule - SoMiKo',
          '8404 - Neukund*innen Ökostrom - SoMiKo']},
  'Soli e.V.': {}
 }
