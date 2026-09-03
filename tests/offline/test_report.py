"""Tests für report.py: Berichtsaufbereitung (Abrechnung, Bilanz, Hauptbuch, Chancen, Projekte)."""
import datetime
import os

import pytest

import report
import table
from api import Api
from settings import PLANNING_ITEM
from support import factories as F


class TestHelpers:
    def test_get_dates(self, user_settings):
        this_year = datetime.date.today().year
        user_settings["-year-"] = this_year
        start, end = report.get_dates()
        assert start == datetime.date(this_year, 1, 1) and end.date() == datetime.date.today()
        user_settings["-year-"] = this_year - 1
        assert report.get_dates()[1].date() == datetime.date.today()
        user_settings["-year-"] = this_year - 2
        assert report.get_dates()[1] == datetime.date(this_year - 2, 12, 31)

    def test_format_float(self):
        assert report.format_float(1234.6) == "1.235"
        assert report.format_float(1234567) == "1.234.567"
        assert report.format_float("Text") == "Text"
        assert report.format_float(0.4) == "0"

    @pytest.mark.parametrize("name, expected", [
        ("'Total Asset (Debit)'", "Summe Vermögenswerte (Aktiva)"),
        ("Aktiva", "Summe Vermögenswerte (Aktiva)"),
        ("Total Liability (Credit)", "Teilsumme Vermögensquellen (Passiva)"),
        ("Provisional Profit / Loss (Credit)", "Überschuss/Defizit"),
        ("Profit for the year", "Überschuss/Defizit"),
        ("Total (Credit)", "Summe Vermögensquellen (Passiva)"),
        ("Total Income (Credit)", "Summe Einnahmen"),
        ("Total Expense (Debit)", "Summe Ausgaben"),
        ("Unclosed Fiscal Years Profit / Loss (Credit)", "Gewinn-/Verlustvortrag"),
        ("4210 - Miete", "4210 - Miete"),
    ])
    def test_format_account(self, name, expected):
        assert report.format_account({"account_name": name})["account_name"] == expected

    def test_format_account_indent_and_truncation(self):
        r = report.format_account({"account_name": "X" * 50, "indent": 2.0})
        assert r["account_name"] == "      " + "X" * 33
        assert len(r["account_name"]) == 39

    def test_remove_dup(self):
        cols = [{"fieldname": "a"}, {"fieldname": "b"}, {"fieldname": "c"}]
        rep = {"result": [{"account_name": "x", "a": 1, "b": 2, "c": 1}, {"account_name": "y", "a": 3, "b": 4, "c": 3},
                          {"a": 9, "b": 9, "c": 0}]}   # Zeile ohne account_name zählt nicht
        assert report.remove_dup(cols, rep) == {"fieldname": "c"}
        rep["result"][0]["c"] = 5
        assert report.remove_dup(cols, rep) is None

    def test_is_relevant(self):
        assert report.is_relevant({"account_name": "Total Asset (Debit)", "t": 5}, ["t"]) is False
        assert report.is_relevant({"account_name": "a", "t": 0.4, "indent": 1}, ["t"]) is False
        assert report.is_relevant({"account_name": "a", "t": 0.6, "indent": 1}, ["t"]) is True
        assert report.is_relevant({"account_name": "a", "t": "x", "indent": 1}, ["t"]) is True
        assert report.is_relevant({"account_name": "a", "t": 0, "indent": 0}, ["t"]) is True
        assert report.is_relevant({"account_name": "a", "t": 0}, ["t"]) is True


