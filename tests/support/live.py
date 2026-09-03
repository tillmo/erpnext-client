"""Connection to a real ERPNext instance for the online tests.

The credentials come exclusively from environment variables (see tests/conftest.py),
never from the user's erpnext.json.

* ``ReadOnlyClient`` wraps the FrappeClient and makes every writing call fail with
  ``ReadOnlyViolation`` - so the read-only tests cannot change anything, even if a
  function under test unexpectedly tried to write.
* ``LiveState`` loads companies, bank accounts and the data of the selected company once
  per session and reinstates them in the class registries before each test (which the
  autouse fixture in tests/conftest.py clears each time).
* ``Cleanup`` remembers created documents and deletes them again at the end of the test.
"""
from __future__ import annotations

import datetime
import uuid
import warnings
from typing import TYPE_CHECKING, Any, Callable, NoReturn

import pytest
import PySimpleGUI as sg

from frappeclient import FrappeClient, FrappeException

if TYPE_CHECKING:
    from bank import BankAccount
    from company import Company
    from conftest import OnlineConfig

WRITE_METHODS = {"insert", "insert_many", "update", "update_with_doctype", "bulk_update", "delete", "submit",
                 "cancel", "set_value", "rename_doc", "attach_file", "read_and_attach_file", "assign_to",
                 "post_api", "post_request", "_login", "logout"}


class ReadOnlyViolation(RuntimeError):
    """A read-only test tried to write to the instance."""


class ReadOnlyClient:
    def __init__(self, client: FrappeClient) -> None:
        self._client: FrappeClient = client
        self.blocked: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._client, name)
        if name in WRITE_METHODS:
            def blocked(*args: Any, **kwargs: Any) -> NoReturn:
                self.blocked.append((name, args, kwargs))
                raise ReadOnlyViolation("Schreibzugriff '{}' in einem Nur-Lese-Test".format(name))
            return blocked
        return attr


def tag(prefix: str = "pytest") -> str:
    """Unique identifier for test documents so that they remain recognisable on the instance."""
    return "{}-{}".format(prefix, uuid.uuid4().hex[:8])


def apply_settings(config: OnlineConfig, company: str) -> None:
    sg.UserSettings.store.update({"-server-": config.server, "-key-": config.key, "-secret-": config.secret,
                                  "-company-": company, "-setup-": False, "-buchen-": False,
                                  "-year-": datetime.date.today().year})


def connect(config: OnlineConfig) -> tuple[FrappeClient, list[str]]:
    if not config.configured:
        pytest.skip("ERPNEXT_TEST_SERVER/ERPNEXT_TEST_KEY/ERPNEXT_TEST_SECRET nicht gesetzt")
    client = FrappeClient(config.server, api_key=config.key, api_secret=config.secret)
    try:
        companies = [c["name"] for c in client.get_list("Company")]
    except Exception as e:  # report connection/auth errors clearly instead of letting every test fail individually
        pytest.skip("Keine Verbindung zu {}: {}".format(config.server, str(e)[:200]))
    if not companies:
        pytest.skip("Die Instanz hat keine Firma")
    return client, companies


