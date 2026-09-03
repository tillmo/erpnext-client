"""Headless replacement for GUI modules and optional third-party packages.

Two reasons for stubs:

* PySimpleGUI / PySimpleGUIWx / easygui are ALWAYS replaced, even if they are
  installed: tests must neither open windows nor overwrite the user's real
  ``erpnext.json`` (sg.UserSettings with autosave).
* jsondiff, jsoneditor, anytree, plotly, datefinder, google-cloud-documentai
  are only replaced if they are missing, so that the project modules remain
  importable. Tests that need the real behaviour of these packages carry the
  ``requires_*`` markers from :mod:`support.deps`.

Every GUI call that was not explicitly answered by a test raises
``GuiCalled`` - so it is immediately noticeable when code unexpectedly runs into a dialog.
"""
from __future__ import annotations

import importlib
import sys
import types
from typing import Any, Callable, Iterable, Iterator, NoReturn


class GuiCalled(RuntimeError):
    """A test has reached code that would open a GUI dialog."""


# ---------------------------------------------------------------- PySimpleGUI
class UserSettings:
    """Replica of sg.UserSettings: all instances share one store.

    Like the original, ``settings['missing']`` returns None instead of KeyError.
    """
    store: dict[str, Any] = {}
    filename: str | None = None

    def __init__(self, filename: str | None = None, path: str | None = None, **kwargs: Any) -> None:
        pass

    def __getitem__(self, key: str) -> Any:
        return UserSettings.store.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        UserSettings.store[key] = value

    def __contains__(self, key: object) -> bool:
        return key in UserSettings.store

    def get(self, key: str, default: Any = None) -> Any:
        return UserSettings.store.get(key, default)

    def set(self, key: str, value: Any) -> None:
        UserSettings.store[key] = value

    def delete_entry(self, key: str) -> None:
        UserSettings.store.pop(key, None)

    def __repr__(self) -> str:
        return "UserSettings({!r})".format(UserSettings.store)


def _gui_function(module_name: str, attr: str) -> Callable[..., NoReturn]:
    def raiser(*args: Any, **kwargs: Any) -> NoReturn:
        raise GuiCalled("{}.{} wurde aufgerufen (args={!r})".format(module_name, attr, args[:2]))
    raiser.__name__ = attr
    return raiser


def make_pysimplegui() -> types.ModuleType:
    mod: Any = types.ModuleType("PySimpleGUI")
    mod.UserSettings = UserSettings
    mod.WIN_CLOSED = None
    mod.WINDOW_CLOSED = None

    def user_settings_filename(filename: str | None = None, path: str | None = None) -> str | None:
        UserSettings.filename = filename
        return filename
    mod.user_settings_filename = user_settings_filename

    # harmless configuration calls
    mod.set_options = lambda *a, **k: None
    mod.theme = lambda *a, **k: None
    mod.theme_add_new = lambda *a, **k: None

    def __getattr__(name: str) -> Callable[..., NoReturn]:
        if name.startswith("__"):
            raise AttributeError(name)
        return _gui_function("PySimpleGUI", name)
    mod.__getattr__ = __getattr__
    return mod


def make_pysimpleguiwx() -> types.ModuleType:
    mod: Any = types.ModuleType("PySimpleGUIWx")
    mod.PopupGetFile = _gui_function("PySimpleGUIWx", "PopupGetFile")

    def __getattr__(name: str) -> Callable[..., NoReturn]:
        if name.startswith("__"):
            raise AttributeError(name)
        return _gui_function("PySimpleGUIWx", name)
    mod.__getattr__ = __getattr__
    return mod


