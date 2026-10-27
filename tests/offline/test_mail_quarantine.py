"""Tests for cron/mail_quarantine.py (mails with broken embedded images)."""
from __future__ import annotations

import base64
import io
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cron"))
PIL = pytest.importorskip("PIL")
import mail_quarantine as mq  # noqa: E402


def jpeg_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, format="JPEG")
    return buf.getvalue()


def mail(html: str, subject: str = "Test") -> EmailMessage:
    m = EmailMessage()
    m["Subject"] = subject
    m["From"] = "a@example.org"
    m.set_content("Textfassung")
    m.add_alternative(html, subtype="html")
    return m


def test_intact_image_passes() -> None:
    data = base64.b64encode(jpeg_bytes()).decode()
    assert mq.broken_images(mail('<p>Hallo</p><img src="data:image/jpeg;base64,%s">' % data)) == []
    assert mq.broken_images(mail("<p>kein Bild</p>")) == []


def test_truncated_image_is_reported() -> None:
    data = base64.b64encode(jpeg_bytes()[:40]).decode()           # cut inside the header, as in the real case
    reasons = mq.broken_images(mail("<img src='data:image/jpeg;base64,%s' alt=''>" % data))
    assert len(reasons) == 1 and reasons[0].startswith("image/jpeg (40 bytes)")
    garbage = mq.broken_images(mail('<img src="data:image/png;base64,QUJD">'))
    assert len(garbage) == 1 and garbage[0].startswith("image/png")


def test_svg_and_decode_header() -> None:
    assert mq.broken_images(mail('<img src="data:image/svg+xml;base64,PHN2Zy8+">')) == []
    assert mq.decode_header("=?utf-8?q?Aw=3A_Balkonkraftwerk?=") == "Aw: Balkonkraftwerk"
    assert mq.decode_header(None) == ""
