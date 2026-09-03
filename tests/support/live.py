"""Verbindung zu einer echten ERPNext-Instanz für die Online-Tests.

Die Zugangsdaten kommen ausschließlich aus Umgebungsvariablen (siehe tests/conftest.py),
nie aus der erpnext.json des Benutzers.

* ``ReadOnlyClient`` umhüllt den FrappeClient und lässt jeden schreibenden Aufruf
  mit ``ReadOnlyViolation`` scheitern - die Nur-Lese-Tests können so nichts verändern,
  selbst wenn eine getestete Funktion unerwartet schreiben wollte.
* ``LiveState`` lädt Firmen, Bankkonten und die Daten der gewählten Firma einmal pro
  Sitzung und setzt sie vor jedem Test wieder in die Klassen-Registries ein (die der
  autouse-Fixture in tests/conftest.py jeweils leert).
* ``Cleanup`` merkt sich angelegte Dokumente und löscht sie am Testende wieder.
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
    """Ein Nur-Lese-Test hat versucht, auf der Instanz zu schreiben."""


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
    """Eindeutige Kennung für Testdokumente, damit sie auf der Instanz erkennbar bleiben."""
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
    except Exception as e:  # Verbindungs-/Auth-Fehler klar melden statt jeden Test einzeln scheitern zu lassen
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
        """Vor jedem Test: Einstellungen, Client und Registries wieder herstellen."""
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

    # ------------------------------------------------------------ Hilfen
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
    """Registrierte Dokumente am Testende löschen (gebuchte zuvor abbrechen)."""

    def __init__(self, client: FrappeClient) -> None:
        self.client: FrappeClient = client
        self.items: list[tuple[str, str]] = []
        self.restore_actions: list[Callable[[], Any]] = []

    def add(self, doctype: str, name: str) -> str:
        self.items.append((doctype, name))
        return name

    def restore(self, action: Callable[[], Any]) -> None:
        """Callable, das am Ende ausgeführt wird (z. B. Feldwert zurücksetzen)."""
        self.restore_actions.append(action)

    def run(self) -> list[tuple[str, str, str]]:
        errors: list[tuple[str, str, str]] = []
        for action in reversed(self.restore_actions):
            try:
                action()
            except Exception as e:
                errors.append(("restore", str(action), str(e)[:200]))
        pending = list(reversed(self.items))
        # Rechnungen an Test-Lieferanten, die ein abgebrochener Test nicht mehr registrieren konnte
        for doctype, name in self.items:
            if doctype == "Supplier":
                try:
                    for pi in self.client.get_list("Purchase Invoice", filters={"supplier": name}, limit_page_length=100):
                        if ("Purchase Invoice", pi["name"]) not in pending:
                            pending.insert(0, ("Purchase Invoice", pi["name"]))
                except FrappeException as e:
                    errors.append(("Purchase Invoice", "von " + name, str(e)[:200]))
        for attempt in range(2):          # zweiter Durchlauf löst Verkettungen (Link-Prüfungen) auf
            failed: list[tuple[str, str, str]] = []
            for doctype, name in pending:
                try:
                    doc = self.client.get_doc(doctype, name)
                except FrappeException:
                    continue        # gibt es (nicht mehr)
                try:
                    if doc.get("docstatus") == 1:
                        self.client.cancel(doctype, name)
                    self.client.delete(doctype, name)
                except Exception as e:
                    # letzte Zeile der Server-Antwort enthält den Ausnahmetyp (statt Traceback-Anfang)
                    failed.append((doctype, name, str(e).strip().splitlines()[-1][:300]))
            pending = [(d, n) for d, n, _ in failed]
            if not pending:
                break
        # stornierte Belege (und daran hängende Stammdaten) lassen sich in ERPNext nicht löschen,
        # weil Hauptbuch-/Payment-Ledger-Einträge darauf verweisen - sie bleiben als 'pytest-…' stehen
        cancelled = [(d, n) for d, n, msg in failed if "LinkExistsError" in msg]
        errors.extend(f for f in failed if "LinkExistsError" not in f[2])
        if cancelled:
            print("Storniert und absichtlich belassen (nicht löschbar): {}".format(cancelled))
        if errors:
            warnings.warn("Aufräumen unvollständig, bitte auf der Testinstanz prüfen: {}".format(errors))
        return errors
