"""Tests für compute_tests.py (Vergleich Google-JSON <-> Einkaufsrechnung)."""
import json

import pytest

from support import factories as F
from support.deps import skip_module_without_pdftotext, requires_jsondiff

skip_module_without_pdftotext()

import compute_tests  # noqa: E402
from api import Api  # noqa: E402


@pytest.fixture
def items():
    Api.items_by_code = {
        "010.100.001": {"item_code": "010.100.001", "description": "Solarmodul 400 Wp",
                        "supplier_items": [{"supplier": "Krannich", "supplier_part_no": "KS-400"},
                                           {"supplier": "Andere", "supplier_part_no": "X-1"}]},
        "000.000.000": {"item_code": "000.000.000", "description": "Generisches Einkaufsprodukt", "supplier_items": []},
    }


class TestConvert:
    def test_convert_item(self, items):
        assert compute_tests.convert_item(("account_head", "3800 - Bezugsnebenkosten - SoMiKo"), "K") == [("shipping", 1)]
        assert compute_tests.convert_item(("account_head", "1576 - Abziehbare VSt. 19% - SoMiKo"), "K") == [("rate", 19)]
        assert compute_tests.convert_item(("account_head", "4210 - Miete - SoMiKo"), "K") == [("account_head", "4210 - Miete - SoMiKo")]
        assert compute_tests.convert_item(("item_code", "010.100.001"), "Krannich") == \
            [("description", "Solarmodul 400 Wp"), ("item_code", "KS-400")]
        assert compute_tests.convert_item(("item_code", "010.100.001"), "Unbekannt") == [("description", "Solarmodul 400 Wp")]
        assert compute_tests.convert_item(("qty", 2), "K") == [("qty", 2)]

    def test_convert_filters_subfields(self, items):
        d = {"qty": 2, "uom": "Stk", "rate": 0, "amount": 10.0, "name": "row1", "item_code": "010.100.001"}
        assert compute_tests.convert(d, "Krannich") == [("qty", 2), ("uom", "Stk"), ("amount", 10.0),
                                                        ("description", "Solarmodul 400 Wp"), ("item_code", "KS-400")]


class TestValidate:
    def test_validate_json1(self, capsys):
        good = {"supplier": "S", "grand_total": 1.0, "taxes": [{"rate": 19, "tax_amount": 0.16}],
                "items": [{"description": "a", "amount": 1.0}]}
        assert compute_tests.validate_json1(good) is True
        assert compute_tests.validate_json1({"supplier": "S"}) is False
        assert "validation failed" in capsys.readouterr().out
        assert compute_tests.validate_json1({"supplier": "S", "grand_total": 1.0, "taxes": [{"rate": 19.5, "tax_amount": 1}]}) is False

    def test_validate_prerechnungs(self, fake_api, capsys):
        fake_api.add("PreRechnung", name="PreR00001", json1=json.dumps({"supplier": "S", "grand_total": 1.0, "taxes": []}))
        fake_api.add("PreRechnung", name="PreR00002", json1=None)
        assert compute_tests.validate_prerechnungs() is True
        fake_api.add("PreRechnung", name="PreR00003", json1=json.dumps({"supplier": "S"}))
        assert compute_tests.validate_prerechnungs() is False


