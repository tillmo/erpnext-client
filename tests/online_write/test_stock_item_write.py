"""Lagerbuchungen, Artikel und Artikelpreise anlegen."""
import pytest

import settings
import stock
from api import Api, LIMIT
from support import factories as F
from support.deps import skip_module_without_pdftotext
from support.live import tag

skip_module_without_pdftotext()

from supplier_item import SupplierItem  # noqa: E402


@pytest.fixture
def stock_item(api):
    rows = api.get_list("Item", filters={"is_stock_item": 1, "disabled": 0}, fields=["name", "stock_uom"],
                        limit_page_length=1)
    if not rows:
        pytest.skip("kein Lagerartikel vorhanden")
    return rows[0]


@pytest.fixture
def warehouse(api, live):
    rows = api.get_list("Warehouse", filters={"name": settings.WAREHOUSE})
    if rows:
        return settings.WAREHOUSE
    rows = api.get_list("Warehouse", filters={"company": live.company_name, "is_group": 0}, limit_page_length=1)
    if not rows:
        pytest.skip("kein Lager für {}".format(live.company_name))
    return rows[0]["name"]


class TestStockEntry:
    def test_material_receipt_draft(self, live, api, cleanup, stock_item, warehouse, today):
        doc = stock.stock_entry_for_item(live.company_name, today, stock_item["name"], warehouse, True, 3,
                                         live.expense_leaf(), project=None)
        assert doc and doc["name"]
        cleanup.add("Stock Entry", doc["name"])
        stored = api.get_doc("Stock Entry", doc["name"])
        assert stored["docstatus"] == 0 and stored["stock_entry_type"] == "Material Receipt"
        assert stored["posting_date"] == today
        item = stored["items"][0]
        assert item["item_code"] == stock_item["name"] and item["t_warehouse"] == warehouse
        assert item["qty"] == pytest.approx(3) and item["basic_rate"] == pytest.approx(1)

    def test_material_issue_draft(self, live, api, cleanup, stock_item, warehouse, today):
        doc = stock.stock_entry_for_item(live.company_name, today, stock_item["name"], warehouse, False, 1,
                                         live.expense_leaf())
        cleanup.add("Stock Entry", doc["name"])
        stored = api.get_doc("Stock Entry", doc["name"])
        assert stored["stock_entry_type"] == "Material Issue"
        assert stored["items"][0]["s_warehouse"] == warehouse


class TestItems:
    def test_new_item_and_price(self, live, api, cleanup, test_supplier):
        pinv = F.make_purchase_invoice(live.company, True)
        Api.items_by_code = {}
        s_item = SupplierItem(pinv)
        s_item.description = "pytest Testartikel " + tag()
        s_item.long_description = "Nur für automatische Tests angelegt"
        s_item.qty, s_item.qty_unit, s_item.rate, s_item.amount = 1, "Stk", 12.5, 12.5
        s_item.item_code = tag("PART")
        e_item = s_item.search_item(test_supplier, check_dup=False)
        assert e_item and e_item["name"].startswith("new")
        cleanup.add("Item", e_item["name"])
        stored = api.get_doc("Item", e_item["name"])
        assert stored["item_group"] == settings.STANDARD_ITEM_GROUP
        assert stored["item_name"] == s_item.description
        assert stored["supplier_items"][0]["supplier"] == test_supplier
        assert stored["supplier_items"][0]["supplier_part_no"] == s_item.item_code
        assert stored["item_defaults"][0]["default_warehouse"] == settings.WAREHOUSE

        s_item.add_item_price(stored, 12.5, "Stk", "2026-01-01")
        prices = api.get_list("Item Price", filters={"item_code": e_item["name"]}, fields=["name", "price_list_rate",
                                                                                          "price_list", "buying", "selling"])
        assert len(prices) == 1
        cleanup.add("Item Price", prices[0]["name"])
        assert prices[0]["price_list_rate"] == pytest.approx(12.5)
        assert prices[0]["price_list"] == settings.STANDARD_PRICE_LIST
        assert prices[0]["buying"] == 1 and prices[0]["selling"] == 1

    def test_load_item_data_completes_item_defaults(self, live, api):
        Api.items_by_code = {}
        Api.item_code_translation = []
        Api.load_item_data()
        assert Api.items_by_code
        rows = api.get_list("Item", filters={"disabled": 0},
                            fields=["name", "`tabItem Default`.company as default_company"], limit_page_length=LIMIT)
        without_defaults = sorted({r["name"] for r in rows if r["default_company"] is None})
        assert not without_defaults, "Artikel ohne item_defaults nach load_item_data: {}".format(without_defaults[:10])
