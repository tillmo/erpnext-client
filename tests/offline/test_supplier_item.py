"""Tests für supplier_item.SupplierItem: Artikelzuordnung, Preise, Aggregat-Umrechnung."""
from collections import defaultdict

import pytest

from support import factories as F
from support.deps import skip_module_without_pdftotext
from support.stubs import GuiCalled

skip_module_without_pdftotext()

import settings  # noqa: E402
from api import Api  # noqa: E402
from supplier_item import SupplierItem  # noqa: E402

MODUL = {"name": "010.100.001", "item_code": "010.100.001", "item_name": "Solarmodul 400 Wp", "item_group": "Solarmodul",
         "description": "Solarmodul 400 Wp schwarz", "supplier_items": [],
         "expense_account": "4996 - Herstellungskosten - SoMiKo"}
SCHIENE = {"name": "020.200.002", "item_code": "020.200.002", "item_name": "Montageschiene", "item_group": "Montagematerial",
           "description": "Schiene", "supplier_items": []}
ELEKTRO = {"name": "030.300.003", "item_code": "030.300.003", "item_name": "Kabel", "item_group": "Elektro-Komponenten",
           "description": "Kabel", "supplier_items": []}
GENERISCH = {"name": "026.000.315", "item_code": "026.000.315", "item_name": "Generisches Einkaufsprodukt",
             "item_group": "Produkte", "description": "x", "supplier_items": []}
SUPPLIER = "Krannich Solar GmbH & Co KG"


@pytest.fixture
def catalogue(somiko, fake_api):
    Api.items_by_code = {i["item_code"]: dict(i) for i in (MODUL, SCHIENE, ELEKTRO, GENERISCH)}
    Api.item_code_translation = defaultdict(dict, {SUPPLIER: {"KS-400": "010.100.001"}})
    for i in (MODUL, SCHIENE, ELEKTRO, GENERISCH):
        fake_api.add("Item", **{k: v for k, v in i.items() if k != "expense_account"})
    for g in ("Solarmodul", "Wechselrichter", "Produkte", "Montagematerial"):
        fake_api.add("Item Group", item_group_name=g)
    return fake_api


@pytest.fixture
def s_item(somiko, catalogue):
    pinv = F.make_purchase_invoice(somiko, True)
    item = SupplierItem(pinv)
    item.description = "Solarmodul 400"
    item.long_description = "Solarmodul 400 Wp schwarz, Glas-Glas"
    item.qty, item.qty_unit, item.rate, item.amount = 2, "Stk", 150.0, 300.0
    return item


class TestSearchItem:
    def test_translation_table_hit(self, s_item, catalogue, gui):
        s_item.item_code = "KS-400"
        assert s_item.search_item(SUPPLIER)["item_code"] == "010.100.001"
        assert gui.calls == [] and catalogue.calls == []

    def test_choice_from_similar_items(self, s_item, catalogue, gui):
        gui.answers["choicebox"] = lambda msg, title, texts: [t for t in texts if t.startswith("010.100.001")][0]
        e_item = s_item.search_item(SUPPLIER)
        assert e_item["item_code"] == "010.100.001"
        texts = gui.calls[0][1][2]
        assert texts[0] == "Neuen Artikel anlegen"
        assert texts[1] == "026.000.315 Generisches Einkaufsprodukt"   # DEFAULT_ITEMS immer ganz oben
        assert texts[2] == "010.100.001 Solarmodul 400 Wp"
        assert "Solarmodul 400 Wp schwarz, Glas-Glas" in gui.calls[0][1][0]

    def test_choice_with_supplier_code_learns_translation(self, s_item, catalogue, gui):
        s_item.item_code = "KS-NEU"
        gui.answers["choicebox"] = "010.100.001 Solarmodul 400 Wp"
        s_item.search_item(SUPPLIER)
        assert Api.item_code_translation[SUPPLIER]["KS-NEU"] == "010.100.001"
        stored = catalogue.get_doc("Item", "010.100.001")
        assert stored["supplier_items"][-1]["supplier"] == SUPPLIER
        assert stored["supplier_items"][-1]["supplier_part_no"] == "KS-NEU"

    def test_cancel(self, s_item, catalogue, gui):
        gui.answers["choicebox"] = None
        assert s_item.search_item(SUPPLIER) is None

    def test_new_item_via_gui(self, s_item, catalogue, gui):
        answers = iter(["Neuen Artikel anlegen", "Wechselrichter", "Ja"])
        gui.answers["choicebox"] = lambda msg, title, texts: next(answers)
        s_item.item_code = "KS-777"
        e_item = s_item.search_item(SUPPLIER)
        assert e_item["name"].startswith("new") and len(e_item["name"]) == 11
        assert e_item["item_group"] == "Wechselrichter"
        assert e_item["item_name"] == "Solarmodul 400"
        assert e_item["description"] == "Solarmodul 400 Wp schwarz, Glas-Glas"
        assert e_item["stock_uom"] == "Stk"
        assert e_item["item_defaults"][0]["company"] == s_item.purchase_invoice.company_name
        assert e_item["item_defaults"][0]["default_warehouse"] == settings.WAREHOUSE
        assert e_item["supplier_items"][0] == {"supplier": SUPPLIER, "supplier_part_no": "KS-777",
                                               "idx": 1, "parent": e_item["name"], "parenttype": "Item",
                                               "parentfield": "supplier_items"}
        assert Api.item_code_translation[SUPPLIER]["KS-777"] == e_item["name"]
        # Artikelgruppen werden sortiert angeboten
        assert gui.calls[1][1][2] == ["Montagematerial", "Produkte", "Solarmodul", "Wechselrichter"]
        assert "Einzelpreis: 150.00€" in gui.calls[1][1][0]

    def test_new_item_declined(self, s_item, catalogue, gui):
        answers = iter(["Neuen Artikel anlegen", "Wechselrichter", "Nein"])
        gui.answers["choicebox"] = lambda msg, title, texts: next(answers)
        assert s_item.search_item(SUPPLIER) is None
        assert catalogue.calls_of("insert") == []

    def test_new_item_group_cancelled(self, s_item, catalogue, gui):
        answers = iter(["Neuen Artikel anlegen", None])
        gui.answers["choicebox"] = lambda msg, title, texts: next(answers)
        assert s_item.search_item(SUPPLIER) is None

    def test_new_item_without_dialogs(self, s_item, catalogue, gui):
        e_item = s_item.search_item(SUPPLIER, check_dup=False)
        assert e_item["item_group"] == settings.STANDARD_ITEM_GROUP
        assert gui.calls == []

    def test_unanswered_dialog_detected(self, s_item, catalogue):
        with pytest.raises(GuiCalled):
            s_item.search_item(SUPPLIER)


