"""Tests für frappe.py (lokaler Ersatz einiger frappe-Utilities)."""
from __future__ import annotations

import json
from datetime import date

import pytest

import frappe


class TestDict:
    def test_attribute_access(self) -> None:
        d = frappe._dict(name="x")
        assert d.name == "x"
        d.other = 3
        assert d["other"] == 3
        del d.other
        assert "other" not in d

    def test_missing_attribute_is_none(self) -> None:
        assert frappe._dict().nothing is None

    def test_update_returns_self_and_copy_keeps_type(self) -> None:
        d = frappe._dict(a=1)
        assert d.update(b=2) is d
        c = d.copy()
        assert isinstance(c, frappe._dict)
        assert c == {"a": 1, "b": 2}

    def test_pickle_roundtrip(self) -> None:
        import pickle
        d = frappe._dict(a=1)
        assert pickle.loads(pickle.dumps(d)) == {"a": 1}


class TestCstr:
    def test_values(self) -> None:
        assert frappe.cstr(None) == ""
        assert frappe.cstr("ä") == "ä"
        assert frappe.cstr("ä".encode("utf-8")) == "ä"
        assert frappe.cstr(5) == "5"

    def test_as_unicode_encoding(self) -> None:
        assert frappe.as_unicode("Müller".encode("latin-1"), "latin-1") == "Müller"


class TestAsJson:
    def test_sorted_keys_and_indent(self) -> None:
        s = frappe.as_json({"b": 1, "a": [1, 2]})
        assert s == '{\n "a": [\n  1,\n  2\n ],\n "b": 1\n}'
        assert json.loads(s) == {"a": [1, 2], "b": 1}

    def test_custom_separators(self) -> None:
        s = frappe.as_json({"a": 1}, indent=None, separators=(",", ":"))
        assert s == '{"a":1}'

    def test_non_string_keys_are_sorted_by_str(self) -> None:
        s = frappe.as_json({2: "b", 1: "a"})
        assert json.loads(s) == {"1": "a", "2": "b"}

    def test_date_serialisation(self) -> None:
        assert json.loads(frappe.as_json({"d": date(2026, 1, 2)}))["d"] == "2026-01-02"
        import datetime, decimal
        out = json.loads(frappe.as_json({"t": datetime.timedelta(hours=1), "n": decimal.Decimal("1.5"), "s": {1, 2}}))
        assert out == {"t": "1:00:00", "n": 1.5, "s": [1, 2]}
        with pytest.raises(TypeError):
            frappe.as_json({"o": object()})
