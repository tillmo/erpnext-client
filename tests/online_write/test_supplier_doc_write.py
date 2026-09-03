"""Create a supplier (Api.create_supplier) and the Doc wrapper against the instance."""
from __future__ import annotations

from typing import Any

import pytest

import settings
from api import Api
from doc import Doc
from frappeclient import FrappeException
from support.live import Cleanup, tag


class TestCreateSupplier:
    def test_create_supplier_is_idempotent(self, api: Any, cleanup: Cleanup) -> None:
        name = tag("Lieferant")
        cleanup.add("Supplier", name)
        Api.create_supplier(name)
        Api.create_supplier(name)
        rows = api.get_list("Supplier", filters={"name": name})
        assert rows == [{"name": name}]
        doc = api.get_doc("Supplier", name)
        assert doc["supplier_group"] == settings.DEFAULT_SUPPLIER_GROUP
        assert doc["supplier_name"] == name


class TestDoc:
    def test_insert_load_update_delete(self, api: Any, cleanup: Cleanup) -> None:
        name = tag("Lieferant")
        d = Doc.__new__(Doc)
        d.doc = {"doctype": "Supplier", "supplier_name": name, "supplier_group": settings.DEFAULT_SUPPLIER_GROUP}
        d.erpnext = False
        cleanup.add("Supplier", name)
        assert d.insert()["name"] == name
        assert d.erpnext is True and d.name == name

        loaded = Doc(name=name, doctype="Supplier")
        assert loaded.erpnext is True and loaded.doc["supplier_name"] == name

        loaded.doc["supplier_details"] = "pytest"
        loaded.update()
        assert api.get_doc("Supplier", name)["supplier_details"] == "pytest"

        api.delete("Supplier", name)
        with pytest.raises(FrappeException):
            api.get_doc("Supplier", name)

    def test_load_missing(self, api: Any, capsys: pytest.CaptureFixture[str]) -> None:
        d = Doc(name="pytest-gibt-es-nicht", doctype="Supplier")
        assert d.erpnext is False
        assert "Fehler in Kommunikation" in capsys.readouterr().out