class TestComputeJson:
    def test_builds_json1_from_purchase_invoice(self, fake_api, items):
        fake_api.add("Purchase Invoice", name="EK 1", supplier="Krannich", posting_date="2026-01-01", bill_no="B",
                     total=100.0, grand_total=119.0, order_id="O",
                     items=[{"item_code": "010.100.001", "qty": 2, "uom": "Stk", "rate": 50.0, "amount": 100.0}],
                     taxes=[{"account_head": "1576 - Abziehbare VSt. 19% - SoMiKo", "tax_amount": 19.0},
                            {"account_head": "3800 - Bezugsnebenkosten - SoMiKo", "tax_amount": 7.5}])
        fake_api.add("PreRechnung", name="PreR00001", purchase_invoice="EK 1")
        pr = fake_api.get_doc("PreRechnung", "PreR00001")
        compute_tests.compute_json(pr)
        json1 = json.loads(fake_api.get_doc("PreRechnung", "PreR00001")["json1"])
        assert json1["supplier"] == "Krannich" and json1["bill_no"] == "B" and json1["order_id"] == "O"
        assert json1["total"] == 100.0 and json1["grand_total"] == 119.0
        assert json1["shipping"] == 7.5
        assert json1["taxes"] == [{"rate": 19, "tax_amount": 19.0}]
        assert json1["items"] == [{"qty": 2, "uom": "Stk", "rate": 50.0, "amount": 100.0,
                                   "description": "Solarmodul 400 Wp", "item_code": "KS-400"}]

    def test_generic_items_are_dropped(self, fake_api, items):
        fake_api.add("Purchase Invoice", name="EK 2", supplier="S", total=1.0, grand_total=1.0,
                     items=[{"item_code": "000.000.000", "qty": 1, "rate": 1.0, "amount": 1.0}], taxes=[])
        fake_api.add("PreRechnung", name="PreR00002", purchase_invoice="EK 2")
        compute_tests.compute_json(fake_api.get_doc("PreRechnung", "PreR00002"))
        json1 = json.loads(fake_api.get_doc("PreRechnung", "PreR00002")["json1"])
        assert "items" not in json1

    def test_invalid_result_is_not_stored(self, fake_api, items):
        fake_api.add("Purchase Invoice", name="EK 3", total=1.0, items=[], taxes=[])   # kein supplier
        fake_api.add("PreRechnung", name="PreR00003", purchase_invoice="EK 3")
        compute_tests.compute_json(fake_api.get_doc("PreRechnung", "PreR00003"))
        assert "json1" not in fake_api.get_doc("PreRechnung", "PreR00003")


@requires_jsondiff
class TestDiffs:
    def test_compute_diff_ignores_excluded_fields(self, fake_api, capsys):
        j1 = {"name": "a", "supplier": "S", "owner": "x", "items": [{"qty": 1, "name": "r1"}], "taxes": []}
        j2 = {"name": "b", "supplier": "S", "owner": "y", "items": [{"qty": 1, "name": "r2"}], "taxes": []}
        fake_api.add("PreRechnung", name="PreR00001", json1=json.dumps(j1), json2=json.dumps(j2))
        compute_tests.compute_diff(fake_api.get_doc("PreRechnung", "PreR00001"))
        assert fake_api.get_doc("PreRechnung", "PreR00001")["diff"] == "None"

    def test_compute_diff_reports_real_difference(self, fake_api, capsys):
        j1 = {"supplier": "S", "items": [{"qty": 1}], "taxes": []}
        j2 = {"supplier": "T", "items": [{"qty": 2}], "taxes": []}
        fake_api.add("PreRechnung", name="PreR00001", json1=json.dumps(j1), json2=json.dumps(j2))
        compute_tests.compute_diff(fake_api.get_doc("PreRechnung", "PreR00001"))
        diff = fake_api.get_doc("PreRechnung", "PreR00001")["diff"]
        assert "supplier" in diff and "qty" in diff
        assert "PreR00001" in capsys.readouterr().out

    def test_compute_json1_diff(self, somiko, fake_api, monkeypatch):
        import purchase_invoice_google_parser as gp
        monkeypatch.setattr(gp, "find_date", lambda s: "2024-03-15")
        j = F.google_invoice_json()
        json1 = {"supplier": "Muster Solartechnik GmbH", "total": 1000.0, "grand_total": 1190.0,
                 "taxes": [{"rate": 19, "tax_amount": 190.0}], "bill_no": "RE2024-77", "order_id": "BEST-1",
                 "posting_date": "2024-03-15"}
        inv = {"lieferant": "Muster Solartechnik GmbH", "json": json.dumps(j), "json1": json.dumps(json1), "chance": None}
        assert compute_tests.compute_json1_diff(inv) == {}
        json1["total"] = 999.0
        inv["json1"] = json.dumps(json1)
        assert "total" in compute_tests.compute_json1_diff(inv)
