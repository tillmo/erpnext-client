"""Fixtures für schreibende Tests gegen eine ERPNext-TESTINSTANZ.

Aktivierung zusätzlich zu den Lese-Variablen:

    ERPNEXT_TEST_WRITE=1            Schreibtests freischalten
    ERPNEXT_TEST_ALLOW_SUBMIT=1     zusätzlich Tests, die Dokumente buchen (docstatus 1) und wieder abbrechen

Alle angelegten Dokumente tragen 'pytest-<id>' im Namen bzw. in einer Referenz und werden
am Testende über die Cleanup-Fixture gelöscht. Trotzdem: nur gegen eine Instanz laufen lassen,
deren Daten entbehrlich sind.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

import pytest

import settings
from support.live import Cleanup, LiveState, tag

if TYPE_CHECKING:
    from company import Company
    from conftest import OnlineConfig
    from frappeclient import FrappeClient
    from support.live import ReadOnlyClient


@pytest.fixture(scope="session")
def live(online_config: OnlineConfig) -> LiveState:
    if not online_config.write:
        pytest.skip("Schreibtests nur mit ERPNEXT_TEST_WRITE=1")
    return LiveState(online_config)


@pytest.fixture(autouse=True)
def _live_env(live: LiveState) -> Iterator[FrappeClient | ReadOnlyClient]:
    yield live.install(read_only=False)


@pytest.fixture
def api(live: LiveState) -> FrappeClient:
    from api import Api
    return Api.api


@pytest.fixture
def comp(live: LiveState) -> Company:
    return live.company


@pytest.fixture
def cleanup(live: LiveState) -> Iterator[Cleanup]:
    c = Cleanup(live.client)
    yield c
    c.run()


@pytest.fixture
def test_supplier(api: FrappeClient, cleanup: Cleanup) -> str:
    """Ein frischer Lieferant nur für diesen Test."""
    name = tag("Lieferant")
    api.insert({"doctype": "Supplier", "supplier_name": name, "supplier_group": settings.DEFAULT_SUPPLIER_GROUP})
    cleanup.add("Supplier", name)
    return name


@pytest.fixture
def submit_allowed(online_config: OnlineConfig) -> bool:
    if not online_config.allow_submit:
        pytest.skip("Buchen nur mit ERPNEXT_TEST_ALLOW_SUBMIT=1")
    return True


@pytest.fixture
def today() -> str:
    import datetime
    return datetime.date.today().strftime("%Y-%m-%d")
