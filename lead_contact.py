"""Contact data of real leads: name, phone numbers and address from the first e-mail.

``extract`` reads the data from the mail text (web form labels such as "Name:", "Telefon:",
otherwise sender name, phone number patterns and a street line followed by "PLZ Ort" in the
signature). ``complete_lead`` shows the values in an editable dialog, fills only the empty lead
fields, creates a linked Address if none exists, and attaches a vCard (.vcf) to the lead as a
private file so that the lead owners can add the contact to their phone from the ERPNext app.
"""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, fields as dataclass_fields
from typing import Any

import easygui
import PySimpleGUI as sg

import lead_rules
import settings
from api import Api, LIMIT
from frappeclient import FrappeException

GOOD_STATUSES = ('Converted', 'Replied', 'Quotation', 'Opportunity', 'Lost Quotation', 'Lead', 'Interested')
COUNTRY = 'Germany'

# web form labels -> contact key
LABELS: dict[str, str] = {
    'name': 'name', 'ihr name': 'name', 'vor- und nachname': 'name', 'vor- und zuname': 'name', 'kontakt': 'name',
    'vorname': 'first_name', 'nachname': 'last_name', 'familienname': 'last_name', 'zuname': 'last_name',
    'telefon': 'phone_any', 'tel': 'phone_any', 'tel.': 'phone_any', 'telefonnummer': 'phone_any', 'rufnummer': 'phone_any',
    'telefon / mobil': 'phone_any', 'phone': 'phone_any', 'handy': 'mobile_no', 'mobil': 'mobile_no',
    'mobile': 'mobile_no', 'mobilnummer': 'mobile_no', 'handynummer': 'mobile_no',
    'adresse': 'address', 'anschrift': 'address', 'straße': 'street', 'strasse': 'street', 'str.': 'street',
    'straße und hausnummer': 'street', 'straße / hausnummer': 'street', 'plz': 'pincode', 'postleitzahl': 'pincode',
    'ort': 'city', 'stadt': 'city', 'wohnort': 'city', 'plz / ort': 'pincode_city', 'plz und ort': 'pincode_city',
    'plz, ort': 'pincode_city', 'e-mail': 'email', 'email': 'email', 'mail': 'email', 'e-mail-adresse': 'email',
}
_LABEL_LINE = re.compile(r'^\s*\*?([A-Za-zÄÖÜäöüß./,\- ]{2,28}?)\*?\s*[:：]\s*(.*?)\s*$')
_PHONE = re.compile(r'(?<![\w+])(?:\+\s?49|0049|0)[\d\s/().\-]{6,}\d')
_DATE = re.compile(r'\d{1,2}\.\d{1,2}\.\d{2,4}')
_PLZ_CITY = re.compile(r'^\s*(?:D\s?-\s?)?(\d{5})\s+([A-ZÄÖÜ][\wäöüß\-./ ]{1,40}?)\s*,?\s*$')
_STREET = re.compile(r'^\s*([A-ZÄÖÜ][\wäöüß.\-\' ]{2,50}?)\s+(\d{1,4}\s?[a-zA-Z]?(?:\s?[-/]\s?\d{1,4}\s?[a-zA-Z]?)?)\s*,?\s*$')
_INLINE_ADDRESS = re.compile(r'^(.*?\d{1,4}\s?[a-zA-Z]?)\s*,\s*(?:D\s?-\s?)?(\d{5})\s+([A-ZÄÖÜ][\wäöüß\-./ ]{1,40}?)\s*$')
# start of a quoted earlier mail ("Von:"/"From:" alone is not used: web forms send such lines as fields)
_QUOTE_START = re.compile(r'^\s*(Am .{6,80} schrieb .*:?|On .{6,80} wrote:|-{2,}\s*(Ursprüngliche|Original|Weitergeleitete) ?(Nachricht|Message).*)\s*$', re.I)
_TITLES = {'herr', 'frau', 'hr.', 'fr.', 'dr.', 'dr', 'prof.', 'prof', 'dipl.-ing.', 'familie', 'fam.'}
_SKIP_ADDRESS_WORDS = ('solidarstrom', 'solidarische ökonomie')
_GREETING = re.compile(r'(grüße|grüsse|gruß|gruss|freundlich|herzlich|^\s*(mfg|lg|vg)\b|beste grüße|liebe grüße)', re.I)
_NAME_LINE = re.compile(r'^\s*((?:[A-ZÄÖÜ][\wäöüß\-\'.]+\s+){1,3}[A-ZÄÖÜ][\wäöüß\-\']+)\s*$')


