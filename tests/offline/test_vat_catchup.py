"""Tests for vat_catchup.py (catching up the VAT transfers to 1780 resp. 1791)."""
from __future__ import annotations

import datetime
from typing import Any

import pytest

import vat_catchup as vc
from frappeclient import FrappeException
from support.fakes import FakeFrappeClient

COMPANY = "Bremer SolidarStrom"
NAMES = {n: "{} - Konto {} - SoMiKo".format(n, n) for n in ("1571", "1576", "1577", "1771", "1776", "1787", "1780", "1791")}


def add_accounts(fake_api: FakeFrappeClient, company: str = COMPANY, numbers: Any = None) -> None:
    for n in (numbers if numbers is not None else NAMES):
        fake_api.add("Account", name=NAMES[n], account_number=n, company=company, is_group=0,
                     account_name="Konto " + n)


def gl(fake_api: FakeFrappeClient, number: str, date: str, debit: float = 0.0, credit: float = 0.0,
       company: str = COMPANY, voucher_no: str = "EK-1") -> None:
    fake_api.add("GL Entry", account=NAMES[number], posting_date=date, debit=debit, credit=credit,
                 company=company, is_cancelled=0, voucher_no=voucher_no)


class TestPeriods:
    def test_quarter_of_and_bounds(self) -> None:
        assert vc.quarter_of("2024-01-15") == "2024-Q1" and vc.quarter_of("2026-09-04") == "2026-Q3"
        assert vc.quarter_bounds("2024-Q1") == ("2024-01-01", "2024-03-31")
        assert vc.quarter_bounds("2024-Q2") == ("2024-04-01", "2024-06-30")
        assert vc.quarter_bounds("2025-Q4") == ("2025-10-01", "2025-12-31")

    def test_last_completed_quarter(self) -> None:
        assert vc.last_completed_quarter(datetime.date(2026, 9, 4)) == "2026-Q2"
        assert vc.last_completed_quarter(datetime.date(2026, 1, 31)) == "2025-Q4"
        assert vc.last_completed_quarter(datetime.date(2026, 4, 1)) == "2026-Q1"

    def test_quarters_until(self) -> None:
        assert vc.quarters_until("2024-Q3") == ["2024-Q1", "2024-Q2", "2024-Q3"]
        assert len(vc.quarters_until("2026-Q2")) == 10
        assert vc.quarters_until("2023-Q4") == []

    def test_titles_dates_offsets(self) -> None:
        assert vc.title_of("2024-Q1") == "USt-Umbuchung 2024-Q1"
        assert vc.title_of(vc.PRE_PERIOD) == "USt-Nachholung Vorjahre bis 2023"
        assert vc.posting_date_of("2024-Q2") == "2024-06-30" and vc.posting_date_of(vc.PRE_PERIOD) == "2024-01-01"
        assert vc.offset_of("2024-Q2") == "1780" and vc.offset_of(vc.PRE_PERIOD) == "1791"


class TestAccounts:
    def test_resolve(self, fake_api: FakeFrappeClient) -> None:
        add_accounts(fake_api, numbers=("1576", "1776", "1780", "1791"))
        fake_api.add("Account", name="8400 - Erlöse - SoMiKo", account_number="8400", company=COMPANY, is_group=0,
                     account_name="Erlöse")
        assert vc.resolve_accounts(fake_api, COMPANY) == {n: NAMES[n] for n in ("1576", "1776", "1780", "1791")}

    def test_balances(self, fake_api: FakeFrappeClient) -> None:
        add_accounts(fake_api)
        gl(fake_api, "1576", "2024-02-01", debit=100.0)
        gl(fake_api, "1576", "2024-03-01", credit=40.0)
        gl(fake_api, "1776", "2024-03-01", credit=19.0)
        assert vc.balances(fake_api, COMPANY, {"1576": NAMES["1576"], "1776": NAMES["1776"]}) == {"1576": 60.0, "1776": -19.0}


