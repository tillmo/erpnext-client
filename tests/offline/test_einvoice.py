"""Tests for einvoice.py (ZUGFeRD / Factur-X / XRechnung embedded in PDFs)."""
from __future__ import annotations

from pathlib import Path

import pytest

import einvoice
from support import factories as F
from support.deps import requires_pypdf

CII = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
  xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocumentContext><ram:GuidelineSpecifiedDocumentContextParameter>
    <ram:ID>urn:cen.eu:en16931:2017</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter></rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument><ram:ID>2106-4076249</ram:ID><ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime><udt:DateTimeString format="102">20260821</udt:DateTimeString></ram:IssueDateTime></rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:AssociatedDocumentLineDocument><ram:LineID>1</ram:LineID></ram:AssociatedDocumentLineDocument>
      <ram:SpecifiedTradeProduct><ram:SellerAssignedID>0131888</ram:SellerAssignedID><ram:Name>Solarkabel 4,0 schwarz 500m</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>389.5000</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="H87">2.0000</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement><ram:ApplicableTradeTax><ram:RateApplicablePercent>19.00</ram:RateApplicablePercent></ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>779.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation></ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:SpecifiedTradeProduct><ram:Name>Schrauben M8</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>12.00</ram:ChargeAmount><ram:BasisQuantity unitCode="H87">100</ram:BasisQuantity></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="H87">50</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement><ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>6.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation></ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:SpecifiedTradeProduct><ram:Name>Verpackung und Versand</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">1</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement><ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>15.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation></ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:SpecifiedTradeProduct><ram:Name>Vorkasse (100%)</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">1</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement><ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>0.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation></ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:BuyerOrderReferencedDocument><ram:IssuerAssignedID>84570</ram:IssuerAssignedID></ram:BuyerOrderReferencedDocument>
      <ram:SellerTradeParty><ram:Name>Krannich Solar GmbH &amp; Co. KG</ram:Name>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">DE814994131</ram:ID></ram:SpecifiedTaxRegistration></ram:SellerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:ApplicableTradeTax><ram:CalculatedAmount>171.00</ram:CalculatedAmount><ram:BasisAmount>900.00</ram:BasisAmount><ram:RateApplicablePercent>19.00</ram:RateApplicablePercent></ram:ApplicableTradeTax>
      <ram:SpecifiedTradeAllowanceCharge><ram:ChargeIndicator><udt:Indicator>true</udt:Indicator></ram:ChargeIndicator><ram:ActualAmount>99.00</ram:ActualAmount><ram:Reason>zzgl. Freight D</ram:Reason></ram:SpecifiedTradeAllowanceCharge>
      <ram:SpecifiedTradeAllowanceCharge><ram:ChargeIndicator><udt:Indicator>true</udt:Indicator></ram:ChargeIndicator><ram:ActualAmount>1.00</ram:ActualAmount><ram:Reason>zzgl. Insurance D</ram:Reason></ram:SpecifiedTradeAllowanceCharge>
      <ram:SpecifiedTradePaymentTerms><ram:Description>Skonto</ram:Description>
        <ram:ApplicableTradePaymentDiscountTerms><ram:CalculationPercent>3.00</ram:CalculationPercent></ram:ApplicableTradePaymentDiscountTerms></ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>800.00</ram:LineTotalAmount><ram:ChargeTotalAmount>100.00</ram:ChargeTotalAmount>
        <ram:TaxBasisTotalAmount>900.00</ram:TaxBasisTotalAmount><ram:TaxTotalAmount>171.00</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>1071.00</ram:GrandTotalAmount><ram:DuePayableAmount>1071.00</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>"""

UBL = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID>
  <cbc:ID>R-00352</cbc:ID><cbc:IssueDate>2026-07-02</cbc:IssueDate>
  <cac:OrderReference><cbc:ID>B-77</cbc:ID></cac:OrderReference>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>BVSS</cbc:Name></cac:PartyName>
    <cac:PartyTaxScheme><cbc:CompanyID>DE123456789</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>Bundesverband Steckersolar e.V.</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AllowanceCharge><cbc:ChargeIndicator>true</cbc:ChargeIndicator><cbc:AllowanceChargeReason>Versand</cbc:AllowanceChargeReason><cbc:Amount>5.00</cbc:Amount></cac:AllowanceCharge>
  <cac:TaxTotal><cbc:TaxAmount>72.20</cbc:TaxAmount>
    <cac:TaxSubtotal><cbc:TaxableAmount>380.00</cbc:TaxableAmount><cbc:TaxAmount>72.20</cbc:TaxAmount><cac:TaxCategory><cbc:Percent>19.0</cbc:Percent></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount>375.00</cbc:LineExtensionAmount><cbc:TaxExclusiveAmount>380.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount>452.20</cbc:TaxInclusiveAmount><cbc:PayableAmount>452.20</cbc:PayableAmount></cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:InvoicedQuantity unitCode="C62">1.0</cbc:InvoicedQuantity><cbc:LineExtensionAmount>375.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Mitgliedsbeitrag 2026</cbc:Name></cac:Item><cac:Price><cbc:PriceAmount>375.0000</cbc:PriceAmount></cac:Price></cac:InvoiceLine>
</Invoice>"""


