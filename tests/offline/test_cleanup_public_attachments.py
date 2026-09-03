"""Entscheidungslogik von cleanup_public_attachments.Cleaner mit einem aufzeichnenden Stub-Client.

Die Datei-Semantik von Frappe (content_hash, Verschieben beim Umstellen auf privat) wird hier
nur so weit nachgestellt, wie das Skript sie voraussetzt; die echten Effekte wurden auf der
Testinstanz geprüft.
"""
from __future__ import annotations

from typing import Any

import os
import sys

import pytest

# das Skript liegt im privaten Verzeichnis mytools/ (nicht Teil dieses Repos)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "mytools"))
cpa = pytest.importorskip("cleanup_public_attachments", reason="mytools/cleanup_public_attachments.py nicht vorhanden")
from frappeclient import FrappeException  # noqa: E402


class StubApi:
    def __init__(self, field_value: str | None = "/private/files/a.pdf", private_twin: bytes | None = None,
                 file_missing: bool = False) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.field_value = field_value
        self.private_twin = private_twin        # Inhalt einer gleichnamigen privaten Datei (Kollision)
        self.file_missing = file_missing
        self.contents: dict[str, bytes] = {}

    def get_value(self, doctype: str, field: str, filters: dict[str, Any]) -> dict[str, str | None]:
        return {field: self.field_value}

    def set_value(self, doctype: str, name: str, field: str, value: Any) -> None:
        self.calls.append(("set_value", doctype, name, field, value))

    def delete(self, doctype: str, name: str) -> None:
        self.calls.append(("delete", doctype, name))

    def update(self, doc: dict[str, Any]) -> None:
        self.calls.append(("update", doc))
        if doc.get("is_private") == 1:
            if self.file_missing:
                raise FrappeException("FrappeClient Request Failed\n\nFileNotFoundError: Cannot find file")
            if self.private_twin is not None:
                raise FrappeException("FrappeClient Request Failed\n\nFileExistsError: A file with same name exists")

    def get_doc(self, doctype: str, name: str) -> dict[str, Any]:
        return {"name": name, "file_url": "/private/files/moved.pdf", "is_private": 1, "content_hash": "h1"}

    def get_list(self, doctype: str, filters: dict[str, Any] | None = None, fields: list[str] | None = None,
                 limit_page_length: int | None = None) -> list[dict[str, Any]]:
        self.calls.append(("get_list", filters))
        return [{"name": "F3", "file_url": "/private/files/moved.pdf", "is_private": 1, "content_hash": "h1",
                 "file_name": "moved.pdf", "attached_to_field": None}]

    def get_file(self, url: str) -> bytes:
        return self.contents.get(url, b"%PDF " + url.encode())

    def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("insert", doc))
        return {"name": "NEW"}


def f(name: str, url: str, private: int, h: str = "h1", field: str | None = None) -> dict[str, Any]:
    return {"name": name, "file_url": url, "file_name": url.split("/")[-1], "is_private": private,
            "content_hash": h, "attached_to_name": "EK 1", "attached_to_field": field}


def run(api: StubApi, files: list[dict[str, Any]], do_it: bool = True) -> cpa.Cleaner:
    c = cpa.Cleaner(api, do_it)
    c.clean_document("Purchase Invoice", "supplier_invoice", "EK 1", files)
    return c


class TestSameContent:
    def test_public_copies_are_deleted_with_unique_hash(self) -> None:
        api = StubApi()
        c = run(api, [f("P1", "/private/files/a.pdf", 1, field="supplier_invoice"),
                      f("O1", "/files/a.pdf", 0), f("O2", "/files/a.pdf", 0)])
        assert api.calls == [("set_value", "File", "O1", "content_hash", "cleanup-O1"), ("delete", "File", "O1"),
                             ("delete", "File", "O2")]          # zweite Kopie: Datei schon weg, nur Dokument
        assert c.total["deleted"] == 2 and c.total["fields"] == 0

    def test_keep_is_bound_to_field_and_field_set_when_public(self) -> None:
        api = StubApi(field_value="/files/a.pdf")
        c = run(api, [f("P1", "/private/files/a.pdf", 1), f("O1", "/files/a.pdf", 0)])
        assert ("update", {"doctype": "File", "name": "P1", "attached_to_field": "supplier_invoice"}) in api.calls
        assert ("set_value", "Purchase Invoice", "EK 1", "supplier_invoice", "/private/files/a.pdf") in api.calls
        assert c.total["fields"] == 1

    def test_field_pointing_to_private_file_is_left_alone(self) -> None:
        api = StubApi(field_value="/private/files/other.pdf")
        run(api, [f("P1", "/private/files/a.pdf", 1), f("P2", "/private/files/other.pdf", 1), f("O1", "/files/a.pdf", 0)])
        assert not any(c[0] == "set_value" and c[1] == "Purchase Invoice" for c in api.calls)

    def test_dry_run_changes_nothing(self, capsys: pytest.CaptureFixture[str]) -> None:
        api = StubApi()
        c = run(api, [f("P1", "/private/files/a.pdf", 1), f("O1", "/files/a.pdf", 0)], do_it=False)
        assert api.calls == []
        assert c.total["deleted"] == 1
        assert "öffentliche Kopie /files/a.pdf löschen" in capsys.readouterr().out


