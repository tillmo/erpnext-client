"""bank.py against real bank accounts and bank transactions (read-only)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import bank
from support import factories as F
from support.live import LiveState
from support.stubs import EasyguiStub

SUPPORTED_BLZ = {"83094495": "sparda", "25090500": "sparda", "29050101": "sparkasse"}


class TestBankAccounts:
    def test_registries(self, live: LiveState) -> None:
        baccs = list(bank.BankAccount.baccounts_by_name.values())
        if not baccs:
            pytest.skip("keine Bankkonten")
        for b in baccs:
            assert bank.BankAccount.baccounts_by_iban[b.iban] is b
            assert b.company is not None and b in bank.BankAccount.baccounts_by_company[b.company.name]
            assert isinstance(b.iban, str) and b.iban.upper().startswith("DE") and len(b.iban.replace(" ", "")) == 22
            assert len(b.blz()) == 8 and b.blz().isdigit()
            assert isinstance(b.balance, float) and b.e_account
            assert "last_integration_date" in b.doc

    def test_baccount_names_for_company(self, live: LiveState) -> None:
        names = bank.BankAccount.get_baccount_names()
        assert set(names) == {b.name for b in live.bank_accounts()}

    def test_iban_check_digits_valid(self, live: LiveState) -> None:
        for b in live.bank_accounts():
            iban = b.iban.replace(" ", "")
            numeric = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
            assert int(numeric) % 97 == 1, "IBAN {} ungültig".format(iban)


class TestStatementDetection:
    def test_get_baccount_recognises_real_iban(self, live: LiveState, tmp_path: Path) -> None:
        baccs = live.bank_accounts()
        if not baccs:
            pytest.skip("keine Bankkonten")
        b = baccs[0]
        fn = F.write_sparkasse_csv(tmp_path / "k.csv", [{"date": "01.01.26", "purpose": "x", "partner": "y", "amount": "1,00"}],
                                   iban=b.iban)
        assert bank.BankStatement.get_baccount(fn) == (b, b.iban)

    def test_read_statement_for_supported_bank(self, live: LiveState, tmp_path: Path, gui: EasyguiStub) -> None:
        baccs = [b for b in live.bank_accounts() if b.blz() in SUPPORTED_BLZ]
        if not baccs:
            pytest.skip("kein Bankkonto mit unterstützter BLZ (Sparkasse Bremen, Sparda, Ethikbank)")
        b = baccs[0]
        rows_spk = [{"date": "01.01.26", "purpose": "Test", "partner": "P", "amount": "1,00"}]
        rows_sparda = [{"date": "01.01.2026", "partner": "P", "purpose": "Test", "amount": "1,00", "balance": "1,00"}]
        if SUPPORTED_BLZ[b.blz()] == "sparkasse":
            fn = F.write_sparkasse_csv(tmp_path / "k.csv", rows_spk, iban=b.iban)
        else:
            fn = F.write_sparda_csv(tmp_path / "k.csv", rows_sparda, iban=b.iban)
        stmt = bank.BankStatement.read_statement(fn)
        assert stmt is not None and stmt.baccount is b and len(stmt.entries) == 1

    def test_unsupported_bank_is_reported(self, live: LiveState, tmp_path: Path, gui: EasyguiStub) -> None:
        gui.answers["msgbox"] = None
        fn = F.write_sparkasse_csv(tmp_path / "k.csv", [{"date": "01.01.26", "purpose": "x", "partner": "y", "amount": "1,00"}],
                                   iban=F.IBAN_FREMD)
        assert bank.BankStatement.read_statement(fn) is None
        assert "Konto unbekannt" in gui.calls[-1][1][0]


class TestQueries:
    def test_find_bank_transaction_with_existing_description(self, live: LiveState, api: Any) -> None:
        bts = api.get_list("Bank Transaction", fields=bank.BT_FIELDS,
                           filters={"company": live.company_name, "status": "Pending"}, limit_page_length=5)
        if not bts:
            pytest.skip("keine offenen Banktransaktionen")
        bt = bts[0]
        word = next((w for w in (bt["description"] or "").split() if len(w) > 3), None)
        if not word:
            pytest.skip("Beschreibung ohne brauchbares Wort")
        total = bt["deposit"] if bt["deposit"] else -bt["withdrawal"]
        found = bank.BankTransaction.find_bank_transaction(live.company_name, total, word)
        assert found is None or found.name == bt["name"] or found.description

    def test_bank_transaction_object(self, live: LiveState, api: Any) -> None:
        bts = api.get_list("Bank Transaction", fields=bank.BT_FIELDS, filters={"company": live.company_name},
                           limit_page_length=3)
        for doc in bts:
            bt = bank.BankTransaction(doc)
            assert bt.baccount.name == doc["bank_account"]
            assert bt.amount == (doc["deposit"] or -doc["withdrawal"])
            assert bt.show().startswith(doc["name"])