class TestAddItemPrice:
    def test_creates_price(self, s_item, catalogue):
        s_item.add_item_price(MODUL, 150.0, "Stk", "2026-01-01")
        prices = catalogue.get_list("Item Price", fields=["*"])
        assert len(prices) == 1
        p = prices[0]
        assert p["item_code"] == "010.100.001" and p["price_list_rate"] == 150.0
        assert p["selling"] is True and p["buying"] is True
        assert p["price_list"] == settings.STANDARD_PRICE_LIST and p["valid_from"] == "2026-01-01" and p["uom"] == "Stk"

    def test_same_price_untouched(self, s_item, catalogue, gui):
        catalogue.add("Item Price", item_code="010.100.001", price_list_rate=150.0)
        s_item.add_item_price(MODUL, 150.0, "Stk", "2026-01-01")
        assert catalogue.calls_of("update") == [] and gui.calls == []

    def test_changed_price_asks(self, s_item, catalogue, gui):
        name = catalogue.add("Item Price", item_code="010.100.001", price_list_rate=140.0)
        gui.answers["ccbox"] = True
        s_item.add_item_price(MODUL, 150.0, "Stk", "2026-01-01")
        assert catalogue.get_doc("Item Price", name)["price_list_rate"] == 150.0
        assert "Alter Preis: 140.0" in gui.calls[0][1][0]
        gui.answers["ccbox"] = False
        s_item.add_item_price(MODUL, 160.0, "Stk", "2026-01-01")
        assert catalogue.get_doc("Item Price", name)["price_list_rate"] == 150.0


class TestProcessItem:
    def test_stock_item(self, s_item, catalogue):
        s_item.item_code = "KS-400"
        result = s_item.process_item(SUPPLIER, "2026-01-01")
        assert result == {"item_code": "010.100.001", "qty": 2, "rate": 150.0, "desc": "Solarmodul 400",
                          "expense_account": "4996 - Herstellungskosten - SoMiKo"}
        assert len(catalogue.get_list("Item Price")) == 1

    def test_non_stock_item_becomes_aggregate(self, s_item, catalogue, gui):
        s_item.description = "Montageschiene"
        s_item.qty, s_item.rate = 4, 25.0
        gui.answers["choicebox"] = "020.200.002 Montageschiene"
        result = s_item.process_item(SUPPLIER, "2026-01-01")
        assert result == {"item_code": settings.AGGREGATE_ITEMS["default"], "qty": 1.0,
                          "rate": settings.AGGREGATE_ITEM_VALUE, "desc": "Montageschiene"}
        assert catalogue.get_list("Item Price") == []

    def test_elektro_group_aggregate(self, s_item, catalogue, gui):
        s_item.qty, s_item.rate = 10, 5.0
        gui.answers["choicebox"] = "030.300.003 Kabel"
        result = s_item.process_item(SUPPLIER, "2026-01-01")
        assert result["item_code"] == settings.AGGREGATE_ITEMS["Elektro-Komponenten"]
        assert result["qty"] == 0.5 and result["rate"] == 100.0

    def test_no_item_found(self, s_item, catalogue, gui):
        gui.answers["choicebox"] = None
        assert s_item.process_item(SUPPLIER, "2026-01-01") is None
