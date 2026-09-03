"""Tests für frappeclient.FrappeClient mit nachgebildeter requests-Session (kein Netz)."""
import json
from base64 import b64encode

import pytest
import requests

import frappe
import frappeclient
from frappeclient import FrappeClient, FrappeException, AuthError
from support.fakes import FakeResponse, FakeSession

URL = "https://erp.example"


@pytest.fixture
def client():
    c = FrappeClient(URL, api_key="key", api_secret="secret")
    c.session = FakeSession()
    return c


def last(client):
    return client.session.requests[-1]


class TestAuthentication:
    def test_basic_auth_header(self, client):
        token = b64encode(b"key:secret").decode()
        assert client.headers["Authorization"] == "Basic " + token
        assert client.headers["Accept"] == "application/json"

    def test_without_key_no_auth_header(self):
        c = FrappeClient(URL)
        assert "Authorization" not in c.headers

    def test_authorization_source_header(self):
        c = FrappeClient(URL, api_key="k", api_secret="s", frappe_authorization_source="MyApp")
        assert c.headers["Frappe-Authorization-Source"] == "MyApp"

    def test_login_with_password(self, monkeypatch):
        session = FakeSession([FakeResponse({"message": "Logged In"})])
        monkeypatch.setattr(requests, "session", lambda: session)
        FrappeClient(URL, username="u", password="p")
        method, url, kwargs = session.requests[0]
        assert (method, url) == ("POST", URL)
        assert kwargs["params"] == {"cmd": "login", "usr": "u", "pwd": "p"}

    def test_login_failure_raises_autherror(self, monkeypatch):
        session = FakeSession([FakeResponse({"message": "Invalid"}, status_code=401)])
        monkeypatch.setattr(requests, "session", lambda: session)
        with pytest.raises(AuthError):
            FrappeClient(URL, username="u", password="falsch")

    @pytest.mark.xfail(strict=True, raises=NameError,
                       reason="SiteUnreachableError/SiteExpiredError sind in frappeclient.py nicht definiert")
    def test_login_502(self, monkeypatch):
        session = FakeSession([FakeResponse({"message": "x"}, status_code=502)])
        monkeypatch.setattr(requests, "session", lambda: session)
        with pytest.raises(FrappeException):
            FrappeClient(URL, username="u", password="p")

    def test_context_manager_logs_out(self, client):
        with client:
            pass
        method, url, kwargs = last(client)
        assert method == "GET" and kwargs["params"] == {"cmd": "logout"}


class TestGetList:
    def test_default_fields_and_no_limit(self, client):
        client.session.responses = [FakeResponse({"data": [{"name": "A"}]})]
        assert client.get_list("Company") == [{"name": "A"}]
        method, url, kwargs = last(client)
        assert method == "GET"
        assert url == URL + "/api/resource/Company"
        assert kwargs["params"] == {"fields": '["name"]'}

    def test_fields_filters_limit_order(self, client):
        client.get_list("Item", fields=["name", "item_code"], filters={"disabled": 0},
                        limit_start=10, limit_page_length=5, order_by="name asc")
        params = last(client)[2]["params"]
        assert json.loads(params["fields"]) == ["name", "item_code"]
        assert json.loads(params["filters"]) == {"disabled": 0}
        assert params["limit_start"] == 10
        assert params["limit_page_length"] == 5
        assert params["order_by"] == "name asc"

    def test_string_fields_pass_through(self, client):
        client.get_list("Item", fields='["*"]')
        assert last(client)[2]["params"]["fields"] == '["*"]'

    def test_list_filters(self, client):
        client.get_list("Bank Transaction", filters=[["Bank Transaction Payments", "payment_entry", "=", "X"]])
        assert json.loads(last(client)[2]["params"]["filters"]) == [["Bank Transaction Payments", "payment_entry", "=", "X"]]


