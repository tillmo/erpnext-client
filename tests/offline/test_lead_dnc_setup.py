"""Tests for lead_dnc_setup.py (server-side protection of leads marked "Do Not Contact")."""
from __future__ import annotations

import json
from typing import Any

import pytest

import lead_dnc_setup as setup
from settings import LEAD_DNC_FIELD
from support.fakes import FakeFrappeClient


def version(docname: str, old: str, new: str, when: str) -> dict[str, Any]:
    return {"doctype": "Version", "ref_doctype": "Lead", "docname": docname, "creation": when,
            "data": json.dumps({"changed": [["status", old, new]]})}


class TestServerObjects:
    def test_custom_field_is_created_once(self, fake_api: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        assert setup.ensure_custom_field(fake_api, apply=False) is False
        assert fake_api.get_list("Custom Field") == []
        assert setup.ensure_custom_field(fake_api, apply=True) is True
        assert setup.ensure_custom_field(fake_api, apply=True) is True
        fields = fake_api.get_list("Custom Field", fields=["dt", "fieldname", "fieldtype"])
        assert fields == [{"dt": "Lead", "fieldname": LEAD_DNC_FIELD, "fieldtype": "Check"}]
        assert "fehlt" in capsys.readouterr().out

    def test_server_script_is_created_and_updated(self, fake_api: FakeFrappeClient) -> None:
        assert setup.ensure_server_script(fake_api, apply=False) is False
        assert setup.ensure_server_script(fake_api, apply=True) is True
        doc = fake_api.get_doc("Server Script", setup.SERVER_SCRIPT_NAME)
        assert doc["reference_doctype"] == "Communication" and doc["doctype_event"] == "After Save"
        assert LEAD_DNC_FIELD in doc["script"] and doc["disabled"] == 0
        # an outdated or disabled script is brought up to date
        doc["script"] = "# alt"
        doc["disabled"] = 1
        fake_api.update(doc)
        assert setup.ensure_server_script(fake_api, apply=False) is False
        assert setup.ensure_server_script(fake_api, apply=True) is True
        doc = fake_api.get_doc("Server Script", setup.SERVER_SCRIPT_NAME)
        assert doc["script"] == setup.SERVER_SCRIPT and doc["disabled"] == 0

    def test_script_only_touches_received_mails_of_flagged_leads(self) -> None:
        # the script text is Python: it has to compile, and it must restore exactly this status
        compile(setup.SERVER_SCRIPT, "server_script", "exec")
        assert 'doc.sent_or_received == "Received"' in setup.SERVER_SCRIPT
        assert 'frappe.db.set_value("Lead", doc.reference_name, "status", "Do Not Contact")' in setup.SERVER_SCRIPT


class TestClassify:
    LEADS = [
        {"name": "L-DNC", "status": "Do Not Contact", LEAD_DNC_FIELD: 0},
        {"name": "L-FLAGGED", "status": "Do Not Contact", LEAD_DNC_FIELD: 1},
        {"name": "L-REOPENED", "status": "Open", LEAD_DNC_FIELD: 0},        # marked, reopened by mail
        {"name": "L-PERSON", "status": "Open", LEAD_DNC_FIELD: 0},          # marked, then reopened by a person
        {"name": "L-NEW", "status": "Open", LEAD_DNC_FIELD: 0},
        {"name": "L-CUSTOMER", "status": "Converted", LEAD_DNC_FIELD: 0},   # marked once, later converted
    ]
    VERSIONS = [
        version("L-DNC", "Open", "Do Not Contact", "2025-01-01 10:00:00"),
        version("L-REOPENED", "Open", "Do Not Contact", "2025-01-01 10:00:00"),
        version("L-REOPENED", "Open", "Do Not Contact", "2025-03-01 10:00:00"),
        version("L-PERSON", "Open", "Do Not Contact", "2025-01-01 10:00:00"),
        version("L-PERSON", "Do Not Contact", "Open", "2025-02-01 10:00:00"),
        version("L-CUSTOMER", "Open", "Do Not Contact", "2025-01-01 10:00:00"),
        version("L-CUSTOMER", "Open", "Converted", "2025-04-01 10:00:00"),
        {"doctype": "Version", "ref_doctype": "Lead", "docname": "L-NEW", "creation": "2025-01-01 10:00:00",
         "data": "kein json"},
    ]

    def test_classify(self) -> None:
        flag, close = setup.classify(self.LEADS, self.VERSIONS)
        assert flag == ["L-DNC"]
        assert close == ["L-REOPENED"]

    def test_status_changes_are_sorted(self) -> None:
        changes = setup.status_changes(list(reversed(self.VERSIONS)))
        assert [c[2] for c in changes["L-PERSON"]] == ["Do Not Contact", "Open"]
        assert "L-NEW" not in changes


class TestBackfill:
    @pytest.fixture
    def data(self, fake_api: FakeFrappeClient) -> FakeFrappeClient:
        for lead in TestClassify.LEADS:
            fake_api.add("Lead", lead_name=lead["name"], **lead)
        for v in TestClassify.VERSIONS:
            fake_api.add(**v)
        return fake_api

    def test_dry_run_changes_nothing(self, data: FakeFrappeClient, capsys: pytest.CaptureFixture[str]) -> None:
        assert setup.backfill(data, apply=False) == (0, 0)
        assert data.calls_of("update") == []
        assert "2 Leads würden markiert" in capsys.readouterr().out

    def test_apply_flags_and_closes(self, data: FakeFrappeClient) -> None:
        assert setup.backfill(data, apply=True) == (2, 0)
        assert data.get_doc("Lead", "L-DNC")[LEAD_DNC_FIELD] == 1
        reopened = data.get_doc("Lead", "L-REOPENED")
        assert reopened[LEAD_DNC_FIELD] == 1 and reopened["status"] == "Do Not Contact"
        for untouched in ("L-PERSON", "L-NEW", "L-CUSTOMER"):
            assert data.get_doc("Lead", untouched)[LEAD_DNC_FIELD] == 0
        assert data.get_doc("Lead", "L-PERSON")["status"] == "Open"
        # idempotent
        assert setup.backfill(data, apply=True) == (0, 0)

    def test_status_recomputed_by_server_removes_flag(self, data: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
        # ERPNext turns a lead with a linked customer into "Converted" on save
        original = data.update

        def update(doc: dict[str, Any]) -> Any:
            if doc["name"] == "L-DNC" and doc.get(LEAD_DNC_FIELD):
                doc = dict(doc, status="Converted")
            return original(doc)
        monkeypatch.setattr(data, "update", update)
        assert setup.backfill(data, apply=True) == (1, 0)
        converted = data.get_doc("Lead", "L-DNC")
        assert converted["status"] == "Converted" and converted[LEAD_DNC_FIELD] == 0
        assert data.get_doc("Lead", "L-REOPENED")[LEAD_DNC_FIELD] == 1
        assert "L-DNC hat nach dem Speichern Status 'Converted'" in capsys.readouterr().out

    def test_limit(self, data: FakeFrappeClient) -> None:
        assert setup.backfill(data, apply=True, limit=1) == (1, 0)
        assert data.get_doc("Lead", "L-DNC")[LEAD_DNC_FIELD] == 1
        assert data.get_doc("Lead", "L-REOPENED")[LEAD_DNC_FIELD] == 0


class TestMain:
    def test_main_dry_run(self, fake_api: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch,
                          capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(setup, "FrappeClient", lambda url, api_key=None, api_secret=None: fake_api)
        fake_api.add("Lead", name="L-DNC", lead_name="x", status="Do Not Contact")
        # before the field exists, the dry run must not query it (Frappe rejects unknown fields)
        original = fake_api.get_list

        def get_list(doctype: str, fields: Any = '["name"]', **kw: Any) -> Any:
            assert not (doctype == "Lead" and LEAD_DNC_FIELD in fields)
            return original(doctype, fields, **kw)
        monkeypatch.setattr(fake_api, "get_list", get_list)
        assert setup.main(["--server", "https://srv", "--key", "k", "--secret", "s"]) == 0
        out = capsys.readouterr().out
        assert "fehlt" in out and "1 Leads würden markiert" in out
        assert fake_api.get_list("Custom Field") == [] and fake_api.calls_of("update") == []

    def test_main_apply(self, fake_api: FakeFrappeClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(setup, "FrappeClient", lambda url, api_key=None, api_secret=None: fake_api)
        fake_api.add("Lead", name="L-DNC", lead_name="x", status="Do Not Contact")
        assert setup.main(["--server", "https://srv", "--key", "k", "--secret", "s", "--apply"]) == 0
        assert len(fake_api.get_list("Custom Field")) == 1
        assert fake_api.get_doc("Server Script", setup.SERVER_SCRIPT_NAME)["disabled"] == 0
        assert fake_api.get_doc("Lead", "L-DNC")[LEAD_DNC_FIELD] == 1