class TestTree:
    ROWS = [
        {"account_name": "Income", "indent": 0, "t": 0},
        {"account_name": "8401", "indent": 1, "t": 100},
        {"account_name": "8403", "indent": 1, "t": 50},
        {"account_name": "Expense", "indent": 0, "t": 0},
        {"account_name": "Rent", "indent": 1, "t": 0},
        {"account_name": "4210", "indent": 2, "t": 30},
    ]

    def test_build_tree(self):
        tr = report.build_tree(self.ROWS)
        assert [c.name for c in tr.children] == ["Income", "Expense"]
        income, expense = tr.children
        assert [c.name for c in income.children] == ["8401", "8403"]
        assert [c.name for c in expense.children] == ["Rent"]
        assert [c.name for c in expense.children[0].children] == ["4210"]
        assert income.children[0].is_leaf and not income.is_leaf

    def test_build_sums(self):
        tr = report.build_tree(self.ROWS)
        report.build_sums(tr, ["t"])
        income, expense = tr.children
        assert income.data["t"] == 150 and expense.data["t"] == 30
        assert expense.children[0].data["t"] == 30
        assert "data" not in tr.__dict__ or tr.name == "root"

    def test_build_tree_without_indent(self):
        tr = report.build_tree([{"account_name": "a"}, {"account_name": "b"}])
        assert [c.name for c in tr.children] == ["a", "b"]


def pl_report(filters):
    return {"columns": [{"fieldname": "account", "label": "Account"}, {"fieldname": "currency", "label": "Currency"},
                        {"fieldname": "total", "label": "Total (EUR)"}, {"fieldname": "leer", "label": "Leer"}],
            "result": [
                {"account_name": "Income", "account": "Income - SoMiKo", "indent": 0, "total": 0, "leer": 0},
                {"account_name": "8401 - Selbstbauanlagen 19%", "account": "8401 - Selbstbauanlagen 19% - SoMiKo",
                 "indent": 1, "total": 1000.0, "leer": 0},
                {"account_name": "Total Income (Credit)", "account": None, "total": 1000.0, "leer": 0},
                {"account_name": "Expense", "account": "Expense - SoMiKo", "indent": 0, "total": 0, "leer": 0},
                {"account_name": "4210 - Miete", "account": "4210 - Miete - SoMiKo", "indent": 1, "total": 400.0, "leer": 0},
                {"account_name": "4985 - Werkzeug", "account": "4985 - Werkzeug - SoMiKo", "indent": 1, "total": 0.2, "leer": 0},
                {"account_name": "Total Expense (Debit)", "account": None, "total": 400.0, "leer": 0},
                {"account_name": "Profit for the year", "account": None, "total": 600.0, "leer": 0},
                {"total": 0, "leer": 0},  # Trennzeile ohne account_name
            ]}