class TestDifferentContent:
    def test_is_privatised_and_kept(self) -> None:
        api = StubApi()
        c = run(api, [f("P1", "/private/files/a.pdf", 1), f("O1", "/files/b.pdf", 0, h="h2")])
        assert ("update", {"doctype": "File", "name": "O1", "is_private": 1}) in api.calls
        assert not any(c[0] == "delete" for c in api.calls)
        assert c.total["privatised"] == 1 and c.total["deleted"] == 0

    def test_collision_is_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        api = StubApi(private_twin=b"anders")
        c = run(api, [f("P1", "/private/files/a.pdf", 1), f("O1", "/files/b.pdf", 0, h="h2")])
        assert c.total["collisions"] == 1
        assert "bleibt öffentlich" in capsys.readouterr().out


class TestOnlyPublic:
    def test_first_is_privatised_rest_deleted(self) -> None:
        api = StubApi(field_value=None)
        c = run(api, [f("O1", "/files/a.pdf", 0), f("O2", "/files/a.pdf", 0)])
        assert api.calls[0] == ("update", {"doctype": "File", "name": "O1", "is_private": 1})
        # nach dem Umstellen liest das Skript die (von Frappe mit umgezogenen) Duplikate neu und löscht sie
        assert ("delete", "File", "F3") in api.calls
        assert ("set_value", "Purchase Invoice", "EK 1", "supplier_invoice", "/private/files/moved.pdf") in api.calls
        assert c.total["privatised"] == 1 and c.total["deleted"] == 1 and c.total["fields"] == 1

    def test_missing_file_documents_are_removed(self) -> None:
        api = StubApi(file_missing=True)
        c = run(api, [f("O1", "/files/a.pdf", 0), f("O2", "/files/a.pdf", 0)])
        assert [c for c in api.calls if c[0] == "delete"] == [("delete", "File", "O1"), ("delete", "File", "O2")]
        assert c.total["deleted"] == 2 and c.total["privatised"] == 0

    def test_identical_private_twin_is_adopted(self) -> None:
        api = StubApi(private_twin=b"gleich")
        api.contents = {"/files/a.pdf": b"gleich", "/private/files/a.pdf": b"gleich"}
        c = run(api, [f("O1", "/files/a.pdf", 0), f("O2", "/files/a.pdf", 0)])
        inserts = [c for c in api.calls if c[0] == "insert"]
        assert inserts and inserts[0][1]["file_url"] == "/private/files/a.pdf" and inserts[0][1]["is_private"] == 1
        assert ("set_value", "File", "O1", "content_hash", "cleanup-O1") in api.calls
        assert ("delete", "File", "O2") in api.calls
        assert c.total["collisions"] == 0

    def test_different_private_twin_is_skipped(self, capsys: pytest.CaptureFixture[str]) -> None:
        api = StubApi(private_twin=b"anders")
        api.contents = {"/files/a.pdf": b"eins", "/private/files/a.pdf": b"zwei"}
        c = run(api, [f("O1", "/files/a.pdf", 0)])
        assert not any(c[0] in ("delete", "insert") for c in api.calls)
        assert c.total["collisions"] == 1
        assert "Dokument übersprungen" in capsys.readouterr().out


def test_main_dry_run_summary(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class Api(StubApi):
        def get_list(self, doctype: str, filters: dict[str, Any] | None = None, fields: list[str] | None = None,
                     limit_page_length: int | None = None) -> list[dict[str, Any]]:
            if filters == {"attached_to_doctype": "Purchase Invoice"}:
                return [f("P1", "/private/files/a.pdf", 1), f("O1", "/files/a.pdf", 0)]
            if filters == {"attached_to_doctype": "PreRechnung"}:
                raise FrappeException("DocType PreRechnung not found")
            return []
    monkeypatch.setattr(cpa, "FrappeClient", lambda *a, **k: Api())
    assert cpa.main(["--server", "https://x", "--key", "k", "--secret", "s"]) == 0
    out = capsys.readouterr().out
    assert "Purchase Invoice: 1 Dokumente mit öffentlichen Anhängen" in out
    assert "1 öffentliche Kopien gelöscht" in out and "Probelauf" in out
    assert "PreRechnung: DocType PreRechnung not found" in out
