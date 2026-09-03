from __future__ import annotations

import datetime
import decimal
import json
from typing import TYPE_CHECKING, Any

def as_unicode(text: str | bytes | None, encoding: str = "utf-8") -> str:
	"""Convert to unicode if required"""
	if isinstance(text, str):
		return text
	elif text is None:
		return ""
	elif isinstance(text, bytes):
		return str(text, encoding)
	else:
		return str(text)

def cstr(s: Any, encoding: str = "utf-8") -> str:
        return as_unicode(s, encoding)

class _dict(dict):
	"""dict like object that exposes keys as attributes"""

	__slots__ = ()
	if TYPE_CHECKING:
		# attribute access is dict.get/dict.__setitem__; this way the type checker understands it too
		def __getattr__(self, name: str) -> Any: ...
		def __setattr__(self, name: str, value: Any) -> None: ...
		def __delattr__(self, name: str) -> None: ...
	else:
		__getattr__ = dict.get
		__setattr__ = dict.__setitem__
		__delattr__ = dict.__delitem__
	__setstate__ = dict.update

	def __getstate__(self) -> _dict:
		return self

	def update(self, *args: Any, **kwargs: Any) -> _dict:  # type: ignore[override]
		"""update and return self -- the missing dict feature in python"""

		super().update(*args, **kwargs)
		return self

	def copy(self) -> _dict:
		return _dict(self)

def json_handler(obj: Any) -> Any:
	"""serialize non-serializable data for json"""
	from collections.abc import Iterable
	from re import Match

	if isinstance(obj, (datetime.date, datetime.datetime, datetime.time)):
		return str(obj)

	elif isinstance(obj, datetime.timedelta):
		return str(obj)

	elif isinstance(obj, decimal.Decimal):
		return float(obj)

	elif isinstance(obj, Iterable):
		return list(obj)

	elif isinstance(obj, Match):
		return obj.string

	elif type(obj) == type or isinstance(obj, Exception):
		return repr(obj)

	elif callable(obj):
		return repr(obj)

	else:
		raise TypeError(
			f"""Object of type {type(obj)} with value of {repr(obj)} is not JSON serializable"""
		)

def as_json(obj: Any, indent: int | None = 1, separators: tuple[str, str] | None = None) -> str:
#	from frappe.utils.response import json_handler

	if separators is None:
		separators = (",", ": ")

	try:
		return json.dumps(
			obj, indent=indent, sort_keys=True, default=json_handler, separators=separators
		)
	except TypeError:
		# this would break in case the keys are not all os "str" type - as defined in the JSON
		# adding this to ensure keys are sorted (expected behaviour)
		sorted_obj = dict(sorted(obj.items(), key=lambda kv: str(kv[0])))
		return json.dumps(sorted_obj, indent=indent, default=json_handler, separators=separators)