class TestDocumentCalls:
    def test_insert_posts_json(self, client):
        client.session.responses = [FakeResponse({"data": {"name": "SUP-1", "doctype": "Supplier"}})]
        res = client.insert({"doctype": "Supplier", "supplier_name": "S"})
        assert isinstance(res, frappe._dict)
        assert res.name == "SUP-1"
        method, url, kwargs = last(client)
        assert (method, url) == ("POST", URL + "/api/resource/Supplier")
        assert json.loads(kwargs["data"]["data"]) == {"doctype": "Supplier", "supplier_name": "S"}

    def test_update_puts_to_named_resource(self, client):
        client.session.responses = [FakeResponse({"data": {"name": "S 1"}})]
        client.update({"doctype": "Supplier", "name": "S 1", "x": 1})
        method, url, kwargs = last(client)
        assert method == "PUT"
        assert url == URL + "/api/resource/Supplier/S 1"

    def test_update_with_doctype_does_not_modify_input(self, client):
        client.session.responses = [FakeResponse({"data": {}})]
        doc = {"name": "N"}
        client.update_with_doctype(doc, "Bank Account")
        assert doc == {"name": "N"}
        assert last(client)[1].endswith("/api/resource/Bank Account/N")

    def test_get_doc(self, client):
        client.session.responses = [FakeResponse({"data": {"name": "N", "items": []}})]
        assert client.get_doc("Purchase Invoice", "N", fields=["name"]) == {"name": "N", "items": []}
        method, url, kwargs = last(client)
        assert url == URL + "/api/resource/Purchase Invoice/N"
        assert kwargs["params"] == {"fields": '["name"]'}

    def test_get_doc_with_filters(self, client):
        client.get_doc("Item", filters={"a": 1})
        assert last(client)[2]["params"] == {"filters": '{"a": 1}'}

    def test_load_doc_returns_full_payload(self, client):
        payload = {"docs": [{"name": "L"}], "docinfo": {}}
        client.session.responses = [FakeResponse(payload)]
        assert client.load_doc("Lead", "L") == payload
        assert last(client)[1] == URL + "/api/method/frappe.desk.form.load.getdoc"

    @pytest.mark.parametrize("call, cmd", [
        (lambda c: c.delete("Supplier", "S"), "frappe.client.delete"),
        (lambda c: c.submit({"doctype": "Journal Entry", "name": "J"}), "frappe.client.submit"),
        (lambda c: c.cancel("Journal Entry", "J"), "frappe.client.cancel"),
        (lambda c: c.set_value("Item", "I", "f", 1), "frappe.client.set_value"),
        (lambda c: c.rename_doc("Item", "a", "b"), "frappe.client.rename_doc"),
        (lambda c: c.insert_many([{"doctype": "Item"}]), "frappe.client.insert_many"),
        (lambda c: c.bulk_update([{"doctype": "Item", "name": "I"}]), "frappe.client.bulk_update"),
    ])
    def test_post_commands(self, client, call, cmd):
        call(client)
        method, url, kwargs = last(client)
        assert method == "POST" and url == URL
        assert kwargs["data"]["cmd"] == cmd

    def test_submit_serialises_doc(self, client):
        client.submit({"doctype": "Journal Entry", "name": "J"})
        assert json.loads(last(client)[2]["data"]["doc"]) == {"doctype": "Journal Entry", "name": "J"}

    def test_get_value(self, client):
        client.session.responses = [FakeResponse({"message": {"name": "X"}})]
        assert client.get_value("Item", "name", {"item_code": "1"}) == {"name": "X"}
        params = last(client)[2]["params"]
        assert params["cmd"] == "frappe.client.get_value"
        assert json.loads(params["filters"]) == {"item_code": "1"}

    def test_preprocess_dumps_containers(self, client):
        assert client.preprocess({"a": {"x": 1}, "b": [1], "c": "s"}) == {"a": '{"x": 1}', "b": "[1]", "c": "s"}


