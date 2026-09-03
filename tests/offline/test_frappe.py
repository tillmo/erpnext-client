"""Tests für frappe.py (lokaler Ersatz einiger frappe-Utilities)."""
import json
from datetime import date

import pytest

import frappe


class TestDict:
    def test_attribute_access(self):
        d = frappe._dict(name="x")
        assert d.name == "x"
        d.other = 3
        assert d["other"] == 3
        del d.other
        assert "other" not in d

    def test_missing_attribute_is_none(self):
        assert frappe._dict().nothing is None

    def test_update_returns_self_and_copy_keeps_type(self):
        d = frappe._dict(a=1)
        assert d.update(b=2) is d
        c = d.copy()
        assert isinstance(c, frappe._dict)
        assert c == {"a": 1, "b": 2}

    def test_pickle_roundtrip(self):
        import pickle
        d = frappe._dict(a=1)
        assert pickle.loads(pickle.dumps(d)) == {"a": 1}


class TestCstr:
    def test_values(self):
        assert frappe.cstr(None) == ""
        assert frappe.cstr("ä") == "ä"
        assert frappe.cstr("ä".encode("utf-8")) == "ä"
        assert frappe.cstr(5) == "5"

    def test_as_unicode_encoding(self):
        assert frappe.as_unicode("Müller".encode("latin-1"), "latin-1") == "Müller"


class TestAsJson:
    def test_sorted_keys_and_indent(self):
        s = frappe.as_json({"b": 1, "a": [1, 2]})
        assert s == '{\n "a": [\n  1,\n  2\n ],\n "b": 1\n}'
        assert json.loads(s) == {"a": [1, 2], "b": 1}

    def test_custom_separators(self):
        s = frappe.as_json({"a": 1}, indent=None, separators=(",", ":"))
        assert s == '{"a":1}'

    def test_non_string_keys_are_sorted_by_str(self):
        s = frappe.as_json({2: "b", 1: "a"})
        assert json.loads(s) == {"1": "a", "2": "b"}

    @pytest.mark.xfail(strict=True, raises=NameError,
                       reason="json_handler benutzt datetime/decimal/LocalProxy ohne Import")
    def test_date_serialisation(self):
        assert json.loads(frappe.as_json({"d": date(2026, 1, 2)}))["d"] == "2026-01-02"
