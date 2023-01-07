
DEFAULT_ITEM_CODE = "000.000.000"
DEFAULT_SUPPLIER_GROUP = "Lieferant"
WAREHOUSE = 'Wielandstr. 33 - SoMiKo'
STANDARD_PRICE_LIST = 'Standard-Vertrieb'
STANDARD_ITEM_GROUP = 'Produkte'
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
    'Anzahlungen Verkauf':(['1400 - Ausstände - SoMiKo'],1),
    'Anzahlungen Einkauf':(['1600 - IV. Verbindlichkeiten aus Lieferungen und Leistungen - SoMiKo'],1),
    'Summe Aktiva': (['I. Vorräte - SoMiKo','Bank - SoMiKo','1600 - IV. Verbindlichkeiten aus Lieferungen und Leistungen - SoMiKo'],1),
    'Summe Passiva': (['A. Eigenkapital - SoMiKo','1400 - Ausstände - SoMiKo'],1),
   }
 }

TAX_ACCOUNTS = \
 {'Bremer SolidarStrom':
  {'tax_pay_account' : '1780 - Umsatzsteuer-Vorauszahlung - SoMiKo',
   'pre_tax_accounts' : ['1576 - Abziehbare VSt. 19% - SoMiKo'],
   'tax_accounts' : ['1776 - Umsatzsteuer 19% - SoMiKo']},
  'Laden':
  {'tax_pay_account' : '1780 - Umsatzsteuer-Vorauszahlung - Laden',
   'pre_tax_accounts' : ['1576 - Abziehbare VSt. 19% - Laden'],
   'tax_accounts' : ['1776 - Umsatzsteuer 19% - Laden']}
 }