class TestCII:
    def test_parse(self) -> None:
        d = einvoice.parse_xml(CII.encode("utf-8"))
        assert d is not None
        assert d["source"] == "einvoice" and d["profile"] == "en16931:2017"
        assert d["supplier"] == "Krannich Solar GmbH & Co. KG" and d["supplier_tax_id"] == "DE814994131"
        assert d["bill_no"] == "2106-4076249" and d["posting_date"] == "2026-08-21" and d["order_id"] == "84570"
        assert d["taxes"] == [{"rate": 19.0, "net": 900.0, "tax_amount": 171.0}]
        assert d["total"] == 900.0 and d["grand_total"] == 1071.0 and d["skonto_percent"] == 3.0
        # header charges (99 + 1) plus the shipping line (15); the prepayment line is dropped
        assert d["shipping"] == 115.0
        assert [i["description"] for i in d["items"]] == ["Solarkabel 4,0 schwarz 500m", "Schrauben M8"]
        assert d["items"][0] == {"item_code": "0131888", "description": "Solarkabel 4,0 schwarz 500m", "qty": 2.0, "uom": "Stk",
                                 "rate": 389.5, "amount": 779.0}
        assert d["items"][1]["rate"] == 0.12 and d["items"][1]["item_code"] is None      # price per 100 pieces

    def test_no_reference_placeholder(self) -> None:
        d = einvoice.parse_xml(CII.replace("<ram:IssuerAssignedID>84570", "<ram:IssuerAssignedID>Keine Referenz angegeben").encode())
        assert d is not None and d["order_id"] is None


class TestUBL:
    def test_parse(self) -> None:
        d = einvoice.parse_xml(UBL.encode("utf-8"))
        assert d is not None
        assert d["supplier"] == "Bundesverband Steckersolar e.V." and d["supplier_tax_id"] == "DE123456789"
        assert d["bill_no"] == "R-00352" and d["posting_date"] == "2026-07-02" and d["order_id"] == "B-77"
        assert d["taxes"] == [{"rate": 19.0, "net": 380.0, "tax_amount": 72.2}]
        assert d["total"] == 380.0 and d["grand_total"] == 452.2 and d["shipping"] == 5.0
        assert d["items"] == [{"item_code": None, "description": "Mitgliedsbeitrag 2026", "qty": 1.0, "uom": "Stk", "rate": 375.0, "amount": 375.0}]
        assert d["profile"] == "xrechnung_3.0"


class TestHelpers:
    def test_dates_numbers_units(self) -> None:
        assert einvoice._date("20260821") == "2026-08-21" and einvoice._date("2026-08-21") == "2026-08-21"
        assert einvoice._date("21.08.2026") is None and einvoice._date(None) is None
        assert einvoice._num("1234,56") == 1234.56 and einvoice._num(" ") is None and einvoice._num("x") is None
        assert einvoice.UNITS["H87"] == "Stk" and einvoice.UNITS["MTR"] == "m"

    def test_other_xml(self) -> None:
        assert einvoice.parse_xml(b"<foo/>") is None
        assert einvoice.parse_xml(b"kein xml") is None
        assert einvoice.extract_xml(b"%PDF-1.4 kein echtes PDF") is None


@requires_pypdf
class TestPdf:
    def test_read_pdf(self, tmp_path: Path) -> None:
        path = F.write_einvoice_pdf(tmp_path / "krannich.pdf", CII)
        d = einvoice.read_pdf(str(path))
        assert d is not None and d["bill_no"] == "2106-4076249"
        assert einvoice.read_pdf(F.write_generic_invoice_pdf(tmp_path / "plain.pdf")) is None
        assert einvoice.read_pdf(str(tmp_path / "fehlt.pdf")) is None

    def test_other_attachments_are_ignored(self, tmp_path: Path) -> None:
        path = F.write_einvoice_pdf(tmp_path / "x.pdf", "<other/>", name="notes.xml")
        assert einvoice.read_pdf(str(path)) is None
