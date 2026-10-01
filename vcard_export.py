"""Export the vCards of assigned leads into Nextcloud address books (CardDAV).

Every lead owner gets an address book on the Nextcloud server (name from
``settings.NEXTCLOUD_ADDRESSBOOK``). The phones subscribe to it via CardDAV (DAVx5 on Android,
CardDAV on iOS), so a lead assigned in the client appears in the address book without any import.
Unlike the vCard attached to the lead in ERPNext, a lead is exported as soon as it is assigned,
even when name, phone number or address are still missing: the owner can then call and complete
the data later. The card carries the lead id as its UID, so a later export replaces it instead of
creating a duplicate, and ``CATEGORIES:ERPNext Lead`` marks the cards this export manages.

Credentials: Nextcloud URL, user and app password from the client settings ("Einstellungen -
Nextcloud") or from NEXTCLOUD_URL, NEXTCLOUD_USER and NEXTCLOUD_PASSWORD. The address books
belong to that user and have to be shared with the lead owners in Nextcloud once.

Usage (also from cron):
    python3 vcard_export.py --server URL --key KEY --secret SECRET
                            [--owner Chris] [--apply] [--create] [--delete]

Without --apply nothing is written (dry run). --create creates a missing address book, --delete
removes the cards of leads that are no longer assigned.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote

from gui import sg
import lead_contact
import settings
from api import Api, LIMIT

DAV_NS = 'DAV:'
CARDDAV_NS = 'urn:ietf:params:xml:ns:carddav'
CATEGORY = 'ERPNext Lead'                                  # marks the cards managed here
DNC = 'Do Not Contact'
# properties that a server may add or rewrite: they must not count as a change
IGNORED_PROPERTIES = ('BEGIN', 'END', 'VERSION', 'PRODID', 'REV')
REPORT_BODY = ('<?xml version="1.0" encoding="utf-8"?>\n'
               '<C:addressbook-query xmlns:D="{}" xmlns:C="{}">'
               '<D:prop><D:getetag/><C:address-data/></D:prop>'
               '</C:addressbook-query>').format(DAV_NS, CARDDAV_NS)
MKCOL_BODY = ('<?xml version="1.0" encoding="utf-8"?>\n'
              '<D:mkcol xmlns:D="{}" xmlns:C="{}"><D:set><D:prop>'
              '<D:resourcetype><D:collection/><C:addressbook/></D:resourcetype>'
              '<D:displayname>{{}}</D:displayname>'
              '</D:prop></D:set></D:mkcol>').format(DAV_NS, CARDDAV_NS)


def credentials() -> tuple[str | None, str | None, str | None]:
    """Nextcloud URL, user and app password from the client settings or the environment."""
    url = user = password = None
    try:
        s = sg.UserSettings()         # headless (cron): holds nothing, the environment decides
        url, user, password = s.get('-nextcloud-url-'), s.get('-nextcloud-user-'), s.get('-nextcloud-password-')
    except Exception:
        pass
    return (url or os.environ.get('NEXTCLOUD_URL') or None,
            user or os.environ.get('NEXTCLOUD_USER') or None,
            password or os.environ.get('NEXTCLOUD_PASSWORD') or None)


def configured() -> bool:
    return all(credentials())


def addressbook_of(owner: str) -> str:
    return settings.NEXTCLOUD_ADDRESSBOOK.format(owner=re.sub(r'[^a-z0-9]+', '-', owner.lower()).strip('-'))


# ---------------------------------------------------------------- vCards
def card_properties(body: str) -> set[str]:
    """The lines of a vCard that carry data, for comparing two cards."""
    lines = set()
    for line in body.replace('\r\n', '\n').split('\n'):
        line = line.strip()
        if line and line.split(':', 1)[0].split(';')[0].upper() not in IGNORED_PROPERTIES:
            lines.add(line)
    return lines


def same_card(a: str, b: str) -> bool:
    return card_properties(a) == card_properties(b)


def uid_of(body: str) -> str | None:
    m = re.search(r'^UID:(.*)$', body.replace('\r\n', '\n'), re.MULTILINE)
    return m.group(1).strip() if m else None


def is_managed(body: str) -> bool:
    """True for cards created by this export (recognised by their category)."""
    return any(line.upper().startswith('CATEGORIES') and CATEGORY in line for line in card_properties(body))


def lead_vcard(doc: dict[str, Any], address: dict[str, Any] | None, base_url: str) -> str:
    contact = lead_contact.from_lead(doc, address)
    note = 'ERPNext Lead {} ({})'.format(doc['name'], doc.get('status') or '')
    return lead_contact.vcard(doc['name'], contact, '{}/app/lead/{}'.format(base_url, doc['name']),
                              categories=CATEGORY, note=note)


def card_filename(lead: str) -> str:
    return re.sub(r'[^\w.-]+', '_', lead) + '.vcf'


# ---------------------------------------------------------------- CardDAV
class CardDav:
    """The few CardDAV requests needed here, against a Nextcloud server."""

    def __init__(self, url: str, user: str, password: str, session: Any = None) -> None:
        self.base: str = url.rstrip('/')
        self.user: str = user
        self.auth: tuple[str, str] = (user, password)
        if session is None:
            import requests
            session = requests.Session()
        self.session: Any = session

    def addressbook_url(self, book: str) -> str:
        return '{}/remote.php/dav/addressbooks/users/{}/{}/'.format(self.base, quote(self.user), quote(book))

    def request(self, method: str, url: str, body: str | None = None, headers: dict[str, str] | None = None) -> Any:
        return self.session.request(method, url, data=body.encode('utf-8') if body else None,
                                    headers=headers or {}, auth=self.auth, timeout=60)

    def exists(self, book: str) -> bool:
        r = self.request('PROPFIND', self.addressbook_url(book), headers={'Depth': '0'})
        if r.status_code in (207, 200):
            return True
        if r.status_code == 404:
            return False
        raise RuntimeError('Nextcloud antwortete auf PROPFIND mit {}'.format(r.status_code))

    def create(self, book: str, display_name: str) -> None:
        r = self.request('MKCOL', self.addressbook_url(book), body=MKCOL_BODY.format(display_name),
                         headers={'Content-Type': 'application/xml; charset=utf-8'})
        if r.status_code not in (201, 200):
            raise RuntimeError('Adressbuch {} konnte nicht angelegt werden (HTTP {})'.format(book, r.status_code))

    def cards(self, book: str) -> dict[str, str]:
        """href -> vCard body of all cards in the address book."""
        r = self.request('REPORT', self.addressbook_url(book), body=REPORT_BODY,
                         headers={'Depth': '1', 'Content-Type': 'application/xml; charset=utf-8'})
        if r.status_code not in (207, 200):
            raise RuntimeError('Nextcloud antwortete auf REPORT mit {}'.format(r.status_code))
        result: dict[str, str] = {}
        for response in ET.fromstring(r.text).findall('{%s}response' % DAV_NS):
            href = response.findtext('{%s}href' % DAV_NS) or ''
            data = response.find('.//{%s}address-data' % CARDDAV_NS)
            if href and data is not None and (data.text or '').strip():
                result[unquote(href)] = data.text or ''
        return result

    def put(self, book: str, filename: str, body: str) -> None:
        r = self.request('PUT', self.addressbook_url(book) + quote(filename), body=body,
                         headers={'Content-Type': 'text/vcard; charset=utf-8'})
        if r.status_code not in (200, 201, 204):
            raise RuntimeError('{} konnte nicht geschrieben werden (HTTP {})'.format(filename, r.status_code))

    def delete(self, href: str) -> None:
        r = self.request('DELETE', '{}{}'.format(self.base, quote(href)))
        if r.status_code not in (200, 204, 404):
            raise RuntimeError('{} konnte nicht gelöscht werden (HTTP {})'.format(href, r.status_code))


# ---------------------------------------------------------------- ERPNext
LEAD_FIELDS = ['name', 'status', 'lead_name', 'first_name', 'last_name', 'email_id', 'mobile_no', 'phone',
               'city', '_assign', 'creation']


def owner_user_id(owner: str) -> str | None:
    rows = Api.api.get_list('User', filters={'first_name': owner}, fields=['name'], limit_page_length=1)
    return rows[0]['name'] if rows else None


def assigned_leads(user_id: str) -> list[dict[str, Any]]:
    """The leads assigned to this user, without those marked "Do Not Contact"."""
    leads = Api.api.get_list('Lead', filters={'_assign': ['like', '%{}%'.format(user_id)], 'status': ['!=', DNC]},
                             fields=LEAD_FIELDS, order_by='creation desc', limit_page_length=LIMIT)
    result = []
    for l in leads:
        try:
            assigned = json.loads(l.get('_assign') or '[]')
        except ValueError:
            assigned = []
        if user_id in assigned:                 # the like filter may match a substring
            result.append(l)
    return result


def addresses_for(names: list[str]) -> dict[str, dict[str, Any]]:
    """Lead -> its linked address (one query per 15 leads, the URL length is limited)."""
    result: dict[str, dict[str, Any]] = {}
    for i in range(0, len(names), 15):
        rows = Api.api.get_list('Address', filters=[['Dynamic Link', 'link_doctype', '=', 'Lead'],
                                                    ['Dynamic Link', 'link_name', 'in', names[i:i + 15]]],
                                fields=['name', 'address_line1', 'pincode', 'city', 'country',
                                        '`tabDynamic Link`.link_name as lead'], limit_page_length=LIMIT)
        for r in rows:
            result.setdefault(r['lead'], r)
    return result


# ---------------------------------------------------------------- export
@dataclass
class Result:
    owner: str
    book: str
    leads: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    obsolete: int = 0
    errors: int = 0
    missing_book: bool = False
    unknown_owner: bool = False


def export_owner(dav: CardDav, owner: str, apply: bool = False, create: bool = False,
                 delete: bool = False) -> Result:
    """Export the leads assigned to one owner into their address book."""
    book = addressbook_of(owner)
    result = Result(owner, book)
    user_id = owner_user_id(owner)
    if not user_id:
        print('  {}: kein ERPNext-Benutzer mit diesem Vornamen'.format(owner))
        result.unknown_owner = True
        return result
    leads = assigned_leads(user_id)
    result.leads = len(leads)
    addresses = addresses_for([l['name'] for l in leads])
    wanted = {l['name']: lead_vcard(l, addresses.get(l['name']), Api.api.url) for l in leads}
    if not dav.exists(book):
        if not (create and apply):
            print('  {}: Adressbuch {} fehlt{}'.format(owner, book, ' (mit --create anlegen)' if apply else ''))
            result.missing_book = True
            return result
        dav.create(book, 'ERPNext-Leads {}'.format(owner))
        print('  {}: Adressbuch {} angelegt, bitte in Nextcloud für {} freigeben'.format(owner, book, owner))
    on_server = dav.cards(book)
    managed = {uid_of(body): (href, body) for href, body in on_server.items() if is_managed(body)}
    for lead, body in wanted.items():
        href_body = managed.get(lead)
        if href_body and same_card(href_body[1], body):
            result.unchanged += 1
            continue
        try:
            if apply:
                dav.put(book, card_filename(lead), body)
            if href_body:
                result.updated += 1
            else:
                result.created += 1
        except RuntimeError as e:
            result.errors += 1
            print('  {}: {}'.format(owner, e))
    for lead, (href, _body) in sorted(managed.items(), key=lambda kv: str(kv[0])):
        if lead in wanted:
            continue
        result.obsolete += 1
        if not (delete and apply):
            continue
        try:
            dav.delete(href)
            result.deleted += 1
        except RuntimeError as e:
            result.errors += 1
            print('  {}: {}'.format(owner, e))
    return result


def describe(result: Result, delete: bool = False) -> str:
    """One line per lead owner, empty when there was nothing to do."""
    if result.unknown_owner or result.missing_book:
        return ''
    parts = ['{} Leads'.format(result.leads), '{} neu'.format(result.created),
             '{} geändert'.format(result.updated), '{} unverändert'.format(result.unchanged)]
    if result.obsolete:
        parts.append('{} verwaist{}'.format(result.obsolete,
                                            ' (gelöscht)' if result.deleted else '' if delete else ' (mit --delete entfernen)'))
    if result.errors:
        parts.append('{} Fehler'.format(result.errors))
    return '  {} -> {}: {}'.format(result.owner, result.book, ', '.join(parts))


def export(owners: list[str], apply: bool = False, create: bool = False, delete: bool = False,
           dav: CardDav | None = None) -> list[Result]:
    """Export for several lead owners. Without credentials it only prints a hint."""
    if dav is None:
        url, user, password = credentials()
        if not (url and user and password):
            print('Kein Nextcloud-Zugang hinterlegt (Einstellungen - Nextcloud), vCard-Export übersprungen')
            return []
        dav = CardDav(url, user, password)
    print('vCard-Export nach {}{}'.format(dav.base, '' if apply else ' (nur Bericht)'))
    results = []
    for owner in owners:
        try:
            result = export_owner(dav, owner, apply, create, delete)
        except (RuntimeError, OSError) as e:
            print('  {}: FEHLER {}'.format(owner, str(e)[:200]))
            results.append(Result(owner, addressbook_of(owner), errors=1))
            continue
        results.append(result)
        line = describe(result, delete)
        if line:
            print(line)
    return results


def export_all(apply: bool = True, create: bool = False, delete: bool = False) -> list[Result]:
    """Menu and lead processing: export for all lead owners from the settings."""
    return export(list(settings.LEAD_OWNERS), apply, create, delete)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--server', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--secret', required=True)
    parser.add_argument('--owner', action='append', help='nur dieser Lead Owner (mehrfach möglich)')
    parser.add_argument('--nextcloud-url', help='z. B. https://cloud.example (sonst aus Einstellungen/Umgebung)')
    parser.add_argument('--nextcloud-user')
    parser.add_argument('--nextcloud-password', help='App-Passwort')
    parser.add_argument('--apply', action='store_true', help='tatsächlich schreiben (sonst nur berichten)')
    parser.add_argument('--create', action='store_true', help='fehlendes Adressbuch anlegen')
    parser.add_argument('--delete', action='store_true', help='verwaiste Karten entfernen')
    args = parser.parse_args(argv)
    from frappeclient import FrappeClient
    Api.api = FrappeClient(args.server, api_key=args.key, api_secret=args.secret)
    url, user, password = credentials()
    url, user, password = args.nextcloud_url or url, args.nextcloud_user or user, args.nextcloud_password or password
    if not (url and user and password):
        print('Nextcloud-Zugang fehlt: --nextcloud-url/--nextcloud-user/--nextcloud-password '
              'oder NEXTCLOUD_URL/_USER/_PASSWORD setzen')
        return 2
    results = export(args.owner or list(settings.LEAD_OWNERS), args.apply, args.create, args.delete,
                     CardDav(url, user, password))
    errors = sum(r.errors for r in results) + sum(1 for r in results if r.missing_book or r.unknown_owner)
    written = sum(r.created + r.updated for r in results)
    print('\n{} Karten {}, {} gelöscht, {} Probleme'.format(
        written, 'geschrieben' if args.apply else 'zu schreiben', sum(r.deleted for r in results), errors))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