class TestBuildReport:
    def test_profit_and_loss(self, somiko, fake_api, user_settings):
        user_settings["-year-"] = 2024
        fake_api.set_report("Profit and Loss Statement", pl_report)
        tbl = report.build_report(somiko.name, periodicity="Quarterly")
        assert isinstance(tbl, table.Table)
        assert tbl.title.startswith("Quartalsabrechnung Bremer SolidarStrom  01.01.2024 - 31.12.2024")
        assert tbl.filename == "Quartalsabrechnung_Bremer_SolidarStrom_2024-01-01.pdf"
        assert tbl.headings == ["Einnahmen/Ausgaben", "Total (EUR"]      # Null-Spalte 'Leer' entfernt
        names = [e["account_name"].strip() for e in tbl.entries]
        assert names == ["8401 - Selbstbauanlagen 19%", "Income", "Summe Einnahmen", "4210 - Miete", "Expense",
                         "Summe Ausgaben", "Überschuss/Defizit"]         # 4985 (rundet auf 0) fällt weg
        bold = {e["account_name"].strip(): e.get("bold") for e in tbl.entries}
        assert bold["Income"] == 3 and bold["8401 - Selbstbauanlagen 19%"] is None
        filters = fake_api.calls_of("query_report")[0][1][1]
        assert filters["company"] == somiko.name and filters["periodicity"] == "Quarterly"
        assert filters["period_start_date"] == "2024-01-01" and filters["period_end_date"] == "2024-12-31"
        assert filters["report"] == "Profit and Loss Statement"
        assert fake_api.calls_of("query_report")[0][1][0] == "Profit and Loss Statement"

    def test_consolidated_removes_duplicate_columns(self, somiko, fake_api, user_settings):
        user_settings["-year-"] = 2024

        def cons(filters):
            rep = pl_report(filters)
            rep["columns"] += [{"fieldname": "dup", "label": "Doppelt"}]
            for r in rep["result"]:
                r["dup"] = r["total"]
            return rep
        fake_api.set_report("Consolidated Financial Statement", cons)
        tbl = report.build_report(somiko.name, consolidated=True)
        assert tbl.title.startswith("Abrechnung Bremer SolidarStrom")
        assert tbl.headings == ["Einnahmen/Ausgaben", "Total (EUR"]
        call = fake_api.calls_of("query_report")[0]
        assert "periodicity" not in call[1][1]
        assert call[2]["ignore_prepared_report"] is True      # sonst nur im Hintergrund erstellt (Frappe 14)

    def test_report_without_data_returns_none(self, somiko, fake_api, capsys):
        fake_api.set_report("Profit and Loss Statement", {"prepared_report": True, "doc": {}})
        assert report.build_report(somiko.name) is None
        assert "liefert keine Daten" in capsys.readouterr().out
        fake_api.set_report("Balance Sheet", lambda f: (_ for _ in ()).throw(RuntimeError("weg")))
        assert report.build_report(somiko.name, balance=True) is None

    def test_default_periodicity(self, somiko, fake_api, user_settings):
        fake_api.set_report("Profit and Loss Statement", pl_report)
        tbl = report.build_report(somiko.name, periodicity=None, filename="x.pdf")
        assert tbl.title.startswith("Abrechnung ")
        assert tbl.filename == "x.pdf"

    def test_balance_sheet_swaps_negative_advances(self, somiko, fake_api, user_settings):
        user_settings["-year-"] = 2024

        def bs(filters):
            return {"columns": [{"fieldname": "account", "label": "Account"}, {"fieldname": "currency", "label": "C"},
                                {"fieldname": "dec_2024", "label": "Dec 2024"}],
                    "result": [
                        {"account_name": "Aktiva", "indent": 0, "dec_2024": 100.0, "total": 100.0},
                        {"account_name": "1400 - Forderungen", "indent": 1, "dec_2024": -50.0, "total": -50.0},
                        {"account_name": "Bank", "indent": 1, "dec_2024": 150.0, "total": 150.0},
                        {"account_name": "Passiva", "indent": 0, "dec_2024": 80.0, "total": 80.0},
                        {"account_name": "1600 - Verbindlichkeiten", "indent": 1, "dec_2024": 80.0, "total": 80.0},
                        {"account_name": "Provisional Profit / Loss (Credit)", "indent": 0, "dec_2024": 20.0, "total": 20.0},
                        {"account_name": "Total (Credit)", "indent": 0, "dec_2024": 0, "total": 0},
                    ]}
        fake_api.set_report("Balance Sheet", bs)
        tbl = report.build_report(somiko.name, balance=True)
        assert tbl.title.startswith("Bilanz Bremer SolidarStrom")
        assert tbl.headings == ["Bilanz", "Dec 2024", "Total"]
        rows = {e["account_name"].strip(): e for e in tbl.entries}
        assert rows["Anzahlungen Verkauf"]["total"] == 50.0       # negative Forderung wandert auf die Passivseite
        assert rows["1400 - Forderungen"]["total"] == 0
        assert rows["Summe Vermögenswerte (Aktiva)"]["total"] == 150.0   # 'Aktiva' umbenannt, Summe der Kinder
        assert rows["Passiva"]["total"] == 50.0
        assert rows["Summe Vermögensquellen (Passiva)"]["total"] == 70.0   # Passiva + Überschuss
        assert fake_api.calls_of("query_report")[0][1][1]["report"] == "Balance Sheet"


