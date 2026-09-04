"""Tests für api.Api (Initialisierung, Artikel-/Kontencache, Lieferant anlegen)."""
from __future__ import annotations

from typing import Any, NoReturn

import pytest

import api
from api import Api
from settings import WAREHOUSE, DEFAULT_SUPPLIER_GROUP
from support.fakes import FakeFrappeClient
from support.stubs import UserSettings


class TestInitialize:
    def test_initialize_uses_settings_and_returns_companies(self, monkeypatch: pytest.MonkeyPatch,
                                                            user_settings: UserSettings) -> None:
        created = {}

        def factory(url: str, api_key: str | None = None, api_secret: str | None = None) -> FakeFrappeClient:
            c = FakeFrappeClient(url, api_key, api_secret)
            c.add("Company", name="Firma A")
            created["client"] = c
            return c
        monkeypatch.setattr(api, "FrappeClient", factory)
        user_settings["-server-"] = "https://srv"
        user_settings["-key-"] = "k"
        user_settings["-secret-"] = "s"
        assert Api.initialize() == [{"name": "Firma A"}]
        assert Api.api is created["client"]
        assert (Api.api.url, Api.api.api_key, Api.api.api_secret) == ("https://srv", "k", "s")

    def test_initialize_with_settings_sets_setup_flag(self, monkeypatch: pytest.MonkeyPatch, user_settings: UserSettings) -> None:
        import PySimpleGUI as sg
        monkeypatch.setattr(api, "FrappeClient", lambda *a, **k: FakeFrappeClient())
        Api.initialize_with_settings()
        assert sg.UserSettings.filename == "erpnext.json"
        assert user_settings["-setup-"] is False

    def test_initialize_with_settings_marks_setup_needed_on_failure(self, monkeypatch: pytest.MonkeyPatch,
                                                                    user_settings: UserSettings) -> None:
        def broken(*a: Any, **k: Any) -> NoReturn:
            raise ConnectionError("kein Server")
        monkeypatch.setattr(api, "FrappeClient", broken)
        Api.initialize_with_settings()
        assert user_settings["-setup-"] is True


@pytest.fixture
def items(fake_api: FakeFrappeClient, user_settings: UserSettings) -> FakeFrappeClient:
    user_settings["-company-"] = "Bremer SolidarStrom"
    fake_api.add("Item", item_code="010.100.001", item_name="Modul 400", item_group="Solarmodul",
                 description="Solarmodul 400 Wp",
                 supplier_items=[{"supplier": "Krannich Solar GmbH & Co KG", "supplier_part_no": "KS-400"},
                                 {"supplier": "pvXchange Trading GmbH", "supplier_part_no": None}],
                 item_defaults=[{"company": "Bremer SolidarStrom", "expense_account": "4996 - Herstellungskosten - SoMiKo",
                                 "default_warehouse": WAREHOUSE}])
    fake_api.add("Item", item_code="020.200.002", item_name="Kabel", item_group="Zubehör", description="Kabel",
                 supplier_items=[], item_defaults=[])
    fake_api.add("Item", item_code="030.300.003", item_name="Fremd", item_group="Zubehör", description="x",
                 supplier_items=[], item_defaults=[{"company": "Laden", "expense_account": "3400 - Wareneingang"}])
    fake_api.add("Item", item_code="099.999.999", item_name="Alt", item_group="Zubehör", description="alt",
                 disabled=1, supplier_items=[], item_defaults=[])
    return fake_api


