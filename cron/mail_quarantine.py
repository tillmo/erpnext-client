"""Move mails that would stall the ERPNext mail pull out of the inbox.

Frappe 14 breaks off the whole pull when a mail embeds an image (``<img src="data:...">``)
that Pillow cannot decode ("Truncated File Read"), and every later mail stays unread until the
mail is removed from the inbox by hand. This script looks at the new mails in the inbox before
Frappe does, opens every embedded image with the same Pillow, and moves a mail with a broken
image to the folder IMAP_FOLDER (default "Fehlerhaft"). Nothing else is touched; the mails are
read with BODY.PEEK, so their flags stay as they are.

Environment: IMAP_HOST, IMAP_USER, IMAP_PASSWORD, IMAP_FOLDER, LAST_UID ("<uidvalidity>:<uid>"
of the last checked mail, from the state file kept by cron/mail_quarantine.sh). Prints one log
line per moved mail and finally "STATE <uidvalidity>:<uid>". Runs inside the ERPNext backend
container (same Pillow as Frappe), see cron/mail_quarantine.sh.
"""
from __future__ import annotations

import base64
import binascii
import datetime
import email
import email.header
import imaplib
import io
import os
import re
import sys
from email.message import Message
from typing import Iterable

DATA_IMAGE = re.compile(r'<img[^>]*src\s*=\s*["\']data:(image/[a-z+.-]+);base64,([^"\']+)["\']', re.IGNORECASE)


def decode_header(value: str | None) -> str:
    parts = []
    for text, charset in email.header.decode_header(value or ''):
        parts.append(text.decode(charset or 'utf-8', 'replace') if isinstance(text, bytes) else text)
    return ' '.join(' '.join(parts).split())


def embedded_images(msg: Message) -> Iterable[tuple[str, bytes]]:
    """(content type, bytes) of every data: image in the HTML parts of the mail."""
    for part in msg.walk():
        if part.get_content_type() != 'text/html':
            continue
        payload = part.get_payload(decode=True) or b''
        html = payload.decode(part.get_content_charset() or 'utf-8', 'replace')
        for m in DATA_IMAGE.finditer(html):
            try:
                yield m.group(1).lower(), base64.b64decode(m.group(2), validate=False)
            except (binascii.Error, ValueError):
                yield m.group(1).lower(), b''


def broken_images(msg: Message) -> list[str]:
    """Reasons why Frappe would fail on this mail: one per embedded image Pillow cannot read."""
    from PIL import Image
    reasons = []
    for content_type, data in embedded_images(msg):
        if content_type == 'image/svg+xml':
            continue
        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except Exception as e:                       # what frappe.utils.image.optimize_image hits
            reasons.append('{} ({} bytes): {}'.format(content_type, len(data), str(e)[:80] or type(e).__name__))
    return reasons


def log(text: str) -> None:
    print(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), text, flush=True)


def ensure_folder(imap: imaplib.IMAP4, folder: str) -> None:
    status, boxes = imap.list()
    for line in boxes or []:
        if line and re.search(r'"?%s"?$' % re.escape(folder), line.decode('utf-8', 'replace')):
            return
    imap.create(folder)
    log('Ordner {} angelegt'.format(folder))


def main() -> int:
    host, user, password = os.environ['IMAP_HOST'], os.environ['IMAP_USER'], os.environ['IMAP_PASSWORD']
    folder = os.environ.get('IMAP_FOLDER') or 'Fehlerhaft'
    last = os.environ.get('LAST_UID') or ''
    imap = imaplib.IMAP4_SSL(host, int(os.environ.get('IMAP_PORT') or 993))
    imap.login(user, password)
    imap.select('INBOX')
    validity = (imap.response('UIDVALIDITY')[1] or [b''])[0]
    validity = (validity or b'').decode()
    last_validity, _, last_uid = last.partition(':')
    if last_validity == validity and last_uid.isdigit():
        status, data = imap.uid('search', None, 'UID', '{}:*'.format(int(last_uid) + 1))
    else:                                            # first run or mailbox renumbered: the last two days
        since = (datetime.date.today() - datetime.timedelta(days=2)).strftime('%d-%b-%Y')
        status, data = imap.uid('search', None, 'SINCE', since)
    uids = [u for u in (data[0] or b'').split() if not (last_uid.isdigit() and int(u) <= int(last_uid))]
    moved = 0
    highest = int(last_uid) if last_uid.isdigit() and last_validity == validity else 0
    for uid in uids:
        status, parts = imap.uid('fetch', uid, '(BODY.PEEK[])')
        raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
        if raw is None:
            continue
        msg = email.message_from_bytes(raw)
        reasons = broken_images(msg)
        if reasons:
            ensure_folder(imap, folder)
            imap.uid('copy', uid, folder)
            imap.uid('store', uid, '+FLAGS', r'(\Deleted)')
            imap.expunge()
            moved += 1
            log('nach {} verschoben: UID {} | {} | {} | {} | {}'.format(
                folder, uid.decode(), decode_header(msg.get('Date')), decode_header(msg.get('From')),
                decode_header(msg.get('Subject'))[:80], '; '.join(reasons)))
        highest = max(highest, int(uid))
    imap.logout()
    if uids or moved:
        log('{} neue Mails geprüft, {} verschoben'.format(len(uids), moved))
    print('STATE {}:{}'.format(validity, highest), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