@dataclass
class Contact:
    first_name: str = ''
    last_name: str = ''
    mobile_no: str = ''
    phone: str = ''
    street: str = ''
    pincode: str = ''
    city: str = ''
    email: str = ''

    def empty(self) -> bool:
        return not any(getattr(self, f.name) for f in dataclass_fields(self))

    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p)

    def merged_with(self, existing: Contact) -> Contact:
        """Existing (manually entered) values win; extracted values fill the gaps."""
        return Contact(**{f.name: getattr(existing, f.name) or getattr(self, f.name) for f in dataclass_fields(self)})


# ---------------------------------------------------------------- extraction
def normalize_phone(raw: str) -> str:
    """'+49 (0)421 / 12 34 56' -> '+49 421 123456'; '' if it does not look like a phone number."""
    if _DATE.search(raw):
        return ''
    s = re.sub(r'\(0\)', '', raw)
    digits = re.sub(r'\D', '', s)
    if s.strip().startswith('+'):
        digits = digits          # already international
    elif digits.startswith('0049'):
        digits = digits[2:]
    elif digits.startswith('0'):
        digits = '49' + digits[1:]
    else:
        return ''
    if not 9 <= len(digits) <= 15:
        return ''
    national = digits[2:]
    if national.startswith(('15', '16', '17')):
        return '+49 ' + national[:3] + ' ' + national[3:]
    for length in (2, 3, 4, 5):          # area code: greedy would be wrong, but we only need readability
        if len(national) > length + 3:
            if length == 2 and national[0] in '3489' and national[:2] in ('30', '40', '69', '89'):
                return '+49 ' + national[:2] + ' ' + national[2:]
            if length == 3 and national[:3] in ('221', '211', '231', '201', '241', '421', '431', '511', '521', '531', '551',
                                                 '561', '611', '621', '631', '641', '681', '711', '721', '761', '821',
                                                 '841', '911', '921', '931', '941', '951'):
                return '+49 ' + national[:3] + ' ' + national[3:]
    return '+49 ' + national[:4] + ' ' + national[4:]


def is_mobile(number: str) -> bool:
    return bool(re.match(r'\+49 1[567]', number))


def phones_in(text: str) -> list[str]:
    seen: list[str] = []
    for m in _PHONE.finditer(text):
        n = normalize_phone(m.group(0))
        if n and n not in seen:
            seen.append(n)
    return seen


def split_name(name: str) -> tuple[str, str]:
    name = re.sub(r'\s+', ' ', name).strip().strip('"\'')
    if not name or '@' in name:
        return '', ''
    if ',' in name:                              # "Muster, Max"
        last, first = [p.strip() for p in name.split(',', 1)]
        return first, last
    parts = [p for p in name.split(' ') if p.lower() not in _TITLES]
    if not parts:
        return '', ''
    if len(parts) == 1:
        return '', parts[0]
    return " ".join(parts[:-1]), parts[-1]


def _lines(text: str) -> list[str]:
    """Lines of the mail without quoted earlier mails (they carry our own signature and numbers)."""
    lines = []
    for line in (text or '').replace('\r', '').split('\n'):
        if _QUOTE_START.match(line):
            break
        if line.lstrip().startswith('>'):
            continue
        lines.append(line.rstrip())
    return lines


