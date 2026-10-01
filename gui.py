"""The GUI toolkit of the client - or a headless stand-in.

FreeSimpleGUI and easygui need tkinter. On a server without it (the cron job that runs
``vcard_export.py``) the client modules must still be importable, so every module takes the
two names from here: the real packages where they are available, otherwise stand-ins whose
``UserSettings`` holds nothing (credentials then come from the command line or the
environment) and whose dialogs raise ``HeadlessError``.
"""
from __future__ import annotations

from typing import Any

sg: Any
easygui: Any

try:
    import FreeSimpleGUI as _sg
    import easygui as _easygui
    sg, easygui = _sg, _easygui
    HEADLESS = False
except ImportError:
    HEADLESS = True

    class HeadlessError(RuntimeError):
        pass

    class _UserSettings:
        """sg.UserSettings without a file: every entry is None until set in this process."""
        _store: dict[str, Any] = {}

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __getitem__(self, key: str) -> Any:
            return self._store.get(key)

        def __setitem__(self, key: str, value: Any) -> None:
            self._store[key] = value

        def get(self, key: str, default: Any = None) -> Any:
            return self._store.get(key, default)

        def set(self, key: str, value: Any) -> None:
            self._store[key] = value

    class _Headless:
        def __init__(self, name: str) -> None:
            self._name = name

        def __getattr__(self, name: str) -> Any:
            if name.startswith('__'):
                raise AttributeError(name)

            def no_gui(*args: Any, **kwargs: Any) -> Any:
                raise HeadlessError("{}.{}: keine grafische Oberfläche verfügbar (tkinter fehlt)".format(self._name, name))
            return no_gui

    sg = _Headless('FreeSimpleGUI')
    sg.UserSettings = _UserSettings
    sg.user_settings_filename = lambda *a, **k: None
    sg.WIN_CLOSED = sg.WINDOW_CLOSED = None
    sg.theme = sg.theme_add_new = sg.set_options = lambda *a, **k: None
    easygui = _Headless('easygui')
