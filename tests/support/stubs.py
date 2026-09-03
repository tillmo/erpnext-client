"""Headless-Ersatz für GUI-Module und optionale Fremdpakete.

Zwei Gründe für Stubs:

* PySimpleGUI / PySimpleGUIWx / easygui werden IMMER ersetzt, auch wenn sie
  installiert sind: Tests dürfen weder Fenster öffnen noch die echte
  ``erpnext.json`` des Benutzers (sg.UserSettings mit autosave) überschreiben.
* jsondiff, jsoneditor, anytree, plotly, datefinder, google-cloud-documentai
  werden nur ersetzt, wenn sie fehlen, damit die Projektmodule importierbar
  bleiben. Tests, die das echte Verhalten dieser Pakete brauchen, sind mit
  den ``requires_*``-Markern aus :mod:`support.deps` versehen.

Jeder GUI-Aufruf, der nicht explizit von einem Test beantwortet wurde, wirft
``GuiCalled`` - so fällt sofort auf, wenn Code unerwartet in einen Dialog läuft.
"""
import importlib
import sys
import types


class GuiCalled(RuntimeError):
    """Ein Test hat Code erreicht, der einen GUI-Dialog öffnen würde."""


# ---------------------------------------------------------------- PySimpleGUI
class UserSettings:
    """Nachbildung von sg.UserSettings: alle Instanzen teilen einen Speicher.

    Wie das Original liefert ``settings['fehlt']`` None statt KeyError.
    """
    store = {}
    filename = None

    def __init__(self, filename=None, path=None, **kwargs):
        pass

    def __getitem__(self, key):
        return UserSettings.store.get(key)

    def __setitem__(self, key, value):
        UserSettings.store[key] = value

    def __contains__(self, key):
        return key in UserSettings.store

    def get(self, key, default=None):
        return UserSettings.store.get(key, default)

    def set(self, key, value):
        UserSettings.store[key] = value

    def delete_entry(self, key):
        UserSettings.store.pop(key, None)

    def __repr__(self):
        return "UserSettings({!r})".format(UserSettings.store)


def _gui_function(module_name, attr):
    def raiser(*args, **kwargs):
        raise GuiCalled("{}.{} wurde aufgerufen (args={!r})".format(module_name, attr, args[:2]))
    raiser.__name__ = attr
    return raiser