def _form_fields(lines: list[str]) -> dict[str, str]:
    """'Label: value' lines (value may follow on the next line, as in web form mails)."""
    found: dict[str, str] = {}
    for i, line in enumerate(lines):
        m = _LABEL_LINE.match(line)
        if not m:
            continue
        label = m.group(1).strip().lower().rstrip('*').strip()
        key = LABELS.get(label)
        if not key:
            continue
        value = m.group(2).strip()
        if not value:
            for nxt in lines[i + 1:i + 3]:
                if nxt.strip():
                    if not (_LABEL_LINE.match(nxt) and LABELS.get(_LABEL_LINE.match(nxt).group(1).strip().lower())):  # type: ignore[union-attr]
                        value = nxt.strip()
                    break
        if value and key not in found:
            found[key] = value
    return found


def _signature_name(lines: list[str]) -> str:
    """Name in the lines after a closing greeting ("Viele Grüße", "Mit freundlichen Grüßen", ...)."""
    for i, line in enumerate(lines):
        if _GREETING.search(line) and len(line) < 60:
            for nxt in lines[i + 1:i + 3]:
                if not nxt.strip():
                    continue
                m = _NAME_LINE.match(nxt)
                if m and not any(w in nxt.lower() for w in _SKIP_ADDRESS_WORDS):
                    return m.group(1)
                break
    return ''


def _address_from_lines(lines: list[str]) -> tuple[str, str, str]:
    """First street line followed by a 'PLZ Ort' line (or both in one line); ('', '', '') if none."""
    def ours(window: list[str]) -> bool:
        return any(w in l.lower() for l in window for w in _SKIP_ADDRESS_WORDS)

    for i, line in enumerate(lines):
        if ours(lines[max(0, i - 3):i + 1]):
            continue
        m = _INLINE_ADDRESS.match(line.strip())
        if m and _STREET.match(m.group(1).strip()):
            return m.group(1).strip().rstrip(','), m.group(2), m.group(3).strip()
        m = _PLZ_CITY.match(line)
        if m:
            for prev in reversed(lines[max(0, i - 2):i]):
                if not prev.strip():
                    continue
                s = _STREET.match(prev.split(',')[-1] if ',' in prev and _STREET.match(prev.split(',')[-1].strip()) else prev)
                if s:
                    return f"{s.group(1).strip()} {s.group(2).strip()}", m.group(1), m.group(2).strip()
                break
    return '', '', ''


def extract(text: str, sender_name: str | None = None, sender: str | None = None) -> Contact:
    """Contact data from a mail text (plain text, see utils.html_to_text)."""
    c = Contact()
    lines = _lines(text)
    form = _form_fields(lines)
    # name
    name = form.get('name', '')
    if form.get('first_name') or form.get('last_name'):
        c.first_name, c.last_name = form.get('first_name', ''), form.get('last_name', '')
        if not c.last_name and c.first_name:
            c.first_name, c.last_name = split_name(c.first_name)
    elif name:
        c.first_name, c.last_name = split_name(name)
    elif sender_name and not any(w in sender_name.lower() for w in _SKIP_ADDRESS_WORDS) and '@' not in sender_name:
        c.first_name, c.last_name = split_name(sender_name)
    else:
        c.first_name, c.last_name = split_name(_signature_name(lines))
    # phones
    for key in ('mobile_no', 'phone_any'):
        for n in phones_in(form.get(key, '')):
            if is_mobile(n) and not c.mobile_no:
                c.mobile_no = n
            elif not is_mobile(n) and not c.phone:
                c.phone = n
    for n in phones_in("\n".join(lines)):          # signature: whatever kind is still missing
        if is_mobile(n) and not c.mobile_no:
            c.mobile_no = n
        elif not is_mobile(n) and not c.phone and n != c.mobile_no:
            c.phone = n
    # address
    if form.get('address'):
        street, plz, city = _address_from_lines(form['address'].replace(',', '\n').split('\n')) \
            if '\n' in form['address'].replace(',', '\n') else ('', '', '')
        m = _INLINE_ADDRESS.match(form['address'])
        if m:
            street, plz, city = m.group(1).strip().rstrip(','), m.group(2), m.group(3).strip()
        c.street, c.pincode, c.city = street, plz, city
    if form.get('street'):
        c.street = form['street']
    if form.get('pincode_city'):
        m = _PLZ_CITY.match(form['pincode_city'])
        if m:
            c.pincode, c.city = m.group(1), m.group(2).strip()
    if form.get('pincode') and re.fullmatch(r'\d{5}', form['pincode'].strip()):
        c.pincode = form['pincode'].strip()
    if form.get('city'):
        c.city = form['city']
    if not (c.street and c.city):
        street, plz, city = _address_from_lines(lines)
        c.street, c.pincode, c.city = c.street or street, c.pincode or plz, c.city or city
    # e-mail
    c.email = lead_rules.address_of(form.get('email')) or lead_rules.address_of(sender) or ''
    if c.email and any(c.email.endswith('@' + d) for d in settings.OWN_DOMAINS):
        c.email = ''
    return c