class TestGeneralLedgerHelpers:
    def test_format_GL(self):
        assert report.format_GL({"account": "'Opening'", "remarks": "No Remarks"}) == \
            {"account": "Eröffnung", "remarks": "", "bold": 3}
        assert report.format_GL({"account": "'Total'"})["account"] == "Total"
        assert report.format_GL({"account": "'Closing (Opening + Total)'"})["account"] == "Abschluss (Eröffnung + Total)"
        assert report.format_GL({"account": "Bank", "remarks": "x"}) == {"account": "Bank", "remarks": "x"}

    def test_is_relevat_GL(self):
        assert report.is_relevat_GL({"debit": 0, "credit": 0, "balance": 0}) is True
        assert report.is_relevat_GL({"debit": 1}) is False

    def test_keep_first(self):
        data = [{"account": "'Opening'"}, {"account": "a"}, {"account": "'Opening'"}, {"account": "b"}]
        assert report.keep_first(data, ["'Opening'"]) == [{"account": "'Opening'"}, {"account": "a"}, {"account": "b"}]

    def test_format_gl(self):
        gle = report.format_gl({"account": "'Opening'", "remarks": "Keine Anmerkungen", "against": "4210 - Miete - X"})
        assert gle["posting_date"] == "Eröffnung" and gle["bold"] == 3 and gle["account"] == ""
        assert gle["remarks"] == "4210 - Miete - X" and gle["against"] == "4210 "
        gle = report.format_gl({"account": "'Total'", "remarks": "x" * 100})
        assert gle["posting_date"] == "Total" and len(gle["remarks"]) == 70
        assert report.format_gl({"account": "'Closing (Opening + Total)'"})["posting_date"] == "Abschluss"
        assert report.format_gl({"account": "1234 - Konto - X", "remarks": "r"})["account"] == "1234 "
        assert report.format_gl({"remarks": ""})["remarks"] is None

    def test_general_ledger_account(self, somiko, fake_api):
        rows = [{"account": "'Opening'", "debit": 0, "credit": 0, "balance": 10.0, "remarks": "No Remarks"},
                {"account": "Bank - SoMiKo", "debit": 5.0, "credit": 0, "balance": 15.0, "posting_date": "2026-02-01",
                 "against": "4210 - Miete - SoMiKo", "remarks": "Miete", "voucher_no": "JV-1"},
                {"account": "'Opening'", "debit": 0, "credit": 0, "balance": 0},      # Doppelung wird entfernt
                {"account": "'Total'", "debit": 5.0, "credit": 0, "balance": 5.0},
                {"account": "'Closing (Opening + Total)'", "debit": 0, "credit": 0, "balance": 15.0},
                {"kein": "Hauptbucheintrag"}]
        fake_api.set_report("General ledger", {"result": rows, "columns": []})
        tbl = report.general_ledger_account(somiko.name, "Bank - SoMiKo")
        assert tbl.title == "Hauptbuch für Bank - SoMiKo"
        assert [e["account"] for e in tbl.entries] == ["Eröffnung", "Bank - SoMiKo", "Total", "Abschluss (Eröffnung + Total)"]
        assert tbl.entries[0]["remarks"] == "" and tbl.entries[0]["bold"] == 3
        assert tbl.headings[0] == "Datum" and tbl.keys[0] == "posting_date"
        filters = fake_api.calls_of("query_report")[0][1][1]
        assert filters["account"] == ["Bank - SoMiKo"] and filters["company"] == somiko.name


class TestKontenblaetter:
    def test_general_ledger_exports_pdf_per_active_account(self, somiko, fake_api, monkeypatch, user_settings, tmp_path):
        user_settings["-year-"] = 2024

        def gl(filters):
            acc = filters["account"][0]
            if acc == "Bank - SoMiKo":
                rows = [{"account": "'Opening'", "balance": 10.0, "debit": 0, "credit": 0, "posting_date": "2024-01-01"},
                        {"account": acc, "balance": 20.0, "debit": 10.0, "credit": 0, "posting_date": "2024-02-01",
                         "voucher_no": "JV-1", "against": "4210 - X", "remarks": "Miete"},
                        {"account": "'Total'", "balance": 10.0, "debit": 10.0, "credit": 0},
                        {"account": "'Closing (Opening + Total)'", "balance": 20.0, "debit": 0, "credit": 0}]
            else:
                rows = [{"account": "'Opening'", "balance": 0, "debit": 0, "credit": 0},
                        {"account": "'Total'", "balance": 0, "debit": 0, "credit": 0},
                        {"account": "'Closing (Opening + Total)'", "balance": 0, "debit": 0, "credit": 0}]
            return {"result": rows, "columns": []}
        fake_api.set_report("General ledger", gl)
        monkeypatch.setattr(report.tempfile, "mkdtemp", lambda: str(tmp_path))
        commands = []
        monkeypatch.setattr(report.os, "system", lambda cmd: commands.append(cmd))
        report.general_ledger(somiko.name)
        pdfs = sorted(f for f in os.listdir(tmp_path) if f.endswith(".pdf"))
        assert pdfs == ["000.pdf"]
        assert (tmp_path / "000.pdf").read_bytes().startswith(b"%PDF")
        assert commands == ["pdftk {}/* cat output Kontenblätter-Bremer-SolidarStrom-2024.pdf".format(tmp_path)]


