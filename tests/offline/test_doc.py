"""Tests für doc.Doc (dünne Hülle um get_doc/insert/update/submit)."""
from doc import Doc


class TestInit:
    def test_load_by_name(self, fake_api):
        fake_api.add("Supplier", supplier_name="S", supplier_group="Lieferant")
        d = Doc(name="S", doctype="Supplier")
        assert d.erpnext is True
        assert d.doc["supplier_group"] == "Lieferant"
        assert d.doc["doctype"] == "Supplier"

    def test_missing_document(self, fake_api, capsys):
        d = Doc(name="gibt es nicht", doctype="Supplier")
        assert d.erpnext is False
        assert d.doc is None
        assert "Fehler in Kommunikation" in capsys.readouterr().out

    def test_from_doc_sets_doctype(self, fake_api):
        d = Doc(doc={"name": "X"}, doctype="Supplier")
        assert d.erpnext is True
        assert d.doc["doctype"] == "Supplier"
        assert d.name == "X"

    def test_from_doc_without_name_is_not_in_erpnext(self, fake_api):
        d = Doc(doc={"name": None})
        assert d.erpnext is False


class TestPersistence:
    def test_insert_assigns_name(self, fake_api):
        d = Doc.__new__(Doc)
        d.doc = {"doctype": "Supplier", "supplier_name": "Neu"}
        d.erpnext = False
        res = d.insert()
        assert res["name"] == "Neu"
        assert d.name == "Neu" and d.erpnext is True
        assert fake_api.get_doc("Supplier", "Neu")

    def test_insert_failure_returns_none(self, fake_api, capsys):
        d = Doc.__new__(Doc)
        d.doc = {"supplier_name": "ohne doctype"}
        assert d.insert() is None
        assert "Fehler" in capsys.readouterr().out

    def test_update_and_submit(self, fake_api):
        fake_api.add("Journal Entry", accounts=[{"account": "A", "debit": 1, "credit": 0},
                                                {"account": "B", "debit": 0, "credit": 1}])
        d = Doc(name="ACC-JV-{}-00001".format(fake_api.year), doctype="Journal Entry")
        d.doc["user_remark"] = "geändert"
        d.update()
        assert fake_api.get_doc("Journal Entry", d.name)["user_remark"] == "geändert"
        d.submit()
        assert d.doc["docstatus"] == 1
        assert fake_api.get_doc("Journal Entry", d.name)["docstatus"] == 1