class TestPostProcess:
    def test_message_and_data(self, client):
        assert client.post_process(FakeResponse({"message": 5})) == 5
        assert client.post_process(FakeResponse({"data": [1]})) == [1]
        assert client.post_process(FakeResponse({"docs": [1]})) == {"docs": [1]}
        assert client.post_process(FakeResponse({"other": 1})) is None

    def test_exc_raises_frappe_exception(self, client):
        exc = json.dumps(["Traceback ...\nValidationError: nein"])
        with pytest.raises(FrappeException) as e:
            client.post_process(FakeResponse({"exc": exc}))
        assert str(e.value).startswith("FrappeClient Request Failed")
        assert "ValidationError: nein" in str(e.value)

    def test_non_json_exc_is_passed_through(self, client):
        with pytest.raises(FrappeException, match="roh"):
            client.post_process(FakeResponse({"exc": "roh"}))

    def test_invalid_json_prints_and_raises(self, client, capsys):
        with pytest.raises(ValueError):
            client.post_process(FakeResponse(text="<html>Server Error</html>"))
        assert "Server Error" in capsys.readouterr().out


class TestFilesAndReports:
    def test_session_get_retries_on_connection_error(self, client, monkeypatch):
        monkeypatch.setattr(frappeclient.time, "sleep", lambda s: None)
        client.session.responses = [requests.exceptions.ConnectionError("down"), FakeResponse({"data": {"name": "N"}})]
        assert client.get_doc("Item", "N") == {"name": "N"}
        assert len(client.session.requests) == 2

    def test_get_pdf_streams_content(self, client):
        client.session.responses = [FakeResponse(content=b"%PDF-1.4 abc")]
        out = client.get_pdf("Sales Invoice", "R 1", print_format="Rechnung", letterhead=False, language="de")
        assert out.read() == b"%PDF-1.4 abc"
        params = last(client)[2]["params"]
        assert params["no_letterhead"] == 1 and params["format"] == "Rechnung" and params["_lang"] == "de"

    def test_get_pdf_error(self, client):
        client.session.responses = [FakeResponse({"exc": "Fehler"}, status_code=417)]
        with pytest.raises(FrappeException):
            client.get_pdf("Sales Invoice", "R 1")

    def test_get_file(self, client):
        client.session.responses = [FakeResponse(content=b"bytes")]
        assert client.get_file("/private/files/x.pdf") == b"bytes"
        assert last(client)[1] == URL + "/private/files/x.pdf"

    def test_attach_file_encodes_base64(self, client, tmp_path):
        p = tmp_path / "r.pdf"
        p.write_bytes(b"data")
        client.read_and_attach_file("Purchase Invoice", "EK 1", str(p), True)
        data = last(client)[2]["data"]
        assert data["cmd"] == "frappe.client.attach_file"
        assert data["filename"] == "r.pdf"
        assert data["filedata"] == b64encode(b"data")
        assert data["is_private"] == 1 and data["decode_base64"] == 1

    def test_query_report(self, client):
        client.session.responses = [FakeResponse({"message": {"result": [], "columns": []}})]
        assert client.query_report("General ledger", {"company": "X"}) == {"result": [], "columns": []}
        method, url, kwargs = last(client)
        assert url == URL + "/api/method/frappe.desk.query_report.run"
        assert kwargs["params"]["report_name"] == "General ledger"
        assert json.loads(kwargs["params"]["filters"]) == {"company": "X"}

    def test_assign_to(self, client):
        client.assign_to("Lead", "L", ["user@example.com"])
        method, url, kwargs = last(client)
        assert url == URL + "/api/method/frappe.desk.form.assign_to.add"
        assert json.loads(kwargs["params"]["assign_to"]) == ["user@example.com"]

    def test_get_attachments_and_background_jobs(self, client):
        client.get_attachments("Purchase Invoice", "EK 1")
        assert "run_method=frappe.core.doctype.file.file.get_attached_images" in last(client)[1]
        client.get_background_jobs()
        assert last(client)[2]["params"]["cmd"].endswith("background_jobs.get_info")