class TestOpportunities:
    def test_format_opp(self):
        opp = {"selbstbau": 1, "mit_speicher": 0, "global_margin": 0, "soliaufschlag": 5, "title": "  " + "x" * 30,
               "none": None, "other": 3}
        out = report.format_opp(opp)
        assert out["selbstbau"] == "✓" and out["mit_speicher"] == ""     # Leerzeichen wird anschließend gestript
        assert out["global_margin"] == "" and out["soliaufschlag"] == 5
        assert out["title"] == "x" * 23 and out["none"] == "" and out["other"] == 3

    def _seed(self, fake_api, comp):
        fake_api.add("Opportunity", name="OPP-1", company=comp, status="Open", nur_balkonmodul=0, title="Meier",
                     transaction_date="2026-01-05", selbstbau=1)
        fake_api.add("Opportunity", name="OPP-2", company=comp, status="Cancelled", nur_balkonmodul=0, title="weg",
                     transaction_date="2026-01-06")
        fake_api.add("Quotation", name="QTN-1", company=comp, status="Open", opportunity="OPP-1", global_margin=10,
                     soliaufschlag=5, kostenvoranschlag=1, elektriker=0, ballastierung=1, title="Meier",
                     transaction_date="2026-01-07")
        fake_api.add("Quotation", name="QTN-2", company=comp, status="Open", opportunity=None, global_margin=0,
                     soliaufschlag=0, kostenvoranschlag=0, elektriker=0, ballastierung=0, title="Ohne Chance",
                     transaction_date="2026-01-08")
        fake_api.add("Sales Order", name="SO-1", company=comp, status="To Deliver", title="Meier", customer_name="Meier",
                     transaction_date="2026-01-09", items=[{"prevdoc_docname": "QTN-1"}])
        fake_api.add("Sales Order", name="SO-2", company=comp, status="Draft", title="{customer_name}",
                     customer_name="Schulz", transaction_date="2026-01-10", items=[{"prevdoc_docname": None}])
        fake_api.add("Sales Invoice", name="R-1", company=comp, status="Paid", balkonmodul=0, title="Meier",
                     posting_date="2026-01-11", items=[{"sales_order": "SO-1"}])
        fake_api.add("Sales Invoice", name="R-2", company=comp, status="Draft", balkonmodul=0, title="Direkt",
                     posting_date="2026-01-12", items=[{"sales_order": None}])
        fake_api.add("Sales Invoice", name="R-3", company=comp, status="Paid", balkonmodul=1, title="Balkon",
                     posting_date="2026-01-13", items=[])

    def test_opportunities_data_links_documents(self, somiko, fake_api):
        self._seed(fake_api, somiko.name)
        opps = report.opportunities_data(somiko.name)
        assert set(opps) == {"OPP-1", "QTN-2", "SO-2", "R-2"}
        o = opps["OPP-1"]
        assert o["quotation"] == "QTN-1" and o["global_margin"] == 10 and o["ballastierung"] == 1
        assert o["sales_order"] == "SO-1*"           # nicht Draft -> Stern
        assert o["sales_invoice"] == "R-1*" and o["is_paid"] is True
        assert opps["QTN-2"]["title"] == "Ohne Chance?A"
        assert opps["SO-2"]["title"] == "Schulz?AB" and opps["SO-2"]["sales_order"] == "SO-2"
        assert opps["R-2"]["title"] == "Direkt?R" and opps["R-2"]["transaction_date"] == "2026-01-12"

    def test_opportunities_data_balkon(self, somiko, fake_api):
        self._seed(fake_api, somiko.name)
        opps = report.opportunities_data(somiko.name, balkon=1)
        assert set(opps) == {"R-3"}
        assert opps["R-3"]["sales_invoice"] == "R-3*" and opps["R-3"]["is_paid"] is True

    def test_opportunities_table(self, somiko, fake_api):
        self._seed(fake_api, somiko.name)
        tbl = report.opportunities(somiko.name)
        assert tbl.title == "Chancen für " + somiko.name
        assert [e["transaction_date"] for e in tbl.entries] == ["2026-01-12", "2026-01-10", "2026-01-08", "2026-01-05"]
        assert tbl.headings[:3] == ["Titel", "Datum", "Soli"] and tbl.headings[-2:] == ["Rechnung", "bez."]
        tbl_b = report.opportunities(somiko.name, balkon=1)
        assert tbl_b.headings == ["Titel", "Datum", "Soli", "Rechnung", "bez."]


