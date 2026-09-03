"""Passen die in settings.py hinterlegten Stammdaten (Konten, Lager, Artikel, Gruppen) zur Instanz?"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest

import settings
from api import LIMIT
from support.live import LiveState

ABBR = {"Bremer SolidarStrom": "SoMiKo", "Laden": "Laden"}


def accounts_for_company(company: str) -> set[str]:
    accs = set()
    tax = settings.TAX_ACCOUNTS.get(company, {})
    if tax.get("tax_pay_account"):
        accs.add(tax["tax_pay_account"])
    accs.update(tax.get("pre_tax_accounts", []))
    accs.update(tax.get("tax_accounts", []))
    for d in (settings.PAYABLE_ACCOUNTS, settings.RECEIVABLE_ACCOUNTS):
        accs.update(d.get(company, {}).values())
    for lst in settings.INCOME_ACCOUNTS.get(company, {}).values():
        accs.update(lst)
    dist = settings.INCOME_DIST_ACCOUNTS.get(company)
    if dist:
        for group in dist["income"]:
            accs.update(group.values())
        accs.update(dist["expense"].values())
        accs.update(dist["tax"].values())
    for title, (lst, factor) in settings.BALANCE_ACCOUNTS.get(company, {}).items():
        accs.update(lst)
    if company == "Bremer SolidarStrom":
        accs.update(settings.SOMIKO_ACCOUNTS.values())
        accs.update([settings.DELIVERY_COST_ACCOUNT, settings.EBAY_ACCOUNT, settings.SOMIKO_STOCK_ACCOUNT])
    if company == "Laden":
        accs.update(settings.NKK_ACCOUNTS.values())
        accs.update(settings.KORNKRAFT_ACCOUNTS.values())
    return accs


def existing(api: Any, doctype: str, names: Iterable[str]) -> set[str]:
    return {r["name"] for r in api.get_list(doctype, filters={"name": ["in", sorted(names)]}, limit_page_length=LIMIT)}


@pytest.mark.parametrize("company", sorted(set(settings.TAX_ACCOUNTS) | set(settings.INCOME_DIST_ACCOUNTS)))
def test_accounts_exist(api: Any, live: LiveState, company: str) -> None:
    if company not in live.companies:
        pytest.skip("Firma {} gibt es auf der Instanz nicht".format(company))
    wanted = accounts_for_company(company)
    if not wanted:
        pytest.skip("keine Konten für {} konfiguriert".format(company))
    server = {r["name"] for r in api.get_list("Account", filters={"company": company}, limit_page_length=LIMIT)}
    missing = sorted(wanted - server)
    assert not missing, "Konten aus settings.py fehlen für {}: {}".format(company, missing)


def test_purchase_tax_templates_match_pre_tax_accounts(live: LiveState) -> None:
    comp = live.company
    tax = settings.TAX_ACCOUNTS.get(comp.name)
    if not tax or not comp.taxes:
        pytest.skip("keine Steuerkonfiguration für {}".format(comp.name))
    assert set(comp.taxes.values()) <= set(tax["pre_tax_accounts"]), \
        "Vorsteuer-Vorlagen der Firma nutzen Konten, die nicht in TAX_ACCOUNTS stehen"


def test_warehouses_exist(api: Any) -> None:
    wanted = {settings.WAREHOUSE, settings.PROJECT_WAREHOUSE}
    missing = wanted - existing(api, "Warehouse", wanted)
    assert not missing, missing


def test_price_list_and_groups_exist(api: Any) -> None:
    assert existing(api, "Price List", {settings.STANDARD_PRICE_LIST}), settings.STANDARD_PRICE_LIST
    assert existing(api, "Supplier Group", {settings.DEFAULT_SUPPLIER_GROUP}), settings.DEFAULT_SUPPLIER_GROUP
    wanted = {settings.STANDARD_ITEM_GROUP, settings.PROJECT_ITEM_GROUP} | set(settings.STOCK_ITEM_GROUPS) | \
        set(settings.BUNDLE_ITEM_GROUPS) | {g for g in settings.AGGREGATE_ITEMS if g != "default"}
    missing = wanted - existing(api, "Item Group", wanted)
    assert not missing, "Artikelgruppen fehlen: {}".format(sorted(missing))


def test_uom_exists(api: Any) -> None:
    assert existing(api, "UOM", {settings.PROJECT_UNIT}), settings.PROJECT_UNIT


def test_items_exist(api: Any) -> None:
    wanted = {settings.DEFAULT_ITEM_CODE, settings.PLANNING_ITEM} | set(settings.DEFAULT_ITEMS) | \
        set(settings.AGGREGATE_ITEMS.values())
    missing = wanted - existing(api, "Item", wanted)
    assert not missing, "Artikel fehlen: {}".format(sorted(missing))


def test_project_types_exist(api: Any) -> None:
    wanted = set(settings.STOCK_PROJECT_TYPES) | set(settings.LUMP_SUM_STOCK_PROJECT_TYPES)
    missing = wanted - existing(api, "Project Type", wanted)
    assert not missing, "Projekttypen fehlen: {}".format(sorted(missing))


def test_lead_owners_are_users(api: Any) -> None:
    users = {u["first_name"] for u in api.get_list("User", fields=["first_name"], limit_page_length=LIMIT)}
    missing = [lo for lo in settings.LEAD_OWNERS if lo not in users]
    assert not missing, "LEAD_OWNERS ohne Benutzer: {}".format(missing)


def test_naming_series_exists(api: Any, live: LiveState) -> None:
    rows = api.get_list("Purchase Invoice", filters={"company": live.company_name}, fields=["naming_series"],
                        limit_page_length=1, order_by="creation desc")
    if not rows:
        pytest.skip("keine Einkaufsrechnung")
    assert rows[0]["naming_series"] == settings.STANDARD_NAMING_SERIES_PINV
