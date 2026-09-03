"""Kontoauszug einlesen, Banktransaktionen zuordnen, wieder auflösen - gegen die Testinstanz.

Voraussetzung: ein Bankkonto der Firma mit unterstützter BLZ (Sparkasse Bremen 29050101,
Sparda 25090500, Ethikbank 83094495). Das Feld last_integration_date des Bankkontos wird
am Ende auf den alten Wert zurückgesetzt.
"""
import pytest

import bank
from api import Api
from frappeclient import FrappeException
from support import factories as F
from support.live import tag

SUPPORTED = {"29050101": "sparkasse", "25090500": "sparda", "83094495": "sparda"}


@pytest.fixture
def bacc(live, api, cleanup):
    baccs = [b for b in live.bank_accounts() if b.blz() in SUPPORTED]
    if not baccs:
        pytest.skip("kein Bankkonto der Firma mit unterstützter BLZ")
    b = baccs[0]
    original = api.get_doc("Bank Account", b.name)
    old_date = original.get("last_integration_date")
    old_doc = dict(b.doc)

    def restore():
        api.update_with_doctype({"name": b.name, "last_integration_date": old_date}, "Bank Account")
        b.doc = old_doc
        b.statement_balance = None
    cleanup.restore(restore)
    return b


def write_statement(bacc, tmp_path, rows):
    if SUPPORTED[bacc.blz()] == "sparkasse":
        return F.write_sparkasse_csv(tmp_path / "auszug.csv", rows, iban=bacc.iban)
    sparda_rows = [{"date": F.datetime.datetime.strptime(r["date"], "%d.%m.%y").strftime("%d.%m.%Y"),
                    "partner": r["partner"], "purpose": r["purpose"], "amount": r["amount"], "balance": "0,00"}
                   for r in rows]
    return F.write_sparda_csv(tmp_path / "auszug.csv", sparda_rows, iban=bacc.iban)


def find_transactions(api, marker):
    return api.get_list("Bank Transaction", fields=bank.BT_FIELDS + ["docstatus"],
                        filters={"description": ["like", "%" + marker + "%"]}, limit_page_length=50)


def test_import_reconcile_and_undo(live, api, cleanup, bacc, tmp_path, today, capsys):
    marker = tag("KA")
    rows = [{"date": "15.08.26", "purpose": "Miete " + marker, "partner": "Vermieter", "amount": "-12,34"},
            {"date": "16.08.26", "purpose": "Spende " + marker, "partner": "Foerderer", "amount": "56,78"}]
    fn = write_statement(bacc, tmp_path, rows)

    # 1) Import
    stmt = bank.BankStatement.process_file(fn)
    assert stmt is not None and len(stmt.entries) == 2 and len(stmt.transactions) == 2
    bts = find_transactions(api, marker)
    for bt in bts:
        cleanup.add("Bank Transaction", bt["name"])
    assert len(bts) == 2
    by_desc = {bt["description"]: bt for bt in bts}
    miete = by_desc["Miete {} Vermieter".format(marker)]
    spende = by_desc["Spende {} Foerderer".format(marker)]
    assert miete["withdrawal"] == pytest.approx(12.34) and miete["unallocated_amount"] == pytest.approx(12.34)
    assert spende["deposit"] == pytest.approx(56.78) and spende["status"] == "Pending"
    assert miete["bank_account"] == bacc.name and miete["company"] == live.company_name
    assert miete["date"] == "2026-08-15"
    assert api.get_doc("Bank Account", bacc.name)["last_integration_date"] == today

    # 2) erneuter Import legt nichts an
    stmt2 = bank.BankStatement.process_file(fn)
    assert stmt2.transactions == []
    assert len(find_transactions(api, marker)) == 2

    # 3) Zuordnung zu einem Aufwandskonto -> Buchungssatz, Transaktion abgeglichen
    bt = bank.BankTransaction(api.get_doc("Bank Transaction", miete["name"]))
    bt.journal_entry(live.expense_leaf(), False)
    je_name = bt.doc["payment_entries"][0]["payment_entry"]
    cleanup.add("Journal Entry", je_name)   # nach den Transaktionen registriert -> wird zuerst gelöscht
    je = api.get_doc("Journal Entry", je_name)
    assert je["docstatus"] == 0 and je["total_debit"] == pytest.approx(12.34)
    assert {a["account"] for a in je["accounts"]} == {bacc.e_account, live.expense_leaf()}
    stored = api.get_doc("Bank Transaction", miete["name"])
    assert stored["status"] == "Reconciled" and stored["unallocated_amount"] == pytest.approx(0)
    assert stored["payment_entries"][0]["payment_entry"] == je_name
    assert je_name not in {bt_["name"] for bt_ in live.company.open_bank_transactions()}

    # 4) Rückgängig: Buchungssatz löschen, Transaktion wieder offen
    bank.BankTransaction.delete_entry(je_name)
    with pytest.raises(FrappeException):
        api.get_doc("Journal Entry", je_name)
    stored = api.get_doc("Bank Transaction", miete["name"])
    assert stored["status"] == "Pending" and stored["unallocated_amount"] == pytest.approx(12.34)
    assert stored["payment_entries"] == []
    assert "angepasst" in capsys.readouterr().out


def test_find_bank_transaction_by_bill_no(live, api, cleanup, bacc, tmp_path):
    marker = tag("RE")
    fn = write_statement(bacc, tmp_path, [{"date": "17.08.26", "purpose": "Rechnung " + marker, "partner": "L",
                                           "amount": "-119,00"}])
    bank.BankStatement.process_file(fn)
    bts = find_transactions(api, marker)
    for bt in bts:
        cleanup.add("Bank Transaction", bt["name"])
    found = bank.BankTransaction.find_bank_transaction(live.company_name, -119.0, marker)
    assert found is not None and found.name == bts[0]["name"]
    assert bank.BankTransaction.find_bank_transaction(live.company_name, -118.0, marker) is None


def test_submit_entry_books_transaction_and_journal(live, api, cleanup, bacc, tmp_path, submit_allowed):
    marker = tag("BUCH")
    fn = write_statement(bacc, tmp_path, [{"date": "18.08.26", "purpose": "Buchen " + marker, "partner": "P",
                                           "amount": "-1,00"}])
    bank.BankStatement.process_file(fn)
    bt_doc = find_transactions(api, marker)[0]
    cleanup.add("Bank Transaction", bt_doc["name"])
    bt = bank.BankTransaction(api.get_doc("Bank Transaction", bt_doc["name"]))
    bt.journal_entry(live.expense_leaf(), False)
    je_name = bt.doc["payment_entries"][0]["payment_entry"]
    cleanup.add("Journal Entry", je_name)
    bank.BankTransaction.submit_entry(je_name)
    assert api.get_doc("Journal Entry", je_name)["docstatus"] == 1
    assert api.get_doc("Bank Transaction", bt_doc["name"])["docstatus"] == 1
