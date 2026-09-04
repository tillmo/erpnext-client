"""Electronic invoices embedded in PDFs (ZUGFeRD / Factur-X / XRechnung).

Many suppliers attach the invoice as XML to the PDF (EN 16931). The XML is exact and complete
(totals per VAT rate, line items, charges, payment discount), so it replaces any parsing.
``read_pdf`` returns the purchase data in the client's common format (see
``purchase_invoice.PurchaseInvoice.apply_purchase_data``) or None if the PDF has no e-invoice.

Supported: CII (Cross Industry Invoice - Factur-X/ZUGFeRD in all profiles with line items, and
XRechnung CII) and the UBL syntax of XRechnung.
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from typing import Any

CII_NS = {
    'rsm': 'urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100',
    'ram': 'urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100',
    'udt': 'urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100',
}
UBL_NS = {
    'inv': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2',
    'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
}
XML_NAMES = ('factur-x.xml', 'zugferd-invoice.xml', 'xrechnung.xml', 'order-x.xml')
# UN/ECE Recommendation 20 unit codes -> ERPNext units used by the client
UNITS = {'H87': 'Stk', 'C62': 'Stk', 'EA': 'Stk', 'PCE': 'Stk', 'NAR': 'Stk', 'MTR': 'm', 'MTK': 'm²', 'MTQ': 'm³',
         'KGM': 'kg', 'GRM': 'g', 'LTR': 'l', 'HUR': 'Std', 'DAY': 'Tag', 'SET': 'Set', 'PR': 'Paar', 'XPK': 'Paket',
         'XPX': 'Palette', 'MMT': 'mm', 'CMT': 'cm', 'KWH': 'kWh', 'MON': 'Monat', 'ANN': 'Jahr', 'LS': 'Pauschale'}
SHIPPING_WORDS = ('fracht', 'freight', 'versand', 'shipping', 'transport', 'verpackung', 'porto', 'lieferkosten',
                  'insurance', 'versicherung', 'tail lift', 'hebebühne', 'terminlieferung', 'driver notification',
                  'fixed date', 'logistik')
PREPAYMENT_WORDS = ('vorkasse', 'anzahlung', 'vorauszahlung')


def extract_xml(pdf: bytes) -> bytes | None:
    """The embedded e-invoice XML of a PDF, or None."""
    try:
        import pypdf
        attachments = pypdf.PdfReader(io.BytesIO(pdf)).attachments
    except Exception:
        return None
    names = [n for n in attachments if n.lower().endswith('.xml')]
    if not names:
        return None
    names.sort(key=lambda n: (n.lower() not in XML_NAMES, n))
    for name in names:
        data = attachments[name]
        content = data[0] if isinstance(data, list) else data
        if isinstance(content, bytes) and (b'CrossIndustryInvoice' in content or b'Invoice-2' in content):
            return content
    return None


def _num(text: str | None) -> float | None:
    if text is None or not text.strip():
        return None
    try:
        return float(text.strip().replace(',', '.'))
    except ValueError:
        return None


def _date(text: str | None) -> str | None:
    """'20260821' (format 102) or '2026-08-21' -> '2026-08-21'"""
    if not text:
        return None
    t = text.strip()
    if re.fullmatch(r'\d{8}', t):
        return f"{t[:4]}-{t[4:6]}-{t[6:]}"
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', t):
        return t
    return None


def _is_shipping(name: str | None) -> bool:
    return any(w in (name or '').lower() for w in SHIPPING_WORDS)


def _is_prepayment(name: str | None) -> bool:
    return any(w in (name or '').lower() for w in PREPAYMENT_WORDS)


def _finish(data: dict[str, Any], items: list[dict[str, Any]], shipping: float) -> dict[str, Any]:
    """Shipping positions are summed into 'shipping', prepayment positions dropped (as the parsers do)."""
    kept: list[dict[str, Any]] = []
    for it in items:
        if _is_shipping(it['description']):
            shipping += it['amount'] or 0.0
        elif _is_prepayment(it['description']):
            continue
        else:
            kept.append(it)
    data['items'] = kept
    data['shipping'] = round(shipping, 2)
    if data.get('grand_total') is None and data.get('total') is not None:
        data['grand_total'] = round(data['total'] + sum(t['tax_amount'] for t in data['taxes']), 2)
    return data


def parse_cii(root: ET.Element) -> dict[str, Any]:
    ns = CII_NS

    def text(path: str, el: ET.Element = root) -> str | None:
        found = el.find(path, ns)
        return found.text.strip() if found is not None and found.text else None

    settlement = root.find('.//ram:ApplicableHeaderTradeSettlement', ns)
    summation = root.find('.//ram:SpecifiedTradeSettlementHeaderMonetarySummation', ns)
    seller_tax = None
    for reg in root.findall('.//ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID', ns):
        if reg.get('schemeID') == 'VA' and reg.text:
            seller_tax = reg.text.strip()
    taxes = []
    for t in (settlement.findall('ram:ApplicableTradeTax', ns) if settlement is not None else []):
        rate = _num(text('ram:RateApplicablePercent', t))
        if rate is None:
            continue
        taxes.append({'rate': rate, 'net': _num(text('ram:BasisAmount', t)) or 0.0,
                      'tax_amount': _num(text('ram:CalculatedAmount', t)) or 0.0})
    shipping = 0.0
    for c in (settlement.findall('ram:SpecifiedTradeAllowanceCharge', ns) if settlement is not None else []):
        charge = _num(text('ram:ActualAmount', c)) or 0.0
        if (text('ram:ChargeIndicator/udt:Indicator', c) or '').lower() == 'true':
            shipping += charge             # header charges (freight, insurance, ...) are shipping costs
        else:
            shipping -= charge             # header allowances reduce them (rare)
    for c in root.findall('.//ram:SpecifiedLogisticsServiceCharge', ns):
        shipping += _num(text('ram:AppliedAmount', c)) or 0.0
    skonto: float | None = None
    for d in root.findall('.//ram:SpecifiedTradePaymentTerms/ram:ApplicableTradePaymentDiscountTerms', ns):
        pct = _num(text('ram:CalculationPercent', d))
        if pct:
            skonto = max(skonto or 0.0, pct)
    items = []
    for li in root.findall('.//ram:IncludedSupplyChainTradeLineItem', ns):
        qty_el = li.find('ram:SpecifiedLineTradeDelivery/ram:BilledQuantity', ns)
        qty = _num(qty_el.text if qty_el is not None else None)
        unit = qty_el.get('unitCode') if qty_el is not None else None
        amount = _num(text('ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount', li))
        rate = _num(text('ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount', li))
        basis = _num(text('ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:BasisQuantity', li))
        if rate is not None and basis:
            rate = rate / basis            # price per basis quantity (e.g. per 100 pieces)
        if rate is None and qty and amount is not None:
            rate = round(amount / qty, 4)
        items.append({'item_code': text('ram:SpecifiedTradeProduct/ram:SellerAssignedID', li),
                      'description': text('ram:SpecifiedTradeProduct/ram:Name', li) or '',
                      'qty': qty, 'uom': UNITS.get(unit or '', unit or 'Stk'), 'rate': rate, 'amount': amount})
    profile = (text('.//ram:GuidelineSpecifiedDocumentContextParameter/ram:ID') or '').split(':')
    order_id = text('.//ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID')
    if order_id and 'keine referenz' in order_id.lower():
        order_id = None
    data: dict[str, Any] = {
        'source': 'einvoice',
        'profile': ':'.join(profile[-2:]) if len(profile) > 1 else (profile[0] if profile else ''),
        'supplier': text('.//ram:SellerTradeParty/ram:Name'),
        'supplier_tax_id': seller_tax,
        'bill_no': text('.//rsm:ExchangedDocument/ram:ID'),
        'posting_date': _date(text('.//rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString')),
        'order_id': order_id,
        'total': _num(text('ram:TaxBasisTotalAmount', summation)) if summation is not None else None,
        'grand_total': _num(text('ram:GrandTotalAmount', summation)) if summation is not None else None,
        'taxes': taxes,
        'skonto_percent': skonto,
    }
    return _finish(data, items, shipping)


def parse_ubl(root: ET.Element) -> dict[str, Any]:
    ns = UBL_NS

    def text(path: str, el: ET.Element = root) -> str | None:
        found = el.find(path, ns)
        return found.text.strip() if found is not None and found.text else None

    taxes = []
    for sub in root.findall('cac:TaxTotal/cac:TaxSubtotal', ns):
        rate = _num(text('cac:TaxCategory/cbc:Percent', sub))
        if rate is None:
            continue
        taxes.append({'rate': rate, 'net': _num(text('cbc:TaxableAmount', sub)) or 0.0,
                      'tax_amount': _num(text('cbc:TaxAmount', sub)) or 0.0})
    shipping = 0.0
    for c in root.findall('cac:AllowanceCharge', ns):
        charge = _num(text('cbc:Amount', c)) or 0.0
        shipping += charge if (text('cbc:ChargeIndicator', c) or '').lower() == 'true' else -charge
    skonto: float | None = None                 # UBL/XRechnung carries a discount only as free text
    items = []
    for li in root.findall('cac:InvoiceLine', ns):
        qty_el = li.find('cbc:InvoicedQuantity', ns)
        qty = _num(qty_el.text if qty_el is not None else None)
        unit = qty_el.get('unitCode') if qty_el is not None else None
        amount = _num(text('cbc:LineExtensionAmount', li))
        rate = _num(text('cac:Price/cbc:PriceAmount', li))
        basis = _num(text('cac:Price/cbc:BaseQuantity', li))
        if rate is not None and basis:
            rate = rate / basis
        items.append({'item_code': text('cac:Item/cac:SellersItemIdentification/cbc:ID', li),
                      'description': text('cac:Item/cbc:Name', li) or '',
                      'qty': qty, 'uom': UNITS.get(unit or '', unit or 'Stk'), 'rate': rate, 'amount': amount})
    seller_tax = None
    for scheme in root.findall('cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme', ns):
        if (text('cac:TaxScheme/cbc:ID', scheme) or '') == 'VAT':
            seller_tax = text('cbc:CompanyID', scheme)
    data: dict[str, Any] = {
        'source': 'einvoice',
        'profile': (text('cbc:CustomizationID') or 'ubl').split(':')[-1],
        'supplier': text('cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName')
        or text('cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name'),
        'supplier_tax_id': seller_tax,
        'bill_no': text('cbc:ID'),
        'posting_date': _date(text('cbc:IssueDate')),
        'order_id': text('cac:OrderReference/cbc:ID'),
        'total': _num(text('cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount')),
        'grand_total': _num(text('cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount')),
        'taxes': taxes,
        'skonto_percent': skonto,
    }
    return _finish(data, items, shipping)


def parse_xml(xml: bytes) -> dict[str, Any] | None:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    tag = root.tag.split('}')[-1]
    if tag == 'CrossIndustryInvoice':
        return parse_cii(root)
    if tag == 'Invoice' and root.tag.startswith('{' + UBL_NS['inv']):
        return parse_ubl(root)
    return None


def read_pdf(path: str) -> dict[str, Any] | None:
    """Purchase data from the e-invoice embedded in the PDF file, or None."""
    try:
        with open(path, 'rb') as f:
            pdf = f.read()
    except OSError:
        return None
    xml = extract_xml(pdf)
    return parse_xml(xml) if xml else None
