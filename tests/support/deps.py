"""Availability of optional dependencies, usable as pytest markers.

The stubs from :mod:`support.stubs` make the project modules importable;
tests that check the real behaviour of a package skip themselves here.
"""
from __future__ import annotations

import shutil
import sys

import pytest


def _real(name: str) -> bool:
    mod = sys.modules.get(name)
    if mod is None:
        try:
            __import__(name)
        except Exception:
            return False
        mod = sys.modules[name]
    return not getattr(mod, "__stub__", False)


HAVE_JSONDIFF = _real("jsondiff")
HAVE_JSONEDITOR = _real("jsoneditor")
HAVE_ANYTREE = _real("anytree")
HAVE_DATEFINDER = _real("datefinder")
HAVE_PLOTLY = _real("plotly")
HAVE_PYPDF = _real("pypdf")
HAVE_PDFTOTEXT = shutil.which("pdftotext") is not None
HAVE_PDFTK = shutil.which("pdftk") is not None

requires_jsondiff = pytest.mark.skipif(not HAVE_JSONDIFF, reason="jsondiff nicht installiert")
requires_jsoneditor = pytest.mark.skipif(not HAVE_JSONEDITOR, reason="jsoneditor nicht installiert")
requires_anytree = pytest.mark.skipif(not HAVE_ANYTREE, reason="anytree nicht installiert (Stub aktiv)")
requires_datefinder = pytest.mark.skipif(not HAVE_DATEFINDER, reason="datefinder nicht installiert")
requires_pdftotext = pytest.mark.skipif(not HAVE_PDFTOTEXT, reason="pdftotext nicht installiert")
requires_pdftk = pytest.mark.skipif(not HAVE_PDFTK, reason="pdftk nicht installiert")


def de_locale_available() -> bool:
    import locale
    try:
        old = locale.setlocale(locale.LC_ALL)
        locale.setlocale(locale.LC_ALL, "de_DE.utf8")
        locale.setlocale(locale.LC_ALL, old)
        return True
    except locale.Error:
        return False


requires_de_locale = pytest.mark.skipif(not de_locale_available(), reason="Locale de_DE.utf8 fehlt")


def skip_module_without_pdftotext() -> None:
    """Call at the start of the module, before purchase_invoice is imported:
    its import runs ``pdftotext -v`` and fails without the program."""
    if not HAVE_PDFTOTEXT:
        pytest.skip("pdftotext nicht installiert", allow_module_level=True)
requires_pypdf = pytest.mark.skipif(not HAVE_PYPDF, reason="pypdf nicht installiert")