class TestProjects:
    def test_projects_table(self, fake_api):
        fake_api.add("Project", name="PROJ-1", project_name="A", creation="2026-01-01", status="Open", project_type="Solaranlage")
        fake_api.add("Project", name="PROJ-2", project_name="B", creation="2026-02-01", status="Completed", project_type="Balkonmodule")
        fake_api.add("Sales Invoice", name="R-1", project="PROJ-1", status="Paid", total=1000.0,
                     items=[{"item_code": PLANNING_ITEM, "amount": 150.0}, {"item_code": "X", "amount": 850.0}])
        fake_api.add("Sales Invoice", name="R-2", project="PROJ-1", status="Cancelled", total=99.0, items=[])
        fake_api.add("Purchase Invoice", name="EK-1", project="PROJ-1", status="Paid", total=600.0)
        tbl = report.projects()
        assert tbl.title == "Projekte" and tbl.just == "right"
        rows = {e["Name"]: e for e in tbl.entries}
        assert rows["PROJ-1"] == {"Name": "PROJ-1", "Datum": "2026-01-01", "Titel": "A", "Typ": "Solaranlage",
                                  "Status": "Open", "Einkauf": 600.0, "Verkauf": 1000.0, "Marge": 400.0, "Planung": 150.0}
        assert rows["PROJ-2"]["Einkauf"] == 0 and rows["PROJ-2"]["Planung"] == 0
        assert [e["Name"] for e in tbl.entries] == ["PROJ-1", "PROJ-2"]   # status DESC, creation DESC


