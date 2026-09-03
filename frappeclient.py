from __future__ import annotations

import requests
import json
from base64 import b64encode
import os
import time
import frappe
from frappe import cstr

from urllib.parse import quote
from typing import Any

try:
	from BytesIO import BytesIO
except:
	from io import BytesIO

class AuthError(Exception):
	pass


class FrappeException(Exception):
	pass


class SiteUnreachableError(FrappeException):
	pass


class SiteExpiredError(FrappeException):
	pass


class NotUploadableException(FrappeException):
	message: str

	def __init__(self, doctype: str) -> None:
		self.message = "The doctype `{0}` is not uploadable, so you can't download the template".format(doctype)


class FrappeClient:
	headers: dict[str, str]
	verify: bool
	session: requests.Session
	url: str
	api_key: str | None
	api_secret: str | None
	frappe_authorization_source: str | None
	can_download: list[str] | None

	def __init__(
		self,
		url: str,
		username: str | None = None,
		password: str | None = None,
		verify: bool = True,
		api_key: str | None = None,
		api_secret: str | None = None,
		frappe_authorization_source: str | None = None,
	) -> None:
		import requests

		self.headers = {
			"Accept": "application/json",
			"content-type": "application/x-www-form-urlencoded",
		}
		self.verify = verify
		self.session = requests.session()
		self.url = url
		self.api_key = api_key
		self.api_secret = api_secret
		self.frappe_authorization_source = frappe_authorization_source
		self.can_download = None

		self.setup_key_authentication_headers()

		# login if username/password provided
		if username and password:
			self._login(username, password)

	def __enter__(self) -> FrappeClient:
		return self

	def __exit__(self, *args: Any, **kwargs: Any) -> None:
		self.logout()

	def _login(self, username: str, password: str) -> dict[str, Any]:
		"""Login/start a sesion. Called internally on init"""
		r = self.session.post(
			self.url,
			params={"cmd": "login", "usr": username, "pwd": password},
			verify=self.verify,
			headers=self.headers,
		)

		if r.status_code == 200 and r.json().get("message") in ("Logged In", "No App"):
			return r.json()
		elif r.status_code == 502:
			raise SiteUnreachableError
		else:
			try:
				error = json.loads(r.text)
				if error.get("exc_type") == "SiteExpiredError":
					raise SiteExpiredError
			except json.decoder.JSONDecodeError:
				error = r.text
				print(error)
			raise AuthError

	def setup_key_authentication_headers(self) -> None:
		if self.api_key and self.api_secret:
			token = b64encode((f"{self.api_key}:{self.api_secret}").encode()).decode("utf-8")
			auth_header = {
				"Authorization": f"Basic {token}",
			}
			self.headers.update(auth_header)

			if self.frappe_authorization_source:
				auth_source = {"Frappe-Authorization-Source": self.frappe_authorization_source}
				self.headers.update(auth_source)

	def logout(self) -> None:
		"""Logout session"""
		self.session.get(
			self.url,
			params={
				"cmd": "logout",
			},
			verify=self.verify,
			headers=self.headers,
		)


	def get_list(
		self,
		doctype: str,
		fields: str | list[str] = '["name"]',
		filters: dict[str, Any] | list[Any] | None = None,
		limit_start: int = 0,
		limit_page_length: int | None = None,
		order_by: str | None = None,
	) -> list[dict[str, Any]]:
		"""Returns list of records of a particular type"""
		if not isinstance(fields, str):
			fields = json.dumps(fields)
		params: dict[str, Any] = {
			"fields": fields,
		}
		if filters:
			params["filters"] = json.dumps(filters)
		if limit_page_length is not None:
			params["limit_start"] = limit_start
			params["limit_page_length"] = limit_page_length
		if order_by:
			params['order_by'] = order_by
		res = self.session.get(
			self.url + "/api/resource/" + doctype, params=params, verify=self.verify, headers=self.headers
		)
		return self.post_process(res)

	def insert(self, doc: dict[str, Any]) -> frappe._dict:
		"""Insert a document to the remote server

		:param doc: A dict or Document object to be inserted remotely"""
		res = self.session.post(
			self.url + "/api/resource/" + doc.get("doctype"),  # type: ignore[operator]
			data={"data": frappe.as_json(doc)},
			verify=self.verify,
			headers=self.headers,
		)
		return frappe._dict(self.post_process(res))

	def insert_many(self, docs: list[dict[str, Any]]) -> Any:
		"""Insert multiple documents to the remote server

		:param docs: List of dict or Document objects to be inserted in one request"""
		return self.post_request({"cmd": "frappe.client.insert_many", "docs": frappe.as_json(docs)})

	def update(self, doc: dict[str, Any]) -> frappe._dict:
		"""Update a remote document

		:param doc: dict or Document object to be updated remotely. `name` is mandatory for this"""
		url = self.url + "/api/resource/" + doc.get("doctype") + "/" + cstr(doc.get("name"))  # type: ignore[operator]
		res = self.session.put(
			url, data={"data": frappe.as_json(doc)}, verify=self.verify, headers=self.headers
		)
		return frappe._dict(self.post_process(res))

	def update_with_doctype(self, doc: dict[str, Any], doctype: str) -> frappe._dict:
		'''Update a remote document and explicity specify its doctype'''
		doc1 = doc.copy()
		doc1['doctype'] = doctype
		return self.update(doc1) 

	def bulk_update(self, docs: list[dict[str, Any]]) -> Any:
		"""Bulk update documents remotely

		:param docs: List of dict or Document objects to be updated remotely (by `name`)"""
		return self.post_request({"cmd": "frappe.client.bulk_update", "docs": frappe.as_json(docs)})

	def delete(self, doctype: str, name: str) -> Any:
		"""Delete remote document by name

		:param doctype: `doctype` to be deleted
		:param name: `name` of document to be deleted"""
		return self.post_request({"cmd": "frappe.client.delete", "doctype": doctype, "name": name})

	def submit(self, doc: dict[str, Any]) -> dict[str, Any]:
		"""Submit remote document

		:param doc: dict or Document object to be submitted remotely"""
		return self.post_request({"cmd": "frappe.client.submit", "doc": frappe.as_json(doc)})

	def get_value(self, doctype: str, fieldname: str | list[str] | None = None, filters: dict[str, Any] | str | None = None) -> Any:
		"""Returns a value form a document

		:param doctype: DocType to be queried
		:param fieldname: Field to be returned (default `name`)
		:param filters: dict or string for identifying the record"""
		return self.get_request(
			{
				"cmd": "frappe.client.get_value",
				"doctype": doctype,
				"fieldname": fieldname or "name",
				"filters": frappe.as_json(filters),
			}
		)

	def set_value(self, doctype: str, docname: str, fieldname: str, value: Any) -> Any:
		"""Set a value in a remote document

		:param doctype: DocType of the document to be updated
		:param docname: name of the document to be updated
		:param fieldname: fieldname of the document to be updated
		:param value: value to be updated"""
		return self.post_request(
			{
				"cmd": "frappe.client.set_value",
				"doctype": doctype,
				"name": docname,
				"fieldname": fieldname,
				"value": value,
			}
		)

	def cancel(self, doctype: str, name: str) -> Any:
		"""Cancel a remote document

		:param doctype: DocType of the document to be cancelled
		:param name: name of the document to be cancelled"""
		return self.post_request({"cmd": "frappe.client.cancel", "doctype": doctype, "name": name})

	def get_doc(self, doctype: str, name: str = "", filters: dict[str, Any] | None = None, fields: list[str] | None = None) -> dict[str, Any]:
		"""Returns a single remote document

		:param doctype: DocType of the document to be returned
		:param name: (optional) `name` of the document to be returned
		:param filters: (optional) Filter by this dict if name is not set
		:param fields: (optional) Fields to be returned, will return everythign if not set"""
		params: dict[str, Any] = {}
		if filters:
			params["filters"] = json.dumps(filters)
		if fields:
			params["fields"] = json.dumps(fields)

		res = self.session_get(
			self.url + "/api/resource/" + doctype + "/" + cstr(name),
			params=params,
			verify=self.verify,
			headers=self.headers,
		)

		return self.post_process(res)

	def load_doc(self, doctype: str, name: str = "") -> dict[str, Any]:
		"""Returns a single remote document with all fields

		:param doctype: DocType of the document to be returned
		:param name: (optional) `name` of the document to be returned"""
		params = {'doctype' : doctype, 'name' : name}
		res = self.session_get(
			self.url + "/api/method/frappe.desk.form.load.getdoc",
			params=params,
			verify=self.verify,
			headers=self.headers,
		)

		return self.post_process(res)
		
        
	def reportview_get(self, doctype: str, filters: dict[str, Any] | list[Any] | None = None, fields: list[str] | None = None, params: dict[str, Any] = {}) -> Any:
		if filters:
			params["filters"] = json.dumps(filters)
		if fields:
			params["fields"] = json.dumps(fields)
		res = self.post_api("frappe.desk.reportview.get",params)
		return self.post_process(res)
		
        
	def rename_doc(self, doctype: str, old_name: str, new_name: str) -> Any:
		"""Rename remote document

		:param doctype: DocType of the document to be renamed
		:param old_name: Current `name` of the document to be renamed
		:param new_name: New `name` to be set"""
		params = {
			"cmd": "frappe.client.rename_doc",
			"doctype": doctype,
			"old_name": old_name,
			"new_name": new_name,
		}
		return self.post_request(params)        


	def get_background_jobs(self) -> Any:
                return self.get_request(
			{
				"cmd": "frappe.core.page.background_jobs.background_jobs.get_info",
			})

        
	def get_pdf(self, doctype: str, name: str, print_format: str = 'Standard', letterhead: bool = True, language: str = 'de') -> Any:
		params = {
			'doctype': doctype,
			'name': name,
			'format': print_format,
                        '_lang':language,
			'no_letterhead': int(not bool(letterhead))
		}
		response = self.session_get(
			self.url + '/api/method/frappe.utils.print_format.download_pdf',
			params=params,
                        verify=self.verify,
			headers=self.headers,
                        stream=True)

		return self.post_process_file_stream(response)

	def get_html(self, doctype: str, name: str, print_format: str = 'Standard', letterhead: bool = True) -> Any:
		params = {
			'doctype': doctype,
			'name': name,
			'format': print_format,
			'no_letterhead': int(not bool(letterhead))
		}
		response = self.session_get(
			self.url + '/print', params=params, stream=True
		)
		return self.post_process_file_stream(response)

	def __load_downloadable_templates(self) -> None:
		self.can_download = self.get_api('frappe.core.page.data_import_tool.data_import_tool.get_doctypes')

	def get_upload_template(self, doctype: str, with_data: bool = False) -> Any:
		if not self.can_download:
			self.__load_downloadable_templates()

		if doctype not in self.can_download:
			raise NotUploadableException(doctype)

		params = {
			'doctype': doctype,
			'parent_doctype': doctype,
			'with_data': 'Yes' if with_data else 'No',
			'all_doctypes': 'Yes'
		}

		request = self.session_get(
			self.url + '/api/method/frappe.core.page.data_import_tool.exporter.get_template',
			params=params
		)
		return self.post_process_file_stream(request)

	def attach_file(self, doctype: str, docname: str, filename: str, filedata: bytes, is_private: bool, docfield: str | None = None) -> Any:
		params = {
			'cmd': 'frappe.client.attach_file',
			'doctype': doctype,
			'docname': docname,
			'filename': filename,
                        'filedata': b64encode(filedata),
                        'is_private': 1 if is_private else 0,
                        'decode_base64': 1
		}
		if docfield:
			# links the file to the Attach field and sets it; without this, Frappe creates
			# another, public copy of the file on the next save
			params['docfield'] = docfield
		return self.post_request(params)

	def read_and_attach_file(self, doctype: str, docname: str, filename: str, is_private: bool, docfield: str | None = None) -> Any:
            basename = os.path.basename(filename)
            filedata = open(filename,"rb").read()
            return self.attach_file(doctype,docname,basename,filedata,is_private,docfield)

	def query_report(self, report_name: str = "", filters: dict[str, Any] | None = None, ignore_prepared_report: bool = False) -> Any:
		params: dict[str, Any] = {}
		if filters:
			params["filters"] = json.dumps(filters)
		params['report_name'] = report_name
		if ignore_prepared_report:
			# otherwise "Prepared Reports" (e.g. Consolidated Financial Statement) are only created in the background
			params['ignore_prepared_report'] = 1
		return self.get_api('frappe.desk.query_report.run',params)

	def get_file(self, path: str) -> bytes:
		'''Returns a file from the file system'''
		return self.session_get(self.url + path,
                                        verify=self.verify,
			                headers=self.headers).content

	def get_attachments(self, doctype: str, name: str) -> Any:
		'''Returns attachments to a document'''
		params = {
			'doctype': doctype,
			'name' : name,
		}
		res = self.session_get(self.url + "/api/resource/" + doctype + "/" + name + "?run_method=frappe.core.doctype.file.file.get_attached_images",
			params=params)
		return self.post_process(res)

	def get_open_activities(self, doctype: str, name: str) -> Any:
		'''Returns open activities of a document'''
		return self.get_request(
			{
				"cmd": "erpnext.crm.utils.get_open_activities",
				"ref_doctype": doctype,
				"ref_docname": name,
			})

	def get_unreconciled_entries(self, name: str) -> Any:
		res = self.session_get(self.url + '/api/resource/' + 'Payment Reconciliation' + '/' + name)

		return self.post_process(res)

	def assign_to(self, doctype: str, name: str, assign_to: list[str]) -> Any:
		params = {"assign_to" : json.dumps(assign_to),
		          "doctype" : doctype,
		          "name" : name,
		         }
		return self.post_api('frappe.desk.form.assign_to.add',params)

	def get_api(self, method: str, params: dict[str, Any] | None = None) -> Any:
		if params is None:
			params = {}
		res = self.session.get(
			f"{self.url}/api/method/{method}", params=params, verify=self.verify, headers=self.headers
		)
		return self.post_process(res)

	def post_api(self, method: str, params: dict[str, Any] | None = None) -> Any:
		if params is None:
			params = {}
		res = self.session.post(
			f"{self.url}/api/method/{method}", params=params, verify=self.verify, headers=self.headers
		)
		return self.post_process(res)

	def get_request(self, params: dict[str, Any]) -> Any:
		res = self.session.get(
			self.url, params=self.preprocess(params), verify=self.verify, headers=self.headers
		)
		res = self.post_process(res)
		return res

	def post_request(self, data: dict[str, Any]) -> Any:
		res = self.session.post(
			self.url, data=self.preprocess(data), verify=self.verify, headers=self.headers
		)
		res = self.post_process(res)
		return res

	def session_get(self, *args: Any, **kwargs: Any) -> requests.Response:
		res: requests.Response | None = None
		while res is None:
			try:
				res = self.session.get(*args,**kwargs)
			except requests.exceptions.ConnectionError as e:
				# too many API calls can cause problems
				print("Warnung: API-Verbindungsproblem")
				time.sleep(1)
		return res


	def preprocess(self, params: dict[str, Any]) -> dict[str, Any]:
		"""convert dicts, lists to json"""
		for key, value in params.items():
			if isinstance(value, (dict, list)):
				params[key] = json.dumps(value)

		return params

	def post_process(self, response: requests.Response) -> Any:
		try:
			rjson = response.json()
		except ValueError:
			print(response.text)
			raise

		if rjson and ("exc" in rjson) and rjson["exc"]:
			try:
				exc = json.loads(rjson["exc"])[0]
				exc = "FrappeClient Request Failed\n\n" + exc
			except Exception:
				exc = rjson["exc"]

			raise FrappeException(exc)
		if rjson and rjson.get("exc_type") and response.status_code >= 400:
			# on 404/417 Frappe 14 often only returns exc_type and _server_messages, without "exc"
			raise FrappeException("FrappeClient Request Failed\n\n{}: {}".format(
				rjson["exc_type"], rjson.get("exception") or rjson.get("_server_messages") or response.status_code))
		if "message" in rjson:
			return rjson["message"]
		elif "data" in rjson:
			return rjson["data"]
		elif "docs" in rjson:
			return rjson
		else:
			return None

	def post_process_file_stream(self, response: requests.Response) -> Any:
		if response.ok:
			output = BytesIO()
			for block in response.iter_content(1024):
				output.write(block)
			output.seek(0)
			return output

		else:
			try:
				rjson = response.json()
			except ValueError:
				print(response.text)
				raise

			if rjson and ('exc' in rjson) and rjson['exc']:
				raise FrappeException(rjson['exc'])
			if 'message' in rjson:
				return rjson['message']
			elif 'data' in rjson:
				return rjson['data']
			else:
				return None