@pytest.fixture
def instance(fake_api: FakeFrappeClient) -> FakeFrappeClient:
    """Input VAT before 2024 and in two quarters of 2024, output VAT in 2024-Q1 and 2026-Q3."""
    add_accounts(fake_api)
    fake_api.add("Company", company_name=COMPANY, default_finance_book=None)
    gl(fake_api, "1576", "2022-08-15", debit=1000.0)         # vor 2024
    gl(fake_api, "1576", "2023-05-15", debit=500.0)          # vor 2024
    gl(fake_api, "1776", "2023-05-20", credit=300.0)         # vor 2024
    gl(fake_api, "1571", "2023-06-30", debit=7.0)            # vor 2024
    gl(fake_api, "1576", "2024-02-01", debit=200.0)          # 2024-Q1
    gl(fake_api, "1776", "2024-03-01", credit=80.0)          # 2024-Q1
    gl(fake_api, "1576", "2024-05-01", debit=50.0)           # 2024-Q2
    gl(fake_api, "1576", "2026-08-01", debit=999.0)          # laufendes Quartal
    return fake_api


class TestComputeTransfers:
    def test_buckets(self, instance: FakeFrappeClient) -> None:
        accounts = vc.resolve_accounts(instance, COMPANY)
        transfers, open_after = vc.compute_transfers(instance, COMPANY, accounts, "2026-Q2")
        by_period = {t.period: t for t in transfers}
        assert by_period[vc.PRE_PERIOD].amounts["1576"] == 1500.0
        assert by_period[vc.PRE_PERIOD].amounts["1776"] == -300.0
        assert by_period[vc.PRE_PERIOD].amounts["1571"] == 7.0
        assert by_period[vc.PRE_PERIOD].net == 1207.0
        assert by_period["2024-Q1"].amounts["1576"] == 200.0 and by_period["2024-Q1"].amounts["1776"] == -80.0
        assert by_period["2024-Q1"].net == 120.0
        assert by_period["2024-Q2"].net == 50.0
        assert by_period["2024-Q3"].empty() and by_period["2025-Q1"].empty()
        assert open_after == 999.0                                    # 2026-Q3 is still running
        assert [t.period for t in transfers][:2] == [vc.PRE_PERIOD, "2024-Q1"]

    def test_until_includes_further_quarters(self, instance: FakeFrappeClient) -> None:
        accounts = vc.resolve_accounts(instance, COMPANY)
        transfers, open_after = vc.compute_transfers(instance, COMPANY, accounts, "2026-Q3")
        assert open_after == 0.0
        assert {t.period for t in transfers if not t.empty()} == {vc.PRE_PERIOD, "2024-Q1", "2024-Q2", "2026-Q3"}

    def test_already_booked_period_is_skipped(self, instance: FakeFrappeClient) -> None:
        instance.add("Journal Entry", name="ACC-JV-0001", company=COMPANY, title="USt-Umbuchung 2024-Q1", docstatus=1)
        gl(instance, "1576", "2024-03-31", credit=200.0, voucher_no="ACC-JV-0001")
        gl(instance, "1776", "2024-03-31", debit=80.0, voucher_no="ACC-JV-0001")
        accounts = vc.resolve_accounts(instance, COMPANY)
        transfers, _ = vc.compute_transfers(instance, COMPANY, accounts, "2026-Q2")
        q1 = next(t for t in transfers if t.period == "2024-Q1")
        assert q1.existing == "ACC-JV-0001"
        assert q1.amounts["1576"] == 200.0 and q1.amounts["1776"] == -80.0     # own entry not deducted
        # a cancelled entry does not count as booked
        instance.docs("Journal Entry")["ACC-JV-0001"]["docstatus"] = 2
        transfers, _ = vc.compute_transfers(instance, COMPANY, accounts, "2026-Q2")
        assert next(t for t in transfers if t.period == "2024-Q1").existing is None

    def test_own_pre_entry_is_excluded_from_the_quarter(self, instance: FakeFrappeClient) -> None:
        """The catch-up entry is dated 2024-01-01 and must not distort 2024-Q1."""
        instance.add("Journal Entry", name="ACC-JV-0002", company=COMPANY, title=vc.TITLE_PRE, docstatus=1)
        gl(instance, "1576", "2024-01-01", credit=1500.0, voucher_no="ACC-JV-0002")
        gl(instance, "1571", "2024-01-01", credit=7.0, voucher_no="ACC-JV-0002")
        gl(instance, "1776", "2024-01-01", debit=300.0, voucher_no="ACC-JV-0002")
        accounts = vc.resolve_accounts(instance, COMPANY)
        transfers, _ = vc.compute_transfers(instance, COMPANY, accounts, "2026-Q2")
        by_period = {t.period: t for t in transfers}
        assert by_period[vc.PRE_PERIOD].existing == "ACC-JV-0002"
        assert by_period["2024-Q1"].net == 120.0 and by_period["2024-Q1"].existing is None

    def test_without_vat_accounts(self, fake_api: FakeFrappeClient) -> None:
        add_accounts(fake_api, numbers=("1780", "1791"))
        assert vc.compute_transfers(fake_api, COMPANY, vc.resolve_accounts(fake_api, COMPANY), "2026-Q2") == ([], 0.0)


