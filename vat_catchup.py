"""Catch up the missing VAT transfers to 1780 (SKR03), pre-2024 amounts via 1791.

Per SKR03 the input VAT accounts (1571, 1576, 1577) and the output VAT accounts (1771, 1776,
1787) are transferred to 1780 "Umsatzsteuer-Vorauszahlung" at the end of every declaration
period; the payment or refund from the tax office then clears 1780. On this installation that
transfer stopped in 2023, so the VAT accounts carry balances of several years.

The periods before 2024 cannot be reconstructed quarter by quarter: a catch-up transfer in the
first quarter of 2023 already mixed periods, and the advance payments on 1718 shifted VAT across
the year boundary (the annual declarations confirm this). The fiscal years up to 2023 are also
closed by Period Closing Vouchers. This script therefore

- transfers every quarter from 2024 on to 1780, dated at the end of that quarter, and
- transfers everything before 2024 in a single entry dated 2024-01-01 to 1791 "Umsatzsteuer
  frühere Jahre", where the tax advisor reconciles it against the tax office's account.

Afterwards the six VAT accounts are zero and 1780 can be reconciled per quarter against the
bank. What remains on 1780 and 1791 is the reconciliation with the tax advisor.

Usage:
    python3 vat_catchup.py --server URL --key KEY --secret SECRET
                           [--company NAME] [--until 2026-Q2] [--apply] [--submit]

Without --apply nothing is changed (dry run). The script is idempotent: a period whose transfer
entry already exists is skipped.
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from frappeclient import FrappeClient, FrappeException

INPUT_ACCOUNTS = ('1571', '1576', '1577')          # abziehbare Vorsteuer
OUTPUT_ACCOUNTS = ('1771', '1776', '1787')         # Umsatzsteuer
VAT_ACCOUNTS = INPUT_ACCOUNTS + OUTPUT_ACCOUNTS
ADVANCE_ACCOUNT = '1780'                           # Umsatzsteuer-Vorauszahlung
EARLIER_ACCOUNT = '1791'                           # Umsatzsteuer frühere Jahre
FIRST_YEAR = 2024                                  # first year booked quarter by quarter
PRE_PERIOD = 'vor {}'.format(FIRST_YEAR)
TITLE_QUARTER = 'USt-Umbuchung {}'
TITLE_PRE = 'USt-Nachholung Vorjahre bis {}'.format(FIRST_YEAR - 1)
EPS = 0.005


def quarter_of(date: str) -> str:
    return '{}-Q{}'.format(date[:4], (int(date[5:7]) - 1) // 3 + 1)


def quarter_bounds(quarter: str) -> tuple[str, str]:
    """('2024-Q2') -> ('2024-04-01', '2024-06-30')"""
    year, q = quarter.split('-Q')
    start = datetime.date(int(year), int(q) * 3 - 2, 1)
    end = datetime.date(int(year) + (1 if q == '4' else 0), 1 if q == '4' else int(q) * 3 + 1, 1) - datetime.timedelta(days=1)
    return start.isoformat(), end.isoformat()


def last_completed_quarter(today: datetime.date) -> str:
    """The quarter before the one that contains ``today``."""
    q = (today.month - 1) // 3 + 1
    return '{}-Q4'.format(today.year - 1) if q == 1 else '{}-Q{}'.format(today.year, q - 1)


def quarters_until(until: str) -> list[str]:
    result = []
    for year in range(FIRST_YEAR, int(until[:4]) + 1):
        for q in range(1, 5):
            quarter = '{}-Q{}'.format(year, q)
            if quarter <= until:
                result.append(quarter)
    return result


def title_of(period: str) -> str:
    return TITLE_PRE if period == PRE_PERIOD else TITLE_QUARTER.format(period)


def posting_date_of(period: str) -> str:
    return '{}-01-01'.format(FIRST_YEAR) if period == PRE_PERIOD else quarter_bounds(period)[1]


def offset_of(period: str) -> str:
    return EARLIER_ACCOUNT if period == PRE_PERIOD else ADVANCE_ACCOUNT


@dataclass
class Transfer:
    """The transfer of one declaration period for one company."""
    period: str
    amounts: dict[str, float] = field(default_factory=dict)     # account number -> debit minus credit
    existing: str | None = None                                 # already booked entry

    @property
    def net(self) -> float:
        return round(sum(self.amounts.values()), 2)

    def empty(self) -> bool:
        return all(abs(v) < EPS for v in self.amounts.values())


def resolve_accounts(api: FrappeClient, company: str) -> dict[str, str]:
    """Account number -> full account name, for the VAT accounts present in the company."""
    wanted = set(VAT_ACCOUNTS) | {ADVANCE_ACCOUNT, EARLIER_ACCOUNT}
    accounts = api.get_list('Account', filters={'company': company, 'is_group': 0},
                            fields=['name', 'account_number'], limit_page_length=100000)
    return {a['account_number']: a['name'] for a in accounts if a['account_number'] in wanted}


def own_entries(api: FrappeClient, company: str, periods: list[str]) -> dict[str, str]:
    """Period -> name of the transfer entry already booked by this script."""
    titles = {title_of(p): p for p in periods}
    rows = api.get_list('Journal Entry', filters={'company': company, 'title': ['in', sorted(titles)], 'docstatus': ['!=', 2]},
                        fields=['name', 'title'], limit_page_length=1000)
    return {titles[r['title']]: r['name'] for r in rows if r['title'] in titles}


def compute_transfers(api: FrappeClient, company: str, accounts: dict[str, str], until: str) -> tuple[list[Transfer], float]:
    """The transfers per period plus the amount left in periods after ``until`` (still running)."""
    numbers = [n for n in VAT_ACCOUNTS if n in accounts]
    if not numbers:
        return [], 0.0
    periods = [PRE_PERIOD] + quarters_until(until)
    existing = own_entries(api, company, periods)
    skip = set(existing.values())
    entries = api.get_list('GL Entry', filters={'company': company, 'is_cancelled': 0,
                                                'account': ['in', [accounts[n] for n in numbers]]},
                           fields=['account', 'posting_date', 'debit', 'credit', 'voucher_no'],
                           limit_page_length=100000)
    transfers = {p: Transfer(p, {n: 0.0 for n in numbers}, existing.get(p)) for p in periods}
    open_after = 0.0
    for e in entries:
        if e['voucher_no'] in skip:
            continue            # our own transfer entry: not part of the amount to transfer
        number = (e['account'].split(' - ')[0] or '').strip()
        value = (e['debit'] or 0.0) - (e['credit'] or 0.0)
        if e['posting_date'] < '{}-01-01'.format(FIRST_YEAR):
            transfers[PRE_PERIOD].amounts[number] += value
        else:
            quarter = quarter_of(e['posting_date'])
            if quarter in transfers:
                transfers[quarter].amounts[number] += value
            else:
                open_after += value
    for t in transfers.values():
        t.amounts = {n: round(v, 2) for n, v in t.amounts.items()}
    return [transfers[p] for p in periods], round(open_after, 2)


def journal_entry_doc(company: str, transfer: Transfer, accounts: dict[str, str],
                      finance_book: str | None = None) -> dict[str, Any]:
    """The journal entry that clears the VAT accounts of one period against the offset account."""
    lines: list[dict[str, Any]] = []
    for number, amount in sorted(transfer.amounts.items()):
        if abs(amount) < EPS:
            continue
        # a debit balance is cleared by a credit and vice versa
        debit, credit = (0.0, round(amount, 2)) if amount > 0 else (round(-amount, 2), 0.0)
        lines.append({'account': accounts[number], 'debit': debit, 'debit_in_account_currency': debit,
                      'credit': credit, 'credit_in_account_currency': credit})
    net = transfer.net
    if abs(net) >= EPS:
        offset = accounts[offset_of(transfer.period)]
        debit, credit = (net, 0.0) if net > 0 else (0.0, -net)
        lines.append({'account': offset, 'debit': debit, 'debit_in_account_currency': debit,
                      'credit': credit, 'credit_in_account_currency': credit})
    remark = ('Umbuchung der Umsatzsteuerkonten auf {} für {}.'.format(offset_of(transfer.period), transfer.period)
              + ('\nSammelnachholung der Jahre bis {}; die Aufteilung auf Quartale ist aus den Daten nicht '
                 'rekonstruierbar (Sammelumbuchung 2023/Q1, Anzahlungsversteuerung über 1718). '
                 'Abstimmung mit dem Steuerbüro erforderlich.'.format(FIRST_YEAR - 1)
                 if transfer.period == PRE_PERIOD else ''))
    doc: dict[str, Any] = {'doctype': 'Journal Entry', 'voucher_type': 'Journal Entry', 'company': company,
                           'title': title_of(transfer.period), 'posting_date': posting_date_of(transfer.period),
                           'set_posting_time': 1, 'user_remark': remark, 'accounts': lines}
    if finance_book:
        doc['finance_book'] = finance_book
    return doc


def balances(api: FrappeClient, company: str, accounts: dict[str, str]) -> dict[str, float]:
    """Current balance (debit minus credit) per account number."""
    numbers = sorted(accounts)
    entries = api.get_list('GL Entry', filters={'company': company, 'is_cancelled': 0,
                                                'account': ['in', [accounts[n] for n in numbers]]},
                           fields=['account', 'debit', 'credit'], limit_page_length=100000)
    result = {n: 0.0 for n in numbers}
    for e in entries:
        number = (e['account'].split(' - ')[0] or '').strip()
        if number in result:
            result[number] += (e['debit'] or 0.0) - (e['credit'] or 0.0)
    return {n: round(v, 2) for n, v in result.items()}


def report(company: str, transfers: list[Transfer], open_after: float, before: dict[str, float]) -> None:
    numbers = [n for n in VAT_ACCOUNTS if any(n in t.amounts for t in transfers)]
    print('\n=== {}'.format(company))
    print('  Salden vorher: ' + ', '.join('{} {:.2f}'.format(n, before.get(n, 0.0))
                                          for n in sorted(before) if abs(before.get(n, 0.0)) >= EPS))
    header = '  {:14}'.format('Periode') + ''.join('{:>12}'.format(n) for n in numbers) + '{:>12} {:>11}  {}'.format(
        'Gegenkonto', 'Betrag', 'Status')
    print(header)
    for t in transfers:
        if t.empty() and not t.existing:
            continue
        row = '  {:14}'.format(t.period) + ''.join('{:12.2f}'.format(t.amounts.get(n, 0.0)) for n in numbers)
        status = 'schon gebucht ({})'.format(t.existing) if t.existing else 'offen'
        print(row + '{:>12} {:11.2f}  {}'.format(offset_of(t.period), t.net, status))
    todo = [t for t in transfers if not t.existing and not t.empty()]
    print('  {} von {} Perioden offen, Summe {:.2f}'.format(len(todo), len(transfers), sum(t.net for t in todo)))
    if abs(open_after) >= EPS:
        print('  Hinweis: {:.2f} liegen in noch nicht abgeschlossenen Quartalen und bleiben stehen '
              '(mit --until einbeziehen)'.format(open_after))


def process(api: FrappeClient, company: str, until: str, apply: bool, submit: bool) -> tuple[int, int]:
    """Report and, with apply, book the transfers of one company. Returns (booked, errors)."""
    accounts = resolve_accounts(api, company)
    missing = [n for n in (ADVANCE_ACCOUNT, EARLIER_ACCOUNT) if n not in accounts]
    if missing:
        print('\n=== {}: Konten {} fehlen, übersprungen'.format(company, ', '.join(missing)))
        return 0, 1
    transfers, open_after = compute_transfers(api, company, accounts, until)
    if not transfers:
        print('\n=== {}: keine Umsatzsteuerkonten'.format(company))
        return 0, 0
    before = balances(api, company, accounts)
    report(company, transfers, open_after, before)
    todo = [t for t in transfers if not t.existing and not t.empty()]
    if not apply:
        if todo:
            print('  {} Buchungssätze würden angelegt (--apply)'.format(len(todo)))
        return 0, 0
    finance_book = api.get_value('Company', 'default_finance_book', {'name': company}) or {}
    booked = errors = 0
    for t in todo:
        doc = journal_entry_doc(company, t, accounts, finance_book.get('default_finance_book'))
        try:
            je = api.insert(doc)
            if submit:
                api.submit(api.get_doc('Journal Entry', je['name']))
            booked += 1
            print('  {}: {} {} ({:.2f})'.format(t.period, je['name'], 'gebucht' if submit else 'als Entwurf angelegt', t.net))
        except FrappeException as e:
            errors += 1
            print('  {}: FEHLER {}'.format(t.period, str(e).splitlines()[-1][:200]))
    if submit:
        after = balances(api, company, accounts)
        print('  Salden nachher: ' + (', '.join('{} {:.2f}'.format(n, v) for n, v in sorted(after.items()) if abs(v) >= EPS) or 'alle 0'))
        rest = round(sum(v for n, v in after.items() if n in VAT_ACCOUNTS), 2)
        if abs(rest - open_after) >= EPS:
            print('  Achtung: auf den Umsatzsteuerkonten bleiben {:.2f} statt der erwarteten {:.2f} '
                  'aus laufenden Quartalen'.format(rest, open_after))
        elif abs(rest) >= EPS:
            print('  Rest {:.2f} auf den Umsatzsteuerkonten gehört zu noch nicht abgeschlossenen Quartalen'.format(rest))
    return booked, errors


def companies_with_vat(api: FrappeClient) -> list[str]:
    """Companies that have at least one VAT account with a balance."""
    result = []
    for c in api.get_list('Company', fields=['name'], limit_page_length=100):
        accounts = resolve_accounts(api, c['name'])
        numbers = [n for n in VAT_ACCOUNTS if n in accounts]
        if not numbers:
            continue
        bal = balances(api, c['name'], {n: accounts[n] for n in numbers})
        if any(abs(v) >= EPS for v in bal.values()):
            result.append(c['name'])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--server', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--secret', required=True)
    parser.add_argument('--company', action='append', help='nur diese Firma (mehrfach möglich; Standard: alle mit Salden)')
    parser.add_argument('--until', help='letztes einzubeziehendes Quartal, z. B. 2026-Q2 (Standard: letztes abgeschlossenes)')
    parser.add_argument('--apply', action='store_true', help='Buchungssätze anlegen (sonst nur berichten)')
    parser.add_argument('--submit', action='store_true', help='die angelegten Buchungssätze auch buchen')
    args = parser.parse_args(argv)
    until = args.until or last_completed_quarter(datetime.date.today())
    if not re.fullmatch(r'20\d\d-Q[1-4]', until):
        print('--until muss die Form 2026-Q2 haben'); return 2
    api = FrappeClient(args.server, api_key=args.key, api_secret=args.secret)
    companies = args.company or companies_with_vat(api)
    print('Quartale {} bis {}, Vorjahre gesammelt zum {}; Firmen: {}'.format(
        '{}-Q1'.format(FIRST_YEAR), until, posting_date_of(PRE_PERIOD), ', '.join(companies) or 'keine'))
    booked = errors = 0
    for company in companies:
        b, e = process(api, company, until, args.apply, args.submit)
        booked += b
        errors += e
    if args.apply:
        print('\n{} Buchungssätze {}, {} Fehler'.format(booked, 'gebucht' if args.submit else 'als Entwurf angelegt', errors))
        if not args.submit and booked:
            print('Bitte in ERPNext prüfen und buchen (oder mit --submit erneut aufrufen).')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
