"""Konsistenzprüfungen für settings.py (Kontenbezeichnungen, Firmenzuordnung)."""
from __future__ import annotations

import re
from datetime import datetime

import pytest

import settings

ACCOUNT_RE = re.compile(r"^(\d{4} - )?.+ - (SoMiKo|Laden)$")


def all_account_strings() -> list[str]:
    found = []

    def walk(x: object) -> None:
        if isinstance(x, str):
            if " - " in x and x.rsplit(" - ", 1)[1] in ("SoMiKo", "Laden"):
                found.append(x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    for name in dir(settings):
        if name.isupper():
            walk(getattr(settings, name))
    return found


class TestAccounts:
    def test_account_names_have_company_suffix(self) -> None:
        for acc in all_account_strings():
            assert ACCOUNT_RE.match(acc), acc

    def test_company_specific_dicts_use_same_companies(self) -> None:
        companies = set(settings.TAX_ACCOUNTS)
        assert set(settings.INCOME_ACCOUNTS) == companies
        assert set(settings.PAYABLE_ACCOUNTS) <= companies
        assert set(settings.RECEIVABLE_ACCOUNTS) <= companies
        assert set(settings.INCOME_DIST_ACCOUNTS) <= companies
        assert set(settings.BALANCE_ACCOUNTS) <= companies

    def test_accounts_belong_to_their_company_abbreviation(self) -> None:
        abbr = {"Bremer SolidarStrom": "SoMiKo", "Laden": "Laden"}
        for company, accs in settings.TAX_ACCOUNTS.items():
            if company not in abbr:
                continue
            for acc in [accs["tax_pay_account"]] + accs["pre_tax_accounts"] + accs["tax_accounts"]:
                assert acc.endswith(" - " + abbr[company]), acc
        for company, accs in settings.INCOME_ACCOUNTS.items():
            for acc in sum(accs.values(), []):
                assert acc.endswith(" - " + abbr[company]), acc

    def test_income_distribution_tax_accounts_match_tax_accounts(self) -> None:
        dist = settings.INCOME_DIST_ACCOUNTS["Laden"]
        assert set(dist["tax"].values()) == set(settings.TAX_ACCOUNTS["Laden"]["tax_accounts"])
        assert set(dist["expense"]) == set(dist["tax"])
        for group in dist["income"]:
            assert set(group) == {"unclear", 7, 19}

    def test_income_accounts_cover_distribution_targets(self) -> None:
        dist = settings.INCOME_DIST_ACCOUNTS["Laden"]
        for rate in (7, 19):
            targets = {g[rate] for g in dist["income"]}
            assert targets <= set(settings.INCOME_ACCOUNTS["Laden"][rate])

    def test_supplier_account_maps_have_same_rates(self) -> None:
        assert set(settings.NKK_ACCOUNTS) == set(settings.KORNKRAFT_ACCOUNTS) == {19.0, 7.0}
        assert set(settings.SOMIKO_ACCOUNTS) == {19.0}

    def test_stock_pre_accounts_refer_to_somiko_accounts(self) -> None:
        for abbrev in settings.STOCK_PRE_ACCOUNTS:
            assert any(abbrev in acc for acc in settings.SOMIKO_ACCOUNTS.values())

    def test_delivery_cost_account(self) -> None:
        assert settings.DELIVERY_COST_DESCRIPTION in settings.DELIVERY_COST_ACCOUNT

    def test_balance_account_areas(self) -> None:
        for company, areas in settings.BALANCE_ACCOUNTS.items():
            for title, (accounts, factor) in areas.items():
                assert accounts and factor in (1, -1), title


class TestItemsAndMisc:
    def test_item_codes_format(self) -> None:
        code_re = re.compile(r"^\d{3}\.\d{3}\.\d{3}$")
        for code in [settings.DEFAULT_ITEM_CODE, settings.PLANNING_ITEM] + settings.DEFAULT_ITEMS + \
                list(settings.AGGREGATE_ITEMS.values()):
            assert code_re.match(code), code

    def test_aggregate_items_have_default(self) -> None:
        assert "default" in settings.AGGREGATE_ITEMS
        assert settings.AGGREGATE_ITEM_VALUE > 0

    def test_dates(self) -> None:
        datetime.strptime(settings.VALIDITY_DATE, "%Y-%m-%d")

    def test_naming_series(self) -> None:
        assert settings.STANDARD_NAMING_SERIES_PINV.endswith("-")
        assert ".YYYY." in settings.STANDARD_NAMING_SERIES_PINV

    def test_project_types_disjoint(self) -> None:
        assert not set(settings.STOCK_PROJECT_TYPES) & set(settings.LUMP_SUM_STOCK_PROJECT_TYPES)

    def test_lead_owners_are_first_names(self) -> None:
        assert settings.LEAD_OWNERS and all(" " not in lo for lo in settings.LEAD_OWNERS)