class TestJournalEntry:
    def test_directions_and_balance(self, instance: FakeFrappeClient) -> None:
        accounts = vc.resolve_accounts(instance, COMPANY)
        transfers, _ = vc.compute_transfers(instance, COMPANY, accounts, "2026-Q2")
        pre = next(t for t in transfers if t.period == vc.PRE_PERIOD)
        doc = vc.journal_entry_doc(COMPANY, pre, accounts)
        assert doc["title"] == vc.TITLE_PRE and doc["posting_date"] == "2024-01-01" and doc["set_posting_time"] == 1
        by_account = {l["account"]: l for l in doc["accounts"]}
        assert by_account[NAMES["1576"]]["credit"] == 1500.0          # debit balance is cleared by a credit
        assert by_account[NAMES["1571"]]["credit"] == 7.0
        assert by_account[NAMES["1776"]]["debit"] == 300.0            # credit balance by a debit
        assert by_account[NAMES["1791"]]["debit"] == 1207.0           # offset for the years before
        assert NAMES["1780"] not in by_account and NAMES["1787"] not in by_account
        assert sum(l["debit"] for l in doc["accounts"]) == sum(l["credit"] for l in doc["accounts"])
        assert "Steuerbüro" in doc["user_remark"]

    def test_quarter_uses_1780(self, instance: FakeFrappeClient) -> None:
        accounts = vc.resolve_accounts(instance, COMPANY)
        transfers, _ = vc.compute_transfers(instance, COMPANY, accounts, "2026-Q2")
        q1 = next(t for t in transfers if t.period == "2024-Q1")
        doc = vc.journal_entry_doc(COMPANY, q1, accounts, finance_book="Standard")
        by_account = {l["account"]: l for l in doc["accounts"]}
        assert doc["posting_date"] == "2024-03-31" and doc["finance_book"] == "Standard"
        assert by_account[NAMES["1780"]]["debit"] == 120.0
        assert "Steuerbüro" not in doc["user_remark"]

    def test_balanced_period_has_no_offset_line(self, fake_api: FakeFrappeClient) -> None:
        add_accounts(fake_api)
        gl(fake_api, "1576", "2024-02-01", debit=100.0)
        gl(fake_api, "1776", "2024-02-01", credit=100.0)
        accounts = vc.resolve_accounts(fake_api, COMPANY)
        transfers, _ = vc.compute_transfers(fake_api, COMPANY, accounts, "2024-Q1")
        doc = vc.journal_entry_doc(COMPANY, next(t for t in transfers if t.period == "2024-Q1"), accounts)
        assert len(doc["accounts"]) == 2 and NAMES["1780"] not in {l["account"] for l in doc["accounts"]}

    def test_fake_accepts_the_entry(self, instance: FakeFrappeClient) -> None:
        accounts = vc.resolve_accounts(instance, COMPANY)
        transfers, _ = vc.compute_transfers(instance, COMPANY, accounts, "2026-Q2")
        pre = next(t for t in transfers if t.period == vc.PRE_PERIOD)
        je = instance.insert(vc.journal_entry_doc(COMPANY, pre, accounts))
        assert je["total_debit"] == je["total_credit"] == 1507.0     # 1500 + 7 credit, 300 + 1207 debit