class TestLoadItemData:
    def test_translation_table_is_a_dict_before_loading(self) -> None:
        assert isinstance(Api.item_code_translation, dict)
        assert Api.item_code_translation["unbekannt"] == {}

    def test_items_by_code_and_translation(self, items: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        Api.load_item_data()
        assert set(Api.items_by_code) == {"010.100.001", "020.200.002", "030.300.003"}
        item = Api.items_by_code["010.100.001"]
        assert item["supplier_items"] == [{"supplier": "Krannich Solar GmbH & Co KG", "supplier_part_no": "KS-400"}]
        assert Api.item_code_translation["Krannich Solar GmbH & Co KG"]["KS-400"] == "010.100.001"
        assert Api.item_code_translation["unbekannt"] == {}
        assert item["expense_account"] == "4996 - Herstellungskosten - SoMiKo"
        # Standardkonto einer anderen Firma wird nicht übernommen
        assert "expense_account" not in Api.items_by_code["030.300.003"]
        assert "Lese alle 3 ERPNext-Artikel ein" in capsys.readouterr().out

    def test_missing_item_defaults_are_created(self, items: FakeFrappeClient) -> None:
        Api.load_item_data()
        updates = [c[1][0] for c in items.calls_of("update")]
        assert [u["name"] for u in updates] == ["020.200.002"]
        assert updates[0]["item_defaults"] == [{"company": "Bremer SolidarStrom", "default_warehouse": WAREHOUSE}]
        # Artikel mit Defaults nur für eine andere Firma bleibt unverändert (item_defaults nicht leer)
        assert items.get_doc("Item", "030.300.003")["item_defaults"][0]["company"] == "Laden"

    def test_second_call_is_cached(self, items: FakeFrappeClient) -> None:
        Api.load_item_data()
        n = len(items.calls)
        Api.load_item_data()
        assert len(items.calls) == n


class TestLoadAccountData:
    def test_groups_by_company(self, fake_api: FakeFrappeClient) -> None:
        fake_api.add("Account", name="Bank - A", account_name="Bank", company="A", is_group=0, root_type="Asset")
        fake_api.add("Account", name="Bank - B", account_name="Bank", company="B", is_group=0, root_type="Asset")
        fake_api.add("Account", name="Aufwand - A", account_name="Aufwand", company="A", is_group=1, root_type="Expense")
        Api.load_account_data()
        assert set(Api.accounts_by_company) == {"A", "B"}
        assert sorted(a["name"] for a in Api.accounts_by_company["A"]) == ["Aufwand - A", "Bank - A"]
        assert Api.accounts_by_company["A"][0].keys() >= {"name", "account_name", "company", "is_group", "root_type"}

    def test_cached(self, fake_api: FakeFrappeClient) -> None:
        fake_api.add("Account", name="Bank - A", account_name="Bank", company="A", is_group=0, root_type="Asset")
        Api.load_account_data()
        fake_api.add("Account", name="Bank - C", account_name="Bank", company="C", is_group=0, root_type="Asset")
        Api.load_account_data()
        assert "C" not in Api.accounts_by_company


class TestSubmitAndSupplier:
    def test_submit_doc(self, fake_api: FakeFrappeClient) -> None:
        name = fake_api.add("Journal Entry", accounts=[], total_debit=0)
        Api.submit_doc("Journal Entry", name)
        assert fake_api.get_doc("Journal Entry", name)["docstatus"] == 1

    def test_create_supplier_inserts_once(self, fake_api: FakeFrappeClient) -> None:
        Api.create_supplier("Neuer Lieferant")
        Api.create_supplier("Neuer Lieferant")
        assert fake_api.get_list("Supplier") == [{"name": "Neuer Lieferant"}]
        doc = fake_api.get_doc("Supplier", "Neuer Lieferant")
        assert doc["supplier_group"] == DEFAULT_SUPPLIER_GROUP
        assert len(fake_api.calls_of("insert")) == 1


class TestFindSupplier:
    @pytest.fixture
    def suppliers(self, fake_api: FakeFrappeClient) -> FakeFrappeClient:
        fake_api.add("Supplier", supplier_name="Krannich Solar GmbH & Co KG", tax_id=None)
        fake_api.add("Supplier", supplier_name="Memodo GmbH", tax_id="DE 318463541")
        fake_api.add("Supplier", supplier_name="Wagner Solar", tax_id=None)
        Api.suppliers_cache = None
        return fake_api

    def test_exact_and_normalised_names(self, suppliers: FakeFrappeClient) -> None:
        assert Api.find_supplier("Memodo GmbH") == "Memodo GmbH"
        assert Api.find_supplier("Krannich Solar GmbH & Co. KG") == "Krannich Solar GmbH & Co KG"     # punctuation
        assert Api.find_supplier("KRANNICH SOLAR GMBH UND CO KG") == "Krannich Solar GmbH & Co KG"
        assert Api.find_supplier("Wagner Solar GmbH") == "Wagner Solar"                               # legal form ignored
        assert Api.find_supplier("Unbekannte Firma AG") is None
        assert Api.find_supplier(None) is None and Api.find_supplier("") is None

    def test_names_with_address_or_legal_form(self, fake_api: FakeFrappeClient) -> None:
        fake_api.add("Supplier", supplier_name="CarpeDiem Energy, Lägelerstr. 53, 88250 Weingarten")
        fake_api.add("Supplier", supplier_name="eibmarkt.com GmbH - Kemmlerstrasse 1 - 08527 Plauen")
        fake_api.add("Supplier", supplier_name="Hans-Wilken_Löhrmann")
        fake_api.add("Supplier", supplier_name="Solar AG")
        fake_api.add("Supplier", supplier_name="Solar GmbH")
        Api.suppliers_cache = None
        assert Api.find_supplier("CarpeDiem Energy GmbH") == "CarpeDiem Energy, Lägelerstr. 53, 88250 Weingarten"
        assert Api.find_supplier("eibmarkt.com GmbH") == "eibmarkt.com GmbH - Kemmlerstrasse 1 - 08527 Plauen"
        assert Api.find_supplier("Hans-Wilken Löhrmann") == "Hans-Wilken_Löhrmann"
        assert Api.find_supplier("Solar e.V.") is None                # ambiguous core name: no guess
        assert Api.supplier_names()[:2] == ["CarpeDiem Energy, Lägelerstr. 53, 88250 Weingarten",
                                            "Hans-Wilken_Löhrmann"]

    def test_tax_id_wins(self, suppliers: FakeFrappeClient) -> None:
        assert Api.find_supplier("Memodo Solar Shop", "DE318463541") == "Memodo GmbH"
        assert Api.find_supplier(None, "DE000000000") is None

    def test_cache(self, suppliers: FakeFrappeClient) -> None:
        Api.find_supplier("Memodo GmbH")
        Api.find_supplier("Memodo GmbH")
        assert len(suppliers.calls_of("get_list")) == 1
