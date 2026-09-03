"""Gemeinsame Test-Konfiguration.

Reihenfolge ist wichtig: zuerst Stubs installieren, dann erst Projektmodule
importieren (die Projektmodule liegen im Repo-Wurzelverzeichnis).

Drei Testkategorien (Verzeichnis = Marker):

* tests/offline       - ohne Netz, Api.api ist ein FakeFrappeClient
* tests/online_read   - lesend gegen eine Instanz (ERPNEXT_TEST_SERVER/KEY/SECRET[/COMPANY])
* tests/online_write  - schreibend gegen eine TESTinstanz (zusätzlich ERPNEXT_TEST_WRITE=1)

Die Zugangsdaten werden bewusst NUR aus Umgebungsvariablen gelesen, nie aus
der erpnext.json des Benutzers - damit Schreibtests nie versehentlich auf der
Produktivinstanz laufen.
"""
from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any, Iterator

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
for p in (TESTS, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from support import stubs  # noqa: E402

STUBS = stubs.install()

import PySimpleGUI as sg  # noqa: E402  (Stub)
import easygui  # noqa: E402  (Stub)

if TYPE_CHECKING:
    from pathlib import Path

    from company import Company
    from support.fakes import FakeFrappeClient


# ------------------------------------------------------------- Marker
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        path = str(item.fspath)
        if os.sep + "offline" + os.sep in path:
            item.add_marker(pytest.mark.offline)
        elif os.sep + "online_read" + os.sep in path:
            item.add_marker(pytest.mark.online_read)
        elif os.sep + "online_write" + os.sep in path:
            item.add_marker(pytest.mark.online_write)


# --------------------------------------------------------- Umgebung
class OnlineConfig:
    def __init__(self) -> None:
        self.server: str | None = os.environ.get("ERPNEXT_TEST_SERVER")
        self.key: str | None = os.environ.get("ERPNEXT_TEST_KEY")
        self.secret: str | None = os.environ.get("ERPNEXT_TEST_SECRET")
        self.company: str | None = os.environ.get("ERPNEXT_TEST_COMPANY")
        self.write: bool = os.environ.get("ERPNEXT_TEST_WRITE") == "1"
        self.allow_submit: bool = os.environ.get("ERPNEXT_TEST_ALLOW_SUBMIT") == "1"
        self.max_invoices: int = int(os.environ.get("ERPNEXT_TEST_MAX_INVOICES", "25"))
        self.parser_min_match: float = float(os.environ.get("ERPNEXT_TEST_PARSER_MIN_MATCH", "0.5"))

    @property
    def configured(self) -> bool:
        return bool(self.server and self.key and self.secret)


@pytest.fixture(scope="session")
def online_config() -> OnlineConfig:
    return OnlineConfig()


# ------------------------------------------------- Zustand zurücksetzen
DEFAULT_SETTINGS: dict[str, Any] = {
    "-company-": "Bremer SolidarStrom",
    "-server-": "https://erpnext.test.invalid",
    "-key-": "testkey",
    "-secret-": "testsecret",
    "-buchen-": False,
    "-setup-": False,
    "-year-": 2026,
    "-folder-": ROOT,
    "-google-credentials-": None,
    "-invoice-processor-": None,
}


def _reset_project_state() -> None:
    """Klassenweite Caches der Projektmodule leeren (nur wenn schon importiert)."""
    api = sys.modules.get("api")
    if api is not None:
        api.Api.api = None
        api.Api.items_by_code = {}
        api.Api.item_code_translation = []
        api.Api.accounts_by_company = {}
    company = sys.modules.get("company")
    if company is not None:
        company.Company.companies_by_name = {}
    bank = sys.modules.get("bank")
    if bank is not None:
        bank.BankAccount.clear_baccounts()


@pytest.fixture(autouse=True)
def _clean_state() -> Iterator[None]:
    stubs.UserSettings.store = dict(DEFAULT_SETTINGS)
    easygui.reset()
    _reset_project_state()
    yield
    _reset_project_state()


@pytest.fixture
def user_settings() -> stubs.UserSettings:
    """Zugriff auf den (gestubbten) sg.UserSettings-Speicher."""
    return sg.UserSettings()


@pytest.fixture
def gui() -> stubs.EasyguiStub:
    """Antworten für easygui-Dialoge hinterlegen: gui.answers['choicebox'] = 'Wert'."""
    return easygui


@pytest.fixture
def fake_api() -> FakeFrappeClient:
    """FakeFrappeClient als Api.api installieren."""
    from support.fakes import FakeFrappeClient
    from api import Api
    client = FakeFrappeClient()
    Api.api = client
    return client


@pytest.fixture
def somiko(fake_api: FakeFrappeClient) -> Company:
    """Firma 'Bremer SolidarStrom' offline, mit Konten und Steuersätzen."""
    from support import factories
    return factories.make_company()


@pytest.fixture
def laden(fake_api: FakeFrappeClient) -> Company:
    from support import factories
    return factories.make_company(factories.LADEN, "Laden")


@pytest.fixture
def restore_locale() -> Iterator[None]:
    import locale
    old = locale.setlocale(locale.LC_ALL)
    yield
    try:
        locale.setlocale(locale.LC_ALL, old)
    except locale.Error:
        locale.setlocale(locale.LC_ALL, "C")


@pytest.fixture
def in_tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tests, die Dateien ins Arbeitsverzeichnis schreiben, laufen in tmp_path."""
    monkeypatch.chdir(tmp_path)
    return tmp_path