def received_mails(comms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Received mails, oldest first."""
    received = [c for c in comms if c.get('sent_or_received', 'Received') == 'Received']
    return sorted(received, key=lambda c: c.get('creation') or c.get('communication_date') or '')


def extract_from_mails(comms: list[dict[str, Any]], fallback_sender: str | None = None) -> tuple[Contact, str]:
    """Contact data from all received mails (the first mail wins, later mails fill gaps) and the text of the first mail."""
    import utils
    contact = Contact()
    first_text = ''
    for i, mail in enumerate(received_mails(comms)):
        text = utils.html_to_text(mail.get('content') or '')
        if i == 0:
            first_text = text
        found = extract(text, mail.get('sender_full_name'), mail.get('sender') or fallback_sender)
        contact = found.merged_with(contact)
    return contact, first_text


def _is_name(value: str | None) -> bool:
    return bool(value) and '@' not in (value or '')


# ---------------------------------------------------------------- ERPNext
def from_lead(doc: dict[str, Any], address: dict[str, Any] | None) -> Contact:
    """The contact data already stored at the lead (names that are just the e-mail address count as empty)."""
    first = doc.get('first_name') or '' if _is_name(doc.get('first_name')) else ''
    last = doc.get('last_name') or '' if _is_name(doc.get('last_name')) else ''
    if not (first or last) and _is_name(doc.get('lead_name')):
        first, last = split_name(doc['lead_name'])
    return Contact(first_name=first, last_name=last, mobile_no=doc.get('mobile_no') or '', phone=doc.get('phone') or '',
                   street=(address or {}).get('address_line1') or '', pincode=(address or {}).get('pincode') or '',
                   city=(address or {}).get('city') or doc.get('city') or '', email=doc.get('email_id') or '')


def linked_address(name: str) -> dict[str, Any] | None:
    rows = Api.api.get_list('Address', filters=[['Dynamic Link', 'link_doctype', '=', 'Lead'],
                                                ['Dynamic Link', 'link_name', '=', name]],
                            fields=['name', 'address_line1', 'pincode', 'city', 'country'], limit_page_length=1)
    return rows[0] if rows else None


def apply_contact(name: str, contact: Contact) -> list[str]:
    """Fill the empty lead fields and create a linked Address if there is none. Returns the changed fields."""
    doc = Api.api.get_doc('Lead', name)
    changed: list[str] = []
    for field, value in (('first_name', contact.first_name), ('last_name', contact.last_name),
                         ('mobile_no', contact.mobile_no), ('phone', contact.phone), ('city', contact.city)):
        current = doc.get(field)
        if field in ('first_name', 'last_name') and not _is_name(current):
            current = None                      # ERPNext fills the name with the e-mail address
        if value and not current:
            doc[field] = value
            changed.append(field)
    full = contact.full_name()
    if full and not _is_name(doc.get('lead_name')):
        doc['lead_name'] = full                 # ERPNext recomputes it from first/last name anyway
        changed.append('lead_name')
    if changed:
        Api.api.update(doc)
    if contact.street and contact.city and not linked_address(name):
        Api.api.insert({'doctype': 'Address', 'address_title': full or doc.get('lead_name') or name,
                        'address_type': 'Personal', 'address_line1': contact.street, 'pincode': contact.pincode,
                        'city': contact.city, 'country': COUNTRY, 'email_id': contact.email or None,
                        'phone': contact.mobile_no or contact.phone or None,
                        'links': [{'link_doctype': 'Lead', 'link_name': name, 'link_title': doc.get('lead_name') or name}]})
        changed.append('address')
    return changed


def _vcard_escape(s: str) -> str:
    return s.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def vcard(name: str, contact: Contact, url: str) -> str:
    """vCard 3.0 for the phone; UID is the lead name so that a re-export replaces the contact."""
    e = _vcard_escape
    lines = ['BEGIN:VCARD', 'VERSION:3.0', f'UID:{e(name)}',
             f'N:{e(contact.last_name)};{e(contact.first_name)};;;', f'FN:{e(contact.full_name() or name)}']
    if contact.mobile_no:
        lines.append(f'TEL;TYPE=CELL:{contact.mobile_no}')
    if contact.phone:
        lines.append(f'TEL;TYPE=HOME,VOICE:{contact.phone}')
    if contact.email:
        lines.append(f'EMAIL;TYPE=INTERNET:{contact.email}')
    if contact.street or contact.city:
        lines.append(f'ADR;TYPE=HOME:;;{e(contact.street)};{e(contact.city)};;{e(contact.pincode)};{e(COUNTRY)}')
    lines += [f'URL:{url}', f'NOTE:{e("ERPNext Lead " + name)}', 'END:VCARD']
    return "\r\n".join(lines) + "\r\n"


def attach_vcard(name: str, contact: Contact) -> str:
    """Attach the vCard privately to the lead, replacing an earlier one. Returns the file name."""
    filename = re.sub(r'[^\w.-]+', '_', name) + '.vcf'
    for f in Api.api.get_list('File', filters={'attached_to_doctype': 'Lead', 'attached_to_name': name,
                                                'file_name': filename}, fields=['name'], limit_page_length=10):
        Api.api.delete('File', f['name'])
    url = f"{Api.api.url}/app/lead/{name}"
    Api.api.attach_file('Lead', name, filename, vcard(name, contact, url).encode('utf-8'), is_private=True)
    return filename


def add_comment(name: str, text: str) -> None:
    try:
        Api.api.insert({'doctype': 'Comment', 'comment_type': 'Comment', 'reference_doctype': 'Lead',
                        'reference_name': name, 'content': text})
    except FrappeException as e:
        print(f"Hinweis: Kommentar an {name} nicht möglich: {str(e).splitlines()[-1][:120]}")


MAX_EXCERPT_LINES = 25


def excerpt(text: str, max_lines: int = MAX_EXCERPT_LINES, width: int = 90) -> str:
    """At most ``max_lines`` display lines of a mail text (long lines are wrapped and count), '…' if cut."""
    out: list[str] = []
    for line in (text or '').split('\n'):
        for piece in (textwrap.wrap(line, width) or ['']):
            if len(out) >= max_lines:
                return "\n".join(out) + "\n…"
            out.append(piece)
    return "\n".join(out)


FIELDS = [('first_name', 'Vorname'), ('last_name', 'Nachname'), ('mobile_no', 'Handy'), ('phone', 'Telefon'),
          ('street', 'Straße und Hausnummer'), ('pincode', 'PLZ'), ('city', 'Ort'), ('email', 'E-Mail')]


def visible_text(text: str) -> str:
    """The mail without quoted earlier mails, for display."""
    return "\n".join(_lines(text)).strip("\n")


def _dialog(msg: str, title: str, fields: list[str], values: list[str]) -> list[str] | None:
    """Wide PySimpleGUI window: heading, scrollable mail excerpt, one input per field. None if cancelled."""
    head, _, text = msg.partition("\n\n")
    keys = [f'-field{i}-' for i in range(len(fields))]
    layout: list[list[Any]] = [[sg.Text(head)],
                               [sg.Multiline(text, size=(110, 18), disabled=True, autoscroll=False)]]
    for label, value, key in zip(fields, values, keys):
        layout.append([sg.Text(label, size=(22, 1)), sg.Input(default_text=value, key=key, size=(60, 1))])
    layout.append([sg.Button('OK', bind_return_key=True), sg.Button('Abbrechen')])
    window = sg.Window(title, layout, finalize=True)
    event, vals = window.read()
    window.close()
    if event != 'OK':
        return None
    return [vals[k] or '' for k in keys]


def edit_contact(contact: Contact, title: str, msg: str) -> Contact | None:
    """Editable dialog with the extracted values; None if cancelled."""
    values = _dialog(msg, title, [label for _, label in FIELDS], [getattr(contact, f) for f, _ in FIELDS])
    if values is None:
        return None
    result = Contact(**{f: (v or '').strip() for (f, _), v in zip(FIELDS, values)})
    for key in ('mobile_no', 'phone'):
        raw = getattr(result, key)
        if raw:
            setattr(result, key, normalize_phone(raw) or raw)
    return result


def complete_lead(name: str, doc: dict[str, Any], comms: list[dict[str, Any]], ask: bool = True) -> bool:
    """Extract, confirm, store and attach the vCard. Returns False if the user cancelled."""
    extracted, text = extract_from_mails(comms, doc.get('email_id'))
    if not extracted.email:
        extracted.email = lead_rules.address_of(doc.get('email_id'))
    contact = extracted.merged_with(from_lead(doc, linked_address(name)))
    if ask:
        msg = f"{name}   {doc.get('lead_name') or ''}\nKontaktdaten prüfen und ergänzen:\n\n{excerpt(visible_text(text), 80, 110)}"
        edited = edit_contact(contact, f"Kontaktdaten für {name}", msg)
        if edited is None:
            print(f"Kontaktdaten für {name} übersprungen")
            return False
        contact = edited
    changed = apply_contact(name, contact)
    filename = attach_vcard(name, contact)
    if changed:
        add_comment(name, "Kontaktdaten aus der E-Mail übernommen: " + ", ".join(changed))
    print(f"{name}: {', '.join(changed) if changed else 'keine neuen Felder'}; vCard {filename} angehängt")
    return True


def complete_leads() -> None:
    """Menu: vCards for complete leads, then contact data (and vCards) for real leads without a phone number."""
    attach_missing_vcards()
    todo = [l for l in real_leads() if not (l.get('mobile_no') or l.get('phone'))]
    print(f"{len(todo)} Leads ohne Telefonnummer")
    done = 0
    for l in todo:
        res = Api.api.load_doc('Lead', l['name'])
        if not complete_lead(l['name'], res['docs'][0], res['docinfo']['communications']):
            if not easygui.ynbox(f"{len(todo) - done} Leads verbleiben. Weiter?", "Kontaktdaten nachtragen"):
                break
            continue
        done += 1
    print(f"Kontaktdaten für {done} Leads nachgetragen")


def real_leads() -> list[dict[str, Any]]:
    """Leads that are (or were) treated as real leads, newest first."""
    leads = Api.api.get_list('Lead', fields=['name', 'status', 'lead_name', 'first_name', 'last_name', 'email_id', 'mobile_no',
                                             'phone', 'city', '_assign', 'creation'],
                             filters={'status': ['!=', 'Do Not Contact']}, order_by='creation desc', limit_page_length=LIMIT)
    return [l for l in leads if l['status'] in GOOD_STATUSES or l['_assign'] not in (None, '', '[]')]


def is_complete(contact: Contact) -> bool:
    return bool(contact.last_name and (contact.mobile_no or contact.phone) and contact.street and contact.city)


def leads_with_vcard() -> set[str]:
    files = Api.api.get_list('File', filters={'attached_to_doctype': 'Lead', 'file_name': ['like', '%.vcf']},
                             fields=['attached_to_name'], limit_page_length=LIMIT)
    return {f['attached_to_name'] for f in files}


def attach_missing_vcards() -> int:
    """vCards for all real leads with complete contact data that have none yet. Returns the number attached."""
    have = leads_with_vcard()
    count = 0
    for l in real_leads():
        if l['name'] in have or not (l.get('last_name') and (l.get('mobile_no') or l.get('phone'))):
            continue
        contact = from_lead(l, linked_address(l['name']))
        if is_complete(contact):
            attach_vcard(l['name'], contact)
            count += 1
    if count:
        print(f"{count} vCards für Leads mit vollständigen Kontaktdaten angehängt")
    return count
