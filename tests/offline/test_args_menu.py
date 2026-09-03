"""Tests für args.py (Kommandozeile, Einstellungen) und die GUI-freien Teile von menu.py."""
import json
import sys

import pytest

from support import factories as F
from support.deps import skip_module_without_pdftotext
from support.stubs import GuiCalled

skip_module_without_pdftotext()

import args  # noqa: E402
import bank  # noqa: E402
import journal  # noqa: E402
import menu  # noqa: E402
import prerechnung  # noqa: E402
import utils  # noqa: E402
from api import Api  # noqa: E402
from company import Company  # noqa: E402
from support.fakes import FakeFrappeClient  # noqa: E402
from version import VERSION  # noqa: E402


class TestArgParser:
    def test_defaults(self):
        a = args.arg_parser().parse_args([])
        assert a.e is None and a.p is None and a.k is None
        assert a.i is False and a.b is False and a.v is False
        assert a.update_stock is False and a.selbst_bezahlt is False and a.anzahlung is False
        assert a.all_sales is False and a.price_dates is False
        assert a.betrag is None and a.company is None

    def test_pre_invoice_flag_with_and_without_name(self):
        assert args.arg_parser().parse_args(["-p"]).p == ""
        assert args.arg_parser().parse_args(["-p", "PreR00001"]).p == "PreR00001"

    def test_overrides(self):
        a = args.arg_parser().parse_args(["-p", "--betrag", "119,5".replace(",", "."), "--mwst", "19", "--rechnungsnr", "R-1",
                                          "--datum", "01.02.2026", "--konto", "4210", "--lieferant", "L",
                                          "--projekt", "P", "--selbst-bezahlt", "--anzahlung", "--update-stock",
                                          "--company", "Laden", "--server", "https://s", "--key", "k", "--secret", "s"])
        assert a.betrag == 119.5 and a.mwst == 19.0 and a.rechnungsnr == "R-1" and a.datum == "01.02.2026"
        assert a.konto == "4210" and a.lieferant == "L" and a.projekt == "P"
        assert a.selbst_bezahlt and a.anzahlung and a.update_stock
        assert (a.company, a.server, a.key, a.secret) == ("Laden", "https://s", "k", "s")

    def test_invalid_amount(self):
        with pytest.raises(SystemExit):
            args.arg_parser().parse_args(["--betrag", "abc"])


class TestGoogleCredentials:
    def test_set_google_credentials_from_string(self, in_tmp_cwd, user_settings):
        args.set_google_credentials(json.dumps({"project_id": "p", "private_key": "a\\nb"}))
        stored = json.load(open(in_tmp_cwd / "google-credentials.json"))
        assert stored == {"project_id": "p", "private_key": "a\nb"}
        assert user_settings["-google-credentials-"] == stored

    def test_set_google_credentials_from_dict(self, in_tmp_cwd, user_settings):
        args.set_google_credentials({"project_id": "q"})
        assert user_settings["-google-credentials-"]["project_id"] == "q"


class TestInit:
    def test_init_applies_arguments_and_connects(self, monkeypatch, user_settings, in_tmp_cwd):
        import PySimpleGUI as sg
        monkeypatch.setattr(sys, "argv", ["erpnext.py", "--company", "Laden", "--server", "https://s", "--key", "k",
                                          "--secret", "sec", "--invoice-processor", "proc",
                                          "--google-json", json.dumps({"project_id": "p"}), "-b"])
        created = {}

        def factory(url, api_key=None, api_secret=None):
            c = FakeFrappeClient(url, api_key, api_secret)
            c.add("Company", name="Laden")
            created["c"] = c
            return c
        import api
        monkeypatch.setattr(api, "FrappeClient", factory)
        a = args.init()
        assert a.b is True
        assert sg.UserSettings.filename == "erpnext.json"
        assert (user_settings["-company-"], user_settings["-server-"], user_settings["-key-"], user_settings["-secret-"]) == \
            ("Laden", "https://s", "k", "sec")
        assert user_settings["-invoice-processor-"] == "proc"
        assert user_settings["-google-credentials-"] == {"project_id": "p"}
        assert user_settings["-setup-"] is False
        assert Api.api is created["c"]

    def test_init_version_exits(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["erpnext.py", "-v"])
        with pytest.raises(SystemExit):
            args.init()
        assert VERSION in capsys.readouterr().out

    def test_init_failed_connection_sets_setup(self, monkeypatch, user_settings):
        monkeypatch.setattr(sys, "argv", ["erpnext.py"])
        import api

        def broken(*a, **k):
            raise ConnectionError("down")
        monkeypatch.setattr(api, "FrappeClient", broken)
        with pytest.raises(ConnectionError):
            args.init()     # Api.initialize ist hier nicht durch den Wrapper geschützt


@pytest.fixture
def loaded(fake_api, user_settings):
    F.seed_company_data(fake_api)
    fake_api.add("Bank Account", **F.bank_account_doc())
    user_settings["-company-"] = None
    return fake_api


class TestInitialLoads:
    def test_loads_companies_and_accounts(self, loaded, user_settings):
        menu.initial_loads()
        assert Company.all() == [F.COMPANY]
        assert user_settings["-company-"] == F.COMPANY
        assert Company.get_company(F.COMPANY).data_loaded is True
        assert list(bank.BankAccount.baccounts_by_name) == ["Sparkasse Bremen - SoMiKo"]

    def test_skipped_during_setup(self, loaded, user_settings):
        user_settings["-setup-"] = True
        menu.initial_loads()
        assert Company.all() == [] and loaded.calls == []