class TestProcess:
    def test_dry_run_changes_nothing(self, instance: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        assert vc.process(instance, COMPANY, "2026-Q2", apply=False, submit=False) == (0, 0)
        assert instance.get_list("Journal Entry") == []
        out = capsys.readouterr().out
        assert "3 von 11 Perioden offen" in out and "3 Buchungssätze würden angelegt" in out
        assert "999.00 liegen in noch nicht abgeschlossenen Quartalen" in out

    def test_apply_books_and_is_idempotent(self, instance: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        assert vc.process(instance, COMPANY, "2026-Q2", apply=True, submit=True) == (3, 0)
        jes = instance.get_list("Journal Entry", fields=["title", "posting_date", "docstatus", "total_debit"])
        assert sorted(j["title"] for j in jes) == ["USt-Nachholung Vorjahre bis 2023", "USt-Umbuchung 2024-Q1",
                                                   "USt-Umbuchung 2024-Q2"]
        assert all(j["docstatus"] == 1 for j in jes)
        by_title = {j["title"]: j for j in jes}
        assert by_title["USt-Umbuchung 2024-Q1"]["posting_date"] == "2024-03-31"
        assert by_title["USt-Umbuchung 2024-Q2"]["posting_date"] == "2024-06-30"
        assert by_title[vc.TITLE_PRE]["posting_date"] == "2024-01-01" and by_title[vc.TITLE_PRE]["total_debit"] == 1507.0
        # the fake writes no GL entries, so the balances it reports do not change here; against a
        # real instance process() re-reads them and warns about a VAT account left over
        assert "Salden nachher" in capsys.readouterr().out
        assert vc.process(instance, COMPANY, "2026-Q2", apply=True, submit=True) == (0, 0)
        assert len(instance.get_list("Journal Entry")) == 3

    def test_apply_creates_drafts_by_default(self, instance: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        assert vc.process(instance, COMPANY, "2024-Q1", apply=True, submit=False) == (2, 0)
        assert all(j["docstatus"] == 0 for j in instance.get_list("Journal Entry", fields=["docstatus"]))
        assert "als Entwurf angelegt" in capsys.readouterr().out

    def test_missing_offset_account(self, fake_api: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        add_accounts(fake_api, numbers=("1576", "1780"))
        assert vc.process(fake_api, COMPANY, "2024-Q1", apply=True, submit=False) == (0, 1)
        assert "Konten 1791 fehlen" in capsys.readouterr().out

    def test_booking_error_is_reported(self, instance: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
        def fail(doc: dict[str, Any]) -> None:
            raise FrappeException("FrappeClient Request Failed\n\nBooks have been closed")
        monkeypatch.setattr(instance, "insert", fail)
        assert vc.process(instance, COMPANY, "2026-Q2", apply=True, submit=False) == (0, 3)
        assert "FEHLER" in capsys.readouterr().out


class TestMain:
    def test_dry_run_over_all_companies(self, instance: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                                        capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(vc, "FrappeClient", lambda url, api_key=None, api_secret=None: instance)
        assert vc.main(["--server", "https://srv", "--key", "k", "--secret", "s", "--until", "2026-Q2"]) == 0
        out = capsys.readouterr().out
        assert "Quartale 2024-Q1 bis 2026-Q2" in out and COMPANY in out
        assert instance.get_list("Journal Entry") == []

    def test_apply_for_one_company(self, instance: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                                   capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(vc, "FrappeClient", lambda url, api_key=None, api_secret=None: instance)
        assert vc.main(["--server", "s", "--key", "k", "--secret", "s", "--company", COMPANY,
                        "--until", "2026-Q2", "--apply", "--submit"]) == 0
        assert len(instance.get_list("Journal Entry")) == 3
        assert "3 Buchungssätze gebucht" in capsys.readouterr().out

    def test_bad_until(self, instance: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                       capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(vc, "FrappeClient", lambda url, api_key=None, api_secret=None: instance)
        assert vc.main(["--server", "s", "--key", "k", "--secret", "s", "--until", "2026/2"]) == 2
        assert "2026-Q2" in capsys.readouterr().out

    def test_companies_with_vat(self, instance: FakeFrappeClient) -> None:
        instance.add("Company", company_name="Ohne Steuer")
        assert vc.companies_with_vat(instance) == [COMPANY]
