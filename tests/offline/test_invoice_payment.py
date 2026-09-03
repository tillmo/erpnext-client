"""Tests for invoice.Invoice, invoice.accrual and payment.create_payment."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, NoReturn

import pytest

import invoice
import payment
from api import Api
from company import Company
from support import factories as F
from support.fakes import FakeFrappeClient
from support.stubs import UserSettings


def pinv_doc(**over: Any) -> dict[str, Any]:
    d = {"name": "EK 2026-00001", "company": F.COMPANY, "posting_date": "2026-03-01", "status": "Unpaid",
         "grand_total": 119.0, "outstanding_amount": 119.0, "supplier": "Lieferant A", "bill_no": "RE-1",
         "is_return": 0}
    d.update(over)
    return d


def strip_meta(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items() if k not in ("idx", "parent", "parenttype", "parentfield")} for r in rows]


def sinv_doc(**over: Any) -> dict[str, Any]:
    d = {"name": "R 2026-00001", "company": F.COMPANY, "posting_date": "2026-03-02", "status": "Unpaid",
         "grand_total": 238.0, "outstanding_amount": 238.0, "customer": "Kunde K", "is_return": 0}
    d.update(over)
    return d


class TestInvoiceInit:
    def test_purchase_invoice(self, fake_api: FakeFrappeClient) -> None:
        inv = invoice.Invoice(pinv_doc(), False)
        assert inv.doctype == "Purchase Invoice"
        assert inv.reference == "RE-1"
        assert inv.party == "Lieferant A" and inv.party_type == "Supplier"
        assert inv.amount == -119.0
        assert inv.outstanding == 119.0
        assert inv.is_return == 0
        assert inv.date == "2026-03-01" and inv.status == "Unpaid"

    def test_purchase_invoice_without_bill_no_uses_name(self, fake_api: FakeFrappeClient) -> None:
        inv = invoice.Invoice(pinv_doc(bill_no=None), False)
        assert inv.reference == "EK 2026-00001"

    def test_sales_invoice(self, fake_api: FakeFrappeClient) -> None:
        inv = invoice.Invoice(sinv_doc(), True)
        assert inv.doctype == "Sales Invoice"
        assert inv.reference == "R 2026-00001"
        assert inv.party == "Kunde K" and inv.party_type == "Customer"
        assert inv.amount == 238.0

    def test_is_return_optional(self, fake_api: FakeFrappeClient) -> None:
        d = sinv_doc()
        del d["is_return"]
        inv = invoice.Invoice(d, True)
        assert not hasattr(inv, "is_return")


class TestInvoicePayment:
    def test_purchase_payment_creates_pay_entry(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        inv = invoice.Invoice(pinv_doc(), False)
        p = inv.payment("Bank - SoMiKo", 119.0, "2026-03-05")
        assert p["payment_type"] == "Pay"
        assert p["paid_from"] == "Bank - SoMiKo"
        assert p["paid_to"] == somiko.payable_account
        assert p["party"] == "Lieferant A" and p["party_type"] == "Supplier"
        assert p["paid_amount"] == p["received_amount"] == 119.0
        assert p["reference_no"] == "RE-1"
        assert p["title"] == "Lieferant A RE-1"
        assert strip_meta(p["references"]) == [{"reference_doctype": "Purchase Invoice",
                                                "reference_name": "EK 2026-00001", "allocated_amount": 119.0}]
        assert p["posting_date"] == p["reference_date"] == "2026-03-05"
        assert p["docstatus"] == 0 and p["unallocated_amount"] == 0.0

    def test_sales_payment_creates_receive_entry(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        inv = invoice.Invoice(sinv_doc(), True)
        p = inv.payment("Bank - SoMiKo", 100.0, "2026-03-05")
        assert p["payment_type"] == "Receive"
        assert p["paid_from"] == somiko.receivable_account
        assert p["paid_to"] == "Bank - SoMiKo"
        assert p["references"][0]["reference_doctype"] == "Sales Invoice"
        assert p["unallocated_amount"] == 0.0

    def test_zero_amount_creates_nothing(self, somiko: Company, fake_api: FakeFrappeClient,
                                         capsys: pytest.CaptureFixture[str]) -> None:
        inv = invoice.Invoice(sinv_doc(), True)
        assert inv.payment("Bank - SoMiKo", 0, "2026-03-05") is None
        assert "Ausstehender Betrag ist 0" in capsys.readouterr().out
        assert fake_api.calls_of("insert") == []

    def test_use_advance_payment(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        name = fake_api.add("Purchase Invoice", **pinv_doc())
        py_name = fake_api.add("Payment Entry", remarks="Anzahlung", paid_amount=50.0, party="Lieferant A")
        import doc
        py = doc.Doc(name=py_name, doctype="Payment Entry")
        inv = invoice.Invoice(fake_api.get_doc("Purchase Invoice", name), False)
        inv.use_advance_payment(py)
        stored = fake_api.get_doc("Purchase Invoice", name)
        assert strip_meta(stored["advances"]) == [{"reference_type": "Payment Entry", "reference_name": py_name,
                                                   "remarks": "Anzahlung", "advance_amount": 50.0,
                                                   "allocated_amount": 50.0}]

    def test_payment_from_bank_transaction_submits(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        bacc = F.make_bank_account(fake_api, somiko)
        import bank
        bt_name = fake_api.add("Bank Transaction", **F.bank_transaction_doc(bacc.name, withdrawal=119.0))
        bt = bank.BankTransaction(fake_api.get_doc("Bank Transaction", bt_name))
        inv = invoice.Invoice(fake_api.get_doc("Purchase Invoice", fake_api.add("Purchase Invoice", **pinv_doc())), False)
        inv.payment_from_bank_transaction(bt)
        pes = fake_api.get_list("Payment Entry", fields=["name", "docstatus", "paid_amount"])
        assert len(pes) == 1 and pes[0]["docstatus"] == 1 and pes[0]["paid_amount"] == 119.0
        stored_bt = fake_api.get_doc("Bank Transaction", bt_name)
        assert stored_bt["status"] == "Reconciled"
        assert stored_bt["payment_entries"][0]["payment_entry"] == pes[0]["name"]


class TestCreatePayment:
    def test_negative_amount_flips_direction(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        p = payment.create_payment(True, somiko, "Bank - SoMiKo", -40.0, "2026-01-01", "Kunde", "Customer", "ref", [])
        assert p["payment_type"] == "Pay" and p["paid_amount"] == 40.0
        assert p["paid_from"] == "Bank - SoMiKo" and p["paid_to"] == somiko.payable_account

    def test_exchange_rates_and_company(self, somiko: Company, fake_api: FakeFrappeClient) -> None:
        p = payment.create_payment(False, somiko, "Bank - SoMiKo", 10.0, "2026-01-01", "L", "Supplier", "r", [])
        assert p["company"] == somiko.name
        assert p["finance_book"] == somiko.default_finance_book
        assert (p["source_exchange_rate"], p["target_exchange_rate"], p["exchange_rate"]) == (1.0, 1.0, 1.0)

    def test_buchen_setting_submits(self, somiko: Company, fake_api: FakeFrappeClient, user_settings: UserSettings,
                                    capsys: pytest.CaptureFixture[str]) -> None:
        user_settings["-buchen-"] = True
        p = payment.create_payment(False, somiko, "Bank - SoMiKo", 10.0, "2026-01-01", "L", "Supplier", "r", [])
        assert fake_api.get_doc("Payment Entry", p["name"])["docstatus"] == 1
        out = capsys.readouterr().out
        assert "erstellt" in out and "gebucht" in out

    def test_insert_failure_returns_none(self, somiko: Company, fake_api: FakeFrappeClient,
                                         monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        def broken(doc: dict[str, Any]) -> NoReturn:
            raise RuntimeError("Server weg")
        monkeypatch.setattr(fake_api, "insert", broken)
        assert payment.create_payment(False, somiko, "B", 1.0, "2026-01-01", "L", "Supplier", "r", []) is None
        assert "Server weg" in capsys.readouterr().out


class TestAccrual:
    def test_accrual_classifies_invoices(self, fake_api: FakeFrappeClient, in_tmp_cwd: Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
        c = F.COMPANY
        fake_api.add("Sales Invoice", name="R 2025-1", company=c, docstatus=1, total=10, posting_date="2025-05-01")
        fake_api.add("Sales Invoice", name="R 2025-2", company=c, docstatus=1, total=10, posting_date="2025-06-01")
        fake_api.add("Sales Invoice", name="R 2025-3", company=c, docstatus=0, total=10, posting_date="2025-06-01")
        fake_api.add("Purchase Invoice", name="EK 2025-1", company=c, docstatus=1, total=10, posting_date="2025-07-01",
                     supplier_invoice="/private/files/ek1.pdf")
        fake_api.add("Purchase Invoice", name="EK 2024-9", company=c, docstatus=1, total=10, posting_date="2024-12-01")
        fake_api.add_file("/private/files/ek1.pdf", b"%PDF-1.4 x")
        fake_api.add("Payment Entry", name="PAY-1", company=c, docstatus=1, posting_date="2025-05-10",
                     references=[{"reference_doctype": "Sales Invoice", "reference_name": "R 2025-1"},
                                 {"reference_doctype": "Purchase Invoice", "reference_name": "EK 2024-9"}])
        fake_api.add("Payment Entry", name="PAY-2", company=c, docstatus=1, posting_date="2025-05-11",
                     references=[{"reference_doctype": "Sales Invoice", "reference_name": "R 2024-8"}])
        sinvs, sinvs_old, pinvs, pinvs_old = invoice.accrual(c, 2025)
        assert sinvs == ["R 2025-2"]          # issued in 2025, not paid in 2025
        assert sinvs_old == ["R 2024-8"]      # paid in 2025, but not from 2025
        assert pinvs == ["EK 2025-1"]
        assert pinvs_old == ["EK 2024-9"]
        assert os.path.exists(in_tmp_cwd / "EK 2025-1.pdf")
        out = capsys.readouterr().out
        assert "Verkaufsrechnungen aus 2025, die 2026 bezahlt wurden: R 2025-2" in out