class TestShowData:
    def test_prints_overview(self, loaded, user_settings, capsys):
        menu.initial_loads()
        comp = Company.get_company(F.COMPANY)
        bacc = bank.BankAccount.baccounts_by_name["Sparkasse Bremen - SoMiKo"]
        bacc.balance, bacc.statement_balance = 100.0, 90.0
        loaded.add("Bank Transaction", **F.bank_transaction_doc(bacc.name, deposit=5.0))
        loaded.add("Journal Entry", company=comp.name, docstatus=0, accounts=[])
        loaded.add("PreRechnung", company=comp.name, eingepflegt=False, typ="Rechnung", datum="2026-01-01")
        loaded.background_jobs = [{"name": "job"}]
        menu.show_data()
        out = capsys.readouterr().out
        assert "Bereich: " + F.COMPANY in out
        assert "letzter Auszug: 01.08.2026" in out
        assert "Kontostand laut ERPNext: 100.00" in out and "laut Auszug: 90.00" in out
        assert "Differenz: 10.00" in out
        assert "1 offene Banktransaktionen" in out and "1 offene Buchungssätze" in out
        assert "1 offene Prerechnungen" in out and "1 offene Hintergrund-Jobs" in out
        assert "offene Einkaufsrechnungen" not in out

    def test_silent_during_setup(self, loaded, user_settings, capsys):
        user_settings["-setup-"] = True
        menu.show_data()
        assert capsys.readouterr().out == ""


class Window:
    def __init__(self):
        self.title = None
        self.closed = False

    def set_title(self, t):
        self.title = t

    def close(self):
        self.closed = True


class TestEventHandler:
    def test_exit_and_close(self, fake_api):
        import PySimpleGUI as sg
        assert menu.event_handler(sg.WIN_CLOSED, Window()) == "exit"
        assert menu.event_handler("Exit", Window()) == "exit"

    def test_company_switch(self, loaded, user_settings):
        menu.initial_loads()
        assert menu.event_handler(F.COMPANY, Window()) == "outer"
        assert user_settings["-company-"] == F.COMPANY

    def test_info_events(self, fake_api, capsys):
        assert menu.event_handler("Über", Window()) == "inner"
        assert VERSION in capsys.readouterr().out
        menu.event_handler("Hilfe Rechnungen", Window())
        assert "Krannich Solar GmbH & Co KG" in capsys.readouterr().out
        for ev in ("Hilfe Server", "Hilfe Banktransaktionen", "Hilfe Buchen"):
            assert menu.event_handler(ev, Window()) == "inner"

    def test_setup_required_message(self, fake_api, user_settings, capsys):
        user_settings["-setup-"] = True
        assert menu.event_handler("Kontoauszug", Window()) == "inner"
        assert "Bitte erst ERPNext-Server einstellen" in capsys.readouterr().out

    def test_year_choice(self, fake_api, user_settings, gui):
        gui.answers["choicebox"] = "2024"
        menu.event_handler("Jahr", Window())
        assert user_settings["-year-"] == 2024
        assert "aktuell: 2026" in gui.calls[0][1][0]
        gui.answers["choicebox"] = None
        menu.event_handler("Jahr", Window())
        assert user_settings["-year-"] == 2024

    def test_reload_data(self, loaded, user_settings, capsys):
        menu.initial_loads()
        n = len(loaded.calls)
        w = Window()
        assert menu.event_handler("Daten neu laden", w) == "inner"
        assert len(loaded.calls) > n
        assert w.title == utils.title()
        assert "Bereich:" in capsys.readouterr().out

    def test_kontoauszug(self, loaded, user_settings, monkeypatch, tmp_path, capsys):
        menu.initial_loads()
        fn = F.write_sparkasse_csv(tmp_path / "k.csv", [{"date": "15.08.26", "purpose": "Test", "partner": "P", "amount": "1,00"}])
        monkeypatch.setattr(utils, "get_file", lambda title: fn)
        menu.event_handler("Kontoauszug", Window())
        out = capsys.readouterr().out
        assert "1 Banktransaktionen eingelesen, davon 1 neu" in out
        assert len(loaded.get_list("Bank Transaction")) == 1

    def test_kontoauszug_cancelled(self, loaded, monkeypatch):
        menu.initial_loads()
        monkeypatch.setattr(utils, "get_file", lambda title: None)
        assert menu.event_handler("Kontoauszug", Window()) == "inner"

    def test_delegating_events(self, loaded, user_settings, monkeypatch):
        menu.initial_loads()
        seen = []
        monkeypatch.setattr(prerechnung, "process", lambda c: seen.append(("process", c)))
        monkeypatch.setattr(journal, "vat_declaration", lambda c, q: seen.append(("vat", c, q)))
        monkeypatch.setattr(journal, "create_tax_journal_entries", lambda c, q: seen.append(("tax", c, q)))
        monkeypatch.setattr(bank.BankTransaction, "unreconcile_for_cancelled_links", classmethod(lambda cls: seen.append("unrec")))
        menu.event_handler("Prerechnungen vorprozessieren", Window())
        menu.event_handler("USt-Voranmeldung", Window())
        menu.event_handler("USt-Buchungen", Window())
        menu.event_handler("Banktransaktionen für abgebr. Links bereinigen", Window())
        q = utils.last_quarter(__import__("datetime").datetime.today())
        assert seen == [("process", F.COMPANY), ("vat", F.COMPANY, q), ("tax", F.COMPANY, q), "unrec"]

    def test_report_without_data_is_skipped(self, loaded, monkeypatch):
        import report
        menu.initial_loads()
        monkeypatch.setattr(report, "build_report", lambda *a, **k: None)
        assert menu.event_handler("Abrechnung", Window()) == "inner"

    def test_gui_events_are_detected(self, loaded):
        menu.initial_loads()
        with pytest.raises(GuiCalled):
            menu.event_handler("Sofort buchen", Window())