# -------------------------------------------------------------------- easygui
class EasyguiStub(types.ModuleType):
    """easygui replacement: answers are provided per function, calls are logged.

    ``answers[name]`` may be a value or a callable(*args, **kwargs).
    Without a stored answer, every dialog raises GuiCalled.
    """
    FUNCTIONS: tuple[str, ...] = ("choicebox", "msgbox", "ccbox", "buttonbox", "fileopenbox",
                 "ynbox", "multchoicebox", "multenterbox", "enterbox", "textbox", "boolbox")

    def __init__(self) -> None:
        super().__init__("easygui")
        self.answers: dict[str, Any] = {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        for name in self.FUNCTIONS:
            setattr(self, name, self._make(name))

    def reset(self) -> None:
        self.answers = {}
        self.calls = []

    def _make(self, name: str) -> Callable[..., Any]:
        def dialog(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            if name not in self.answers:
                raise GuiCalled("easygui.{} wurde aufgerufen: {!r}".format(name, args[:2]))
            answer = self.answers[name]
            if callable(answer):
                return answer(*args, **kwargs)
            return answer
        dialog.__name__ = name
        return dialog


# ------------------------------------------ optional third-party packages
def make_jsondiff() -> tuple[types.ModuleType, types.ModuleType]:
    mod: Any = types.ModuleType("jsondiff")
    symbols: Any = types.ModuleType("jsondiff.symbols")

    class Symbol:
        def __init__(self, label: str) -> None:
            self.label: str = label

        def __repr__(self) -> str:
            return "$" + self.label

    symbols.Symbol = Symbol
    symbols.insert = Symbol("insert")
    symbols.delete = Symbol("delete")
    symbols.update = Symbol("update")
    symbols.replace = Symbol("replace")
    mod.symbols = symbols
    mod.insert = symbols.insert
    mod.delete = symbols.delete

    def diff(a: Any, b: Any, syntax: str = "compact", **kwargs: Any) -> NoReturn:
        raise NotImplementedError("jsondiff ist nicht installiert - Test mit requires_jsondiff markieren")
    mod.diff = diff
    mod.__stub__ = True
    return mod, symbols


def make_jsoneditor() -> types.ModuleType:
    mod: Any = types.ModuleType("jsoneditor")

    def editjson(data: Any, callback: Callable[..., Any] | None = None, **kwargs: Any) -> NoReturn:
        raise GuiCalled("jsoneditor.editjson wurde aufgerufen")
    mod.editjson = editjson
    mod.__stub__ = True
    return mod


def make_anytree() -> types.ModuleType:
    """Minimal but semantically faithful replica of anytree.Node/PostOrderIter/RenderTree."""
    mod: Any = types.ModuleType("anytree")

    class Node:
        def __init__(self, name: Any, parent: Node | None = None,
                     children: Iterable[Node] | None = None, **kwargs: Any) -> None:
            self.name: Any = name
            self.__dict__.update(kwargs)
            self._children: list[Node] = []
            self._parent: Node | None = None
            self.parent = parent
            if children:
                for c in children:
                    c.parent = self

        @property
        def parent(self) -> Node | None:
            return self._parent

        @parent.setter
        def parent(self, value: Node | None) -> None:
            if self._parent is not None:
                self._parent._children.remove(self)
            self._parent = value
            if value is not None:
                value._children.append(self)

        @property
        def children(self) -> tuple[Node, ...]:
            return tuple(self._children)

        @property
        def is_leaf(self) -> bool:
            return not self._children

        @property
        def is_root(self) -> bool:
            return self._parent is None

        def __repr__(self) -> str:
            return "Node({!r})".format(self.name)

    class PostOrderIter:
        def __init__(self, node: Node) -> None:
            self.node: Node = node

        def __iter__(self) -> Iterator[Node]:
            def walk(n: Node) -> Iterator[Node]:
                for c in n.children:
                    yield from walk(c)
                yield n
            return walk(self.node)

    class PreOrderIter(PostOrderIter):
        def __iter__(self) -> Iterator[Node]:
            def walk(n: Node) -> Iterator[Node]:
                yield n
                for c in n.children:
                    yield from walk(c)
            return walk(self.node)

    def RenderTree(node: Node) -> Iterator[tuple[str, str, Node]]:
        def walk(n: Node, depth: int) -> Iterator[tuple[str, str, Node]]:
            yield ("    " * depth, "", n)
            for c in n.children:
                yield from walk(c, depth + 1)
        return walk(node, 0)

    mod.Node = Node
    mod.PostOrderIter = PostOrderIter
    mod.PreOrderIter = PreOrderIter
    mod.RenderTree = RenderTree
    mod.__stub__ = True
    return mod


def make_plotly() -> tuple[types.ModuleType, types.ModuleType]:
    plotly: Any = types.ModuleType("plotly")
    px: Any = types.ModuleType("plotly.express")
    px.calls = []

    class Figure:
        def __init__(self, kwargs: dict[str, Any]) -> None:
            self.kwargs: dict[str, Any] = kwargs
            self.shown: bool = False

        def show(self) -> None:
            self.shown = True

    def line(*args: Any, **kwargs: Any) -> Figure:
        fig = Figure(kwargs)
        px.calls.append(("line", args, kwargs, fig))
        return fig
    px.line = line
    plotly.express = px
    plotly.__stub__ = True
    return plotly, px


def make_datefinder() -> types.ModuleType:
    mod: Any = types.ModuleType("datefinder")

    def find_dates(text: str, **kwargs: Any) -> NoReturn:
        raise NotImplementedError("datefinder ist nicht installiert - Test mit requires_datefinder markieren")
    mod.find_dates = find_dates
    mod.__stub__ = True
    return mod


def make_google() -> tuple[Any, dict[str, types.ModuleType]]:
    """google.cloud.documentai_v1beta3 and google.api_core.client_options."""
    created: dict[str, types.ModuleType] = {}
    google: Any
    try:
        google = importlib.import_module("google")
    except ImportError:
        google = types.ModuleType("google")
        google.__path__ = []
        created["google"] = google

    cloud: Any = types.ModuleType("google.cloud")
    cloud.__path__ = []
    documentai: Any = types.ModuleType("google.cloud.documentai_v1beta3")

    class DocumentProcessorServiceClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("google-cloud-documentai ist nicht installiert")
    documentai.DocumentProcessorServiceClient = DocumentProcessorServiceClient
    documentai.__stub__ = True
    cloud.documentai_v1beta3 = documentai
    created["google.cloud"] = cloud
    created["google.cloud.documentai_v1beta3"] = documentai

    api_core: Any = types.ModuleType("google.api_core")
    api_core.__path__ = []
    client_options: Any = types.ModuleType("google.api_core.client_options")

    class ClientOptions:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)
    client_options.ClientOptions = ClientOptions
    api_core.client_options = client_options
    created["google.api_core"] = api_core
    created["google.api_core.client_options"] = client_options
    return google, created


# ------------------------------------------------------------ Installation
def _missing(name: str) -> bool:
    try:
        importlib.import_module(name)
        return False
    except Exception:  # ImportError, but also broken installations
        return True


def install() -> dict[str, types.ModuleType]:
    """Register stubs in sys.modules. Must run before the first project import.

    Returns a dict with the installed stub modules (for fixtures).
    """
    installed: dict[str, types.ModuleType] = {}

    sg = make_pysimplegui()
    sys.modules["PySimpleGUI"] = sg
    installed["PySimpleGUI"] = sg
    sgwx = make_pysimpleguiwx()
    sys.modules["PySimpleGUIWx"] = sgwx
    installed["PySimpleGUIWx"] = sgwx
    eg = EasyguiStub()
    sys.modules["easygui"] = eg
    installed["easygui"] = eg

    if _missing("jsondiff"):
        mod, symbols = make_jsondiff()
        sys.modules["jsondiff"] = mod
        sys.modules["jsondiff.symbols"] = symbols
        installed["jsondiff"] = mod
    if _missing("jsoneditor"):
        installed["jsoneditor"] = sys.modules["jsoneditor"] = make_jsoneditor()
    if _missing("anytree"):
        installed["anytree"] = sys.modules["anytree"] = make_anytree()
    if _missing("plotly.express"):
        plotly, px = make_plotly()
        sys.modules["plotly"] = plotly
        sys.modules["plotly.express"] = px
        installed["plotly"] = plotly
    if _missing("datefinder"):
        installed["datefinder"] = sys.modules["datefinder"] = make_datefinder()
    if _missing("google.cloud.documentai_v1beta3") or _missing("google.api_core.client_options"):
        google, created = make_google()
        for name, mod in created.items():
            sys.modules[name] = mod
        if hasattr(google, "__path__"):
            google.cloud = created["google.cloud"]
            google.api_core = created["google.api_core"]
        installed.update(created)
    return installed
