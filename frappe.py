def as_unicode(text: str, encoding: str = "utf-8") -> str:
	"""Convert to unicode if required"""
	if isinstance(text, str):
		return text
	elif text is None:
		return ""
	elif isinstance(text, bytes):
		return str(text, encoding)
	else:
		return str(text)

def cstr(s, encoding="utf-8"):
        return as_unicode(s, encoding)

class _dict(dict):
	"""dict like object that exposes keys as attributes"""

	__slots__ = ()
	__getattr__ = dict.get
	__setattr__ = dict.__setitem__
	__delattr__ = dict.__delitem__
	__setstate__ = dict.update

	def __getstate__(self):
		return self

	def update(self, *args, **kwargs):
		"""update and return self -- the missing dict feature in python"""

		super().update(*args, **kwargs)
		return self

	def copy(self):
		return _dict(self)

def json_handler(obj):
	"""serialize non-serializable data for json"""
	from collections.abc import Iterable
	from re import Match

	if isinstance(obj, (datetime.date, datetime.datetime, datetime.time)):
		return str(obj)

	elif isinstance(obj, datetime.timedelta):
		return format_timedelta(obj)

	elif isinstance(obj, decimal.Decimal):
		return float(obj)

	elif isinstance(obj, LocalProxy):
		return str(obj)

	elif isinstance(obj, frappe.model.document.BaseDocument):
		doc = obj.as_dict(no_nulls=True)
		return doc

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

def as_json(obj, indent=1, separators=None) -> str:
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