class LiveState:
    client: FrappeClient
    companies: list[str]

    def __init__(self, config: OnlineConfig) -> None:
        import bank
        import company as company_mod
        from api import Api
        self.config: OnlineConfig = config
        self.client, self.companies = connect(config)
        self.company_name: str = config.company or self.companies[0]
        if self.company_name not in self.companies:
            pytest.skip("ERPNEXT_TEST_COMPANY={!r} gibt es auf der Instanz nicht (vorhanden: {})".format(
                self.company_name, ", ".join(self.companies)))
        apply_settings(config, self.company_name)
        Api.api = self.client
        company_mod.Company.companies_by_name = {}
        bank.BankAccount.clear_baccounts()
        company_mod.Company.init_companies()
        bank.BankAccount.init_baccounts()
        self.company: Company = company_mod.Company.get_company(self.company_name)
        self.company.load_data()
        self.companies_by_name: dict[str, Company] = dict(company_mod.Company.companies_by_name)
        self.baccounts_by_iban: dict[str, BankAccount] = dict(bank.BankAccount.baccounts_by_iban)
        self.baccounts_by_name: dict[str, BankAccount] = dict(bank.BankAccount.baccounts_by_name)
        self.baccounts_by_company: dict[str, list[BankAccount]] = {
            k: list(v) for k, v in bank.BankAccount.baccounts_by_company.items()}
        self.accounts_by_company: dict[str, list[dict[str, Any]]] = dict(Api.accounts_by_company)

    def install(self, read_only: bool) -> FrappeClient | ReadOnlyClient:
        """Before each test: restore settings, client and registries."""
        import bank
        import company as company_mod
        from api import Api
        from collections import defaultdict
        apply_settings(self.config, self.company_name)
        Api.api = ReadOnlyClient(self.client) if read_only else self.client
        Api.accounts_by_company = dict(self.accounts_by_company)
        company_mod.Company.companies_by_name = dict(self.companies_by_name)
        bank.BankAccount.baccounts_by_iban = dict(self.baccounts_by_iban)
        bank.BankAccount.baccounts_by_name = dict(self.baccounts_by_name)
        bank.BankAccount.baccounts_by_company = defaultdict(list, {k: list(v) for k, v in self.baccounts_by_company.items()})
        return Api.api

    # ----------------------------------------------------------- Helpers
    def bank_accounts(self) -> list[BankAccount]:
        return self.baccounts_by_company.get(self.company_name, [])

    def expense_leaf(self) -> str:
        accs = [a for a in self.company.leaf_accounts if a["root_type"] == "Expense"]
        if not accs:
            pytest.skip("Firma {} hat kein Aufwandskonto".format(self.company_name))
        return accs[0]["name"]

    def income_leaf(self) -> str:
        accs = [a for a in self.company.leaf_accounts if a["root_type"] == "Income"]
        if not accs:
            pytest.skip("Firma {} hat kein Ertragskonto".format(self.company_name))
        return accs[0]["name"]

    def bank_leaf(self) -> str:
        baccs = self.bank_accounts()
        if baccs:
            return baccs[0].e_account
        accs = [a for a in self.company.leaf_accounts if a["root_type"] == "Asset"]
        if not accs:
            pytest.skip("Firma {} hat kein Aktivkonto".format(self.company_name))
        return accs[0]["name"]

    def doctype_exists(self, doctype: str) -> bool:
        try:
            self.client.get_list(doctype, limit_page_length=1)
            return True
        except FrappeException:
            return False


class Cleanup:
    """Delete registered documents at the end of the test (cancel submitted ones first)."""

    def __init__(self, client: FrappeClient) -> None:
        self.client: FrappeClient = client
        self.items: list[tuple[str, str]] = []
        self.restore_actions: list[Callable[[], Any]] = []

    def add(self, doctype: str, name: str) -> str:
        self.items.append((doctype, name))
        return name

    def restore(self, action: Callable[[], Any]) -> None:
        """Callable that is executed at the end (e.g. resetting a field value)."""
        self.restore_actions.append(action)

    def run(self) -> list[tuple[str, str, str]]:
        errors: list[tuple[str, str, str]] = []
        for action in reversed(self.restore_actions):
            try:
                action()
            except Exception as e:
                errors.append(("restore", str(action), str(e)[:200]))
        pending = list(reversed(self.items))
        # invoices to test suppliers that an aborted test could no longer register
        for doctype, name in self.items:
            if doctype == "Supplier":
                try:
                    for pi in self.client.get_list("Purchase Invoice", filters={"supplier": name}, limit_page_length=100):
                        if ("Purchase Invoice", pi["name"]) not in pending:
                            pending.insert(0, ("Purchase Invoice", pi["name"]))
                except FrappeException as e:
                    errors.append(("Purchase Invoice", "von " + name, str(e)[:200]))
        for attempt in range(2):          # a second pass resolves chains (link checks)
            failed: list[tuple[str, str, str]] = []
            for doctype, name in pending:
                try:
                    doc = self.client.get_doc(doctype, name)
                except FrappeException:
                    continue        # does not exist (any more)
                try:
                    if doc.get("docstatus") == 1:
                        self.client.cancel(doctype, name)
                    self.client.delete(doctype, name)
                except Exception as e:
                    # the last line of the server response contains the exception type (instead of the start of the traceback)
                    failed.append((doctype, name, str(e).strip().splitlines()[-1][:300]))
            pending = [(d, n) for d, n, _ in failed]
            if not pending:
                break
        # cancelled documents (and master data attached to them) cannot be deleted in ERPNext,
        # because general ledger / payment ledger entries refer to them - they remain as 'pytest-…'
        cancelled = [(d, n) for d, n, msg in failed if "LinkExistsError" in msg]
        errors.extend(f for f in failed if "LinkExistsError" not in f[2])
        if cancelled:
            print("Storniert und absichtlich belassen (nicht löschbar): {}".format(cancelled))
        if errors:
            warnings.warn("Aufräumen unvollständig, bitte auf der Testinstanz prüfen: {}".format(errors))
        return errors