def make_pysimplegui():
    mod = types.ModuleType("PySimpleGUI")
    mod.UserSettings = UserSettings
    mod.WIN_CLOSED = None
    mod.WINDOW_CLOSED = None

    def user_settings_filename(filename=None, path=None):
        UserSettings.filename = filename
        return filename
    mod.user_settings_filename = user_settings_filename

    # harmlose Konfigurationsaufrufe
    mod.set_options = lambda *a, **k: None
    mod.theme = lambda *a, **k: None
    mod.theme_add_new = lambda *a, **k: None

    def __getattr__(name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _gui_function("PySimpleGUI", name)
    mod.__getattr__ = __getattr__
    return mod


def make_pysimpleguiwx():
    mod = types.ModuleType("PySimpleGUIWx")
    mod.PopupGetFile = _gui_function("PySimpleGUIWx", "PopupGetFile")

    def __getattr__(name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _gui_function("PySimpleGUIWx", name)
    mod.__getattr__ = __getattr__
    return mod


# -------------------------------------------------------------------- easygui
class EasyguiStub(types.ModuleType):
    """easygui-Ersatz: Antworten werden pro Funktion vorgegeben, Aufrufe protokolliert.

    ``answers[name]`` darf ein Wert oder ein Callable(*args, **kwargs) sein.
    Ohne hinterlegte Antwort wirft jeder Dialog GuiCalled.
    """
    FUNCTIONS = ("choicebox", "msgbox", "ccbox", "buttonbox", "fileopenbox",
                 "ynbox", "multchoicebox", "enterbox", "textbox", "boolbox")

    def __init__(self):
        super().__init__("easygui")
        self.answers = {}
        self.calls = []
        for name in self.FUNCTIONS:
            setattr(self, name, self._make(name))

    def reset(self):
        self.answers = {}
        self.calls = []

    def _make(self, name):
        def dialog(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name not in self.answers:
                raise GuiCalled("easygui.{} wurde aufgerufen: {!r}".format(name, args[:2]))
            answer = self.answers[name]
            if callable(answer):
                return answer(*args, **kwargs)
            return answer
        dialog.__name__ = name
        return dialog


# ------------------------------------------------- optionale Fremdpakete
def make_jsondiff():
    mod = types.ModuleType("jsondiff")
    symbols = types.ModuleType("jsondiff.symbols")

    class Symbol:
        def __init__(self, label):
            self.label = label

        def __repr__(self):
            return "$" + self.label

    symbols.Symbol = Symbol
    symbols.insert = Symbol("insert")
    symbols.delete = Symbol("delete")
    symbols.update = Symbol("update")
    symbols.replace = Symbol("replace")
    mod.symbols = symbols
    mod.insert = symbols.insert
    mod.delete = symbols.delete

    def diff(a, b, syntax="compact", **kwargs):
        raise NotImplementedError("jsondiff ist nicht installiert - Test mit requires_jsondiff markieren")
    mod.diff = diff
    mod.__stub__ = True
    return mod, symbols


def make_jsoneditor():
    mod = types.ModuleType("jsoneditor")

    def editjson(data, callback=None, **kwargs):
        raise GuiCalled("jsoneditor.editjson wurde aufgerufen")
    mod.editjson = editjson
    mod.__stub__ = True
    return mod


def make_anytree():
    """Minimale, aber semantisch treue Nachbildung von anytree.Node/PostOrderIter/RenderTree."""
    mod = types.ModuleType("anytree")

    class Node:
        def __init__(self, name, parent=None, children=None, **kwargs):
            self.name = name
            self.__dict__.update(kwargs)
            self._children = []
            self._parent = None
            self.parent = parent
            if children:
                for c in children:
                    c.parent = self

        @property
        def parent(self):
            return self._parent

        @parent.setter
        def parent(self, value):
            if self._parent is not None:
                self._parent._children.remove(self)
            self._parent = value
            if value is not None:
                value._children.append(self)

        @property
        def children(self):
            return tuple(self._children)

        @property
        def is_leaf(self):
            return not self._children

        @property
        def is_root(self):
            return self._parent is None

        def __repr__(self):
            return "Node({!r})".format(self.name)

    class PostOrderIter:
        def __init__(self, node):
            self.node = node

        def __iter__(self):
            def walk(n):
                for c in n.children:
                    yield from walk(c)
                yield n
            return walk(self.node)

    class PreOrderIter(PostOrderIter):
        def __iter__(self):
            def walk(n):
                yield n
                for c in n.children:
                    yield from walk(c)
            return walk(self.node)

    def RenderTree(node):
        def walk(n, depth):
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


def make_plotly():
    plotly = types.ModuleType("plotly")
    px = types.ModuleType("plotly.express")
    px.calls = []

    class Figure:
        def __init__(self, kwargs):
            self.kwargs = kwargs
            self.shown = False

        def show(self):
            self.shown = True

    def line(*args, **kwargs):
        fig = Figure(kwargs)
        px.calls.append(("line", args, kwargs, fig))
        return fig
    px.line = line
    plotly.express = px
    plotly.__stub__ = True
    return plotly, px


def make_datefinder():
    mod = types.ModuleType("datefinder")

    def find_dates(text, **kwargs):
        raise NotImplementedError("datefinder ist nicht installiert - Test mit requires_datefinder markieren")
    mod.find_dates = find_dates
    mod.__stub__ = True
    return mod


def make_google():
    """google.cloud.documentai_v1beta3 und google.api_core.client_options."""
    created = {}
    try:
        google = importlib.import_module("google")
    except ImportError:
        google = types.ModuleType("google")
        google.__path__ = []
        created["google"] = google

    cloud = types.ModuleType("google.cloud")
    cloud.__path__ = []
    documentai = types.ModuleType("google.cloud.documentai_v1beta3")

    class DocumentProcessorServiceClient:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("google-cloud-documentai ist nicht installiert")
    documentai.DocumentProcessorServiceClient = DocumentProcessorServiceClient
    documentai.__stub__ = True
    cloud.documentai_v1beta3 = documentai
    created["google.cloud"] = cloud
    created["google.cloud.documentai_v1beta3"] = documentai

    api_core = types.ModuleType("google.api_core")
    api_core.__path__ = []
    client_options = types.ModuleType("google.api_core.client_options")

    class ClientOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    client_options.ClientOptions = ClientOptions
    api_core.client_options = client_options
    created["google.api_core"] = api_core
    created["google.api_core.client_options"] = client_options
    return google, created


# ------------------------------------------------------------ Installation
def _missing(name):
    try:
        importlib.import_module(name)
        return False
    except Exception:  # ImportError, aber auch kaputte Installationen
        return True


def install():
    """Stubs in sys.modules eintragen. Muss vor dem ersten Projekt-Import laufen.

    Liefert ein dict mit den installierten Stub-Modulen (für Fixtures).
    """
    installed = {}

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