class TestBalancesAndBalkon:
    def test_balance_adapts_and_sets_dates(self, fake_api):
        rows = [{"account": "'Opening'", "balance": 10.0, "posting_date": "x"},
                {"account": "Bank - X", "balance": 20.0, "posting_date": "2024-02-01"},
                {"account": "'Total'", "balance": 30.0},
                {"account": "'Closing'", "balance": 30.0, "posting_date": "y"}]
        fake_api.set_report("General ledger", {"result": rows})
        r = report.balance("F", ["Bank - X"], -1, "2024-01-01", "2024-12-31")
        assert [(e["posting_date"], e["balance"]) for e in r] == [("2024-01-01", -10.0), ("2024-02-01", -20.0),
                                                                  ("2024-12-31", -30.0)]

    def test_balances_plots(self, fake_api, user_settings, monkeypatch):
        fake_api.set_report("General ledger", {"result": [{"account": "'Opening'", "balance": 1.0, "posting_date": "a"},
                                                          {"account": "'Closing'", "balance": 1.0, "posting_date": "b"}]})
        figs = []

        class Fig:
            def show(self):
                figs.append("shown")
        monkeypatch.setattr(report.px, "line", lambda data, **kw: (figs.append((data, kw)), Fig())[1])
        report.balances("F", {"Bank": (["Bank - X"], 1), "Lager": (["I. Vorräte - X"], -1)})
        data, kw = figs[0]
        assert {e["Bilanzposten"] for e in data} == {"Bank", "Lager"}
        assert kw["color"] == "Bilanzposten" and figs[-1] == "shown"

    def _items(self):
        Api.items_by_code = {
            "B1": {"item_code": "B1", "item_name": "Balkon-Anlage 2x400"},
            "B2": {"item_code": "B2", "item_name": "Balkon Paket klein"},
            "G": {"item_code": "G", "item_name": "Grundkosten"},
            "S": {"item_code": "S", "item_name": "Soli-Preis"},
            "X": {"item_code": "X", "item_name": "Sonstiges"},
        }

    def test_balkonmodule_month(self, fake_api):
        self._items()
        fake_api.add("Sales Invoice", name="R-1", company="F", balkonmodul=1, posting_date="2026-03-05", status="Paid",
                     items=[{"item_code": "B1", "qty": 2}, {"item_code": "G", "qty": 2}, {"item_code": "X", "qty": 1}])
        fake_api.add("Sales Invoice", name="R-2", company="F", balkonmodul=1, posting_date="2026-03-20", status="Paid",
                     items=[{"item_code": "B2", "qty": 1}, {"item_code": "S", "qty": 3}])
        fake_api.add("Sales Invoice", name="R-3", company="F", balkonmodul=1, posting_date="2026-04-01", status="Paid",
                     items=[{"item_code": "B2", "qty": 5}])
        aggr = report.balkonmodule_month("F", "2026-03-01", "2026-03-31")
        assert dict(aggr) == {"Balkonmodule": 5.0, "Grundkosten": 2.0, "Soli-Preis": 3.0}

    def test_balkonmodule_plot(self, fake_api, user_settings, monkeypatch):
        self._items()
        user_settings["-year-"] = 2024
        fake_api.add("Sales Invoice", name="R-1", company="F", balkonmodul=1, posting_date="2024-02-05", status="Paid",
                     items=[{"item_code": "B1", "qty": 1}])
        captured = {}

        class Fig:
            def show(self):
                captured["shown"] = True
        monkeypatch.setattr(report.px, "line", lambda data, **kw: captured.update(data=data) or Fig())
        report.balkonmodule("F")
        assert captured["shown"] and captured["data"] == [{"Datum": "2024-02-01", "Wert": "Balkonmodule", "Anzahl": 2.0}]

    def test_balkonmodule_csv(self, fake_api, in_tmp_cwd, capsys):
        fake_api.add("Project", name="PROJ-B", project_type="Balkonmodule", status="Open")
        fake_api.add("Item", item_code="B1", item_name="Balkon-Anlage")
        fake_api.add("Item", item_code="A1", item_name="Adapter")
        fake_api.add("Sales Invoice", name="R-1", company="F", project="PROJ-B", status="Paid",
                     items=[{"item_code": "B1", "qty": 2}, {"item_code": "A1", "qty": 1}])
        fake_api.add("Sales Invoice", name="R-2", company="F", project="PROJ-B", status="Paid", items=[{"item_code": "B1", "qty": 1}])
        report.balkonmodule_csv("F")
        text = (in_tmp_cwd / "balkon.csv").read_text()
        assert text.splitlines()[0] == '"item_name","item_code","qty"'
        assert '"Adapter","A1",1' in text and '"Balkon-Anlage","B1",3' in text
        assert "Projekt PROJ-B" in capsys.readouterr().out

    def test_sold_items(self, fake_api):
        self._items()
        fake_api.add("Sales Invoice", name="R-1", project="P", status="Paid", items=[{"item_code": "G", "qty": 2}])
        fake_api.add("Sales Invoice", name="R-2", project="P", status="Cancelled", items=[{"item_code": "G", "qty": 9}])
        assert report.sold_items("P") == [{"item_name": "Grundkosten", "item_code": "G", "qty": 2}]
