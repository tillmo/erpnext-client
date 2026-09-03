"""Berichte gegen echte Daten: Abrechnung, Bilanz, Hauptbuch, Projekte, Chancen."""
import datetime

import pytest

import journal
import report
import table


class TestFinancialStatements:
    @pytest.mark.parametrize("kwargs", [
        dict(consolidated=False, balance=False, periodicity="Yearly"),
        dict(consolidated=False, balance=False, periodicity="Quarterly"),
        dict(consolidated=True, balance=False, periodicity="Yearly"),
        dict(consolidated=False, balance=True, periodicity=None),
    ], ids=["pl-yearly", "pl-quarterly", "consolidated", "balance"])
    def test_build_report(self, live, user_settings, kwargs):
        user_settings["-year-"] = datetime.date.today().year
        tbl = report.build_report(live.company_name, **kwargs)
        assert isinstance(tbl, table.Table), "Bericht liefert keine Daten"
        if not tbl.entries:
            pytest.skip("Firma {} hat keine Buchungen im Berichtszeitraum".format(live.company_name))
        assert tbl.headings[0] in ("Einnahmen/Ausgaben", "Bilanz")
        assert all("account_name" in e for e in tbl.entries)
        assert all(len(e["account_name"]) <= 39 for e in tbl.entries)

    def test_build_report_previous_year(self, live, user_settings):
        # get_dates: das Vorjahr läuft bis heute, ältere Jahre bis zum 31.12.
        user_settings["-year-"] = datetime.date.today().year - 1
        assert report.build_report(live.company_name).title.endswith(datetime.date.today().strftime("%d.%m.%Y"))
        user_settings["-year-"] = datetime.date.today().year - 2
        assert report.build_report(live.company_name).title.endswith("31.12.{}".format(datetime.date.today().year - 2))


class TestGeneralLedger:
    def test_get_gl_and_total(self, live):
        year = datetime.date.today().year
        acc = live.company.leaf_accounts[0]["name"]
        rows = journal.get_gl(live.company_name, "{}-01-01".format(year), "{}-12-31".format(year), [acc])
        assert isinstance(rows, list)
        total = journal.get_gl_total(live.company_name, "{}-01-01".format(year), "{}-12-31".format(year), [acc])
        assert isinstance(total, (int, float))

    def test_balance(self, live):
        year = datetime.date.today().year
        acc = live.bank_leaf()
        rows = report.balance(live.company_name, [acc], 1, "{}-01-01".format(year), "{}-12-31".format(year))
        assert rows and rows[0]["posting_date"] == "{}-01-01".format(year)
        assert rows[-1]["posting_date"] == "{}-12-31".format(year)

    def test_income_pretax_declaration(self, live, capsys):
        import settings
        import utils
        if live.company_name not in settings.TAX_ACCOUNTS or live.company_name not in settings.INCOME_ACCOUNTS:
            pytest.skip("keine Steuerkonfiguration für {}".format(live.company_name))
        q = utils.last_quarter(datetime.date.today())
        start, end = utils.quarter_to_dates(q)
        inc = journal.income(live.company_name, start, end)
        assert set(inc) == set(settings.INCOME_ACCOUNTS[live.company_name])
        assert isinstance(journal.pretax(live.company_name, start, end), (int, float))
        details = journal.pretax_details(live.company_name, start, end)
        assert all(len(d) == 3 for d in details)
        journal.vat_declaration(live.company_name, q)
        assert "Vorsteuer" in capsys.readouterr().out


class TestTables:
    def test_projects(self, live):
        tbl = report.projects()
        assert tbl.title == "Projekte"
        for e in tbl.entries:
            assert e["Marge"] == pytest.approx(e["Verkauf"] - e["Einkauf"])

    def test_sold_items_of_first_project(self, live, api):
        projects = api.get_list("Project", limit_page_length=1)
        if not projects:
            pytest.skip("keine Projekte")
        items = report.sold_items(projects[0]["name"])
        assert isinstance(items, list)

    def test_opportunities(self, live):
        tbl = report.opportunities(live.company_name)
        assert isinstance(tbl, table.Table)

    def test_balkonmodule_month(self, live, monkeypatch):
        year = datetime.date.today().year
        aggr = report.balkonmodule_month(live.company_name, "{}-01-01".format(year), "{}-01-31".format(year))
        assert all(isinstance(v, float) for v in aggr.values())

    def test_balances_uses_plotly(self, live, monkeypatch):
        import settings
        if live.company_name not in settings.BALANCE_ACCOUNTS:
            pytest.skip("keine BALANCE_ACCOUNTS für {}".format(live.company_name))
        captured = {}

        class Fig:
            def show(self):
                captured["shown"] = True
        monkeypatch.setattr(report.px, "line", lambda data, **kw: captured.update(data=data) or Fig())
        report.balances(live.company_name, settings.BALANCE_ACCOUNTS[live.company_name])
        assert captured["shown"] and captured["data"]
