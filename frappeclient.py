import requests
import json
from base64 import b64encode
import os
import time
import frappe
from frappe import cstr

from urllib.parse import quote

try:
	from BytesIO import BytesIO
except:
	from io import BytesIO

try:
    unicode
except NameError:
    unicode = str


class AuthError(Exception):
	pass


class FrappeException(Exception):
	pass


class NotUploadableException(FrappeException):
	def __init__(self, doctype):
		self.message = "The doctype `{1}` is not uploadable, so you can't download the template".format(doctype)


class FrappeClient:
	def __init__(
		self,
		url,
		username=None,
		password=None,
		verify=True,
		api_key=None,
		api_secret=None,
		frappe_authorization_source=None,
	):
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

		self.setup_key_authentication_headers()

		# login if username/password provided
		if username and password:
			self._login(username, password)

	def __enter__(self):
		return self

	def __exit__(self, *args, **kwargs):
		self.logout()

	def _login(self, username, password):
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

	def setup_key_authentication_headers(self):
		if self.api_key and self.api_secret:
			token = b64encode((f"{self.api_key}:{self.api_secret}").encode()).decode("utf-8")
			auth_header = {
				"Authorization": f"Basic {token}",
			}
			self.headers.update(auth_header)

			if self.frappe_authorization_source:
				auth_source = {"Frappe-Authorization-Source": self.frappe_authorization_source}
				self.headers.update(auth_source)

	def logout(self):
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
		self, doctype, fields='["name"]', filters=None, limit_start=0, limit_page_length=None, order_by=None
	):
		"""Returns list of records of a particular type"""
		if not isinstance(fields, str):
			fields = json.dumps(fields)
		params = {
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

	def insert(self, doc):
		"""Insert a document to the remote server

		:param doc: A dict or Document object to be inserted remotely"""
		res = self.session.post(
			self.url + "/api/resource/" + doc.get("doctype"),
			data={"data": frappe.as_json(doc)},
			verify=self.verify,
			headers=self.headers,
		)
		return frappe._dict(self.post_process(res))

	def insert_many(self, docs):
		"""Insert multiple documents to the remote server

		:param docs: List of dict or Document objects to be inserted in one request"""
		return self.post_request({"cmd": "frappe.client.insert_many", "docs": frappe.as_json(docs)})

	def update(self, doc):
		"""Update a remote document

		:param doc: dict or Document object to be updated remotely. `name` is mandatory for this"""
		url = self.url + "/api/resource/" + doc.get("doctype") + "/" + cstr(doc.get("name"))
		res = self.session.put(
			url, data={"data": frappe.as_json(doc)}, verify=self.verify, headers=self.headers
		)
		return frappe._dict(self.post_process(res))

	def update_with_doctype(self, doc, doctype):
		'''Update a remote document and explicity specify its doctype'''
		doc1 = doc.copy()
		doc1['doctype'] = doctype
		return self.update(doc1) 

	def bulk_update(self, docs):
		"""Bulk update documents remotely

		:param docs: List of dict or Document objects to be updated remotely (by `name`)"""
		return self.post_request({"cmd": "frappe.client.bulk_update", "docs": frappe.as_json(docs)})

	def delete(self, doctype, name):
		"""Delete remote document by name

		:param doctype: `doctype` to be deleted
		:param name: `name` of document to be deleted"""
		return self.post_request({"cmd": "frappe.client.delete", "doctype": doctype, "name": name})

	def submit(self, doc):
		"""Submit remote document

		:param doc: dict or Document object to be submitted remotely"""
		return self.post_request({"cmd": "frappe.client.submit", "doc": frappe.as_json(doc)})

	def get_value(self, doctype, fieldname=None, filters=None):
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

	def set_value(self, doctype, docname, fieldname, value):
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

	def cancel(self, doctype, name):
		"""Cancel a remote document

		:param doctype: DocType of the document to be cancelled
		:param name: name of the document to be cancelled"""
		return self.post_request({"cmd": "frappe.client.cancel", "doctype": doctype, "name": name})

	def get_doc(self, doctype, name="", filters=None, fields=None):
		"""Returns a single remote document

		:param doctype: DocType of the document to be returned
		:param name: (optional) `name` of the document to be returned
		:param filters: (optional) Filter by this dict if name is not set
		:param fields: (optional) Fields to be returned, will return everythign if not set"""
		params = {}
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

	def rename_doc(self, doctype, old_name, new_name):
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


	def get_background_jobs(self):
		response = self.session_get(
			self.url + '/api/method/frappe.core.page.background_jobs.background_jobs.get_info')
		return self.post_process(response)

        
	def get_pdf(self, doctype, name, print_format='Standard', letterhead=True,language='de'):
		params = {
			'doctype': doctype,
			'name': name,
			'format': print_format,
                        '_lang':language,
			'no_letterhead': int(not bool(letterhead))
		}
		response = self.session_get(
			self.url + '/api/method/frappe.utils.print_format.download_pdf',
			params=params, stream=True)

		return self.post_process_file_stream(response)

	def get_html(self, doctype, name, print_format='Standard', letterhead=True):
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

	def __load_downloadable_templates(self):
		self.can_download = self.get_api('frappe.core.page.data_import_tool.data_import_tool.get_doctypes')

	def get_upload_template(self, doctype, with_data=False):
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

	def attach_file(self,doctype,docname,filename,filedata,is_private):
		params = {
			'cmd': 'frappe.client.attach_file',
			'doctype': doctype,
			'docname': docname,
			'filename': filename,
                        'filedata': b64encode(filedata),
                        'is_private': 1 if is_private else 0,
                        'decode_base64': 1
		}
		return self.post_request(params)

	def read_and_attach_file(self,doctype,docname,filename,is_private):
            basename = os.path.basename(filename)
            filedata = open(filename,"rb").read()
            return self.attach_file(doctype,docname,basename,filedata,is_private)

	def query_report(self,report_name="",filters=None):
		params = {}
		if filters:
			params["filters"] = json.dumps(filters)
		params['report_name'] = report_name
		return self.get_api('frappe.desk.query_report.run',params)

	def get_file(self, path):
		'''Returns a file from the file system'''
		return self.session_get(self.url + path).content

	def get_attachments(self, doctype, name):
		'''Returns attachments to a document'''
		params = {
			'doctype': doctype,
			'name' : name,
		}
		res = self.session_get(self.url + "/api/resource/" + doctype + "/" + name + "?run_method=frappe.core.doctype.file.file.get_attached_images",
			params=params)
		return self.post_process(res)

	def get_unreconciled_entries(self,name):
		res = self.session_get(self.url + '/api/resource/' + 'Payment Reconciliation' + '/' + name)

		return self.post_process(res)

	def get_api(self, method, params=None):
		if params is None:
			params = {}
		res = self.session.get(
			f"{self.url}/api/method/{method}", params=params, verify=self.verify, headers=self.headers
		)
		return self.post_process(res)

	def post_api(self, method, params=None):
		if params is None:
			params = {}
		res = self.session.post(
			f"{self.url}/api/method/{method}", params=params, verify=self.verify, headers=self.headers
		)
		return self.post_process(res)

	def get_request(self, params):
		res = self.session.get(
			self.url, params=self.preprocess(params), verify=self.verify, headers=self.headers
		)
		res = self.post_process(res)
		return res

	def post_request(self, data):
		res = self.session.post(
			self.url, data=self.preprocess(data), verify=self.verify, headers=self.headers
		)
		res = self.post_process(res)
		return res

	def session_get(self,*args,**kwargs):
		res = None
		while res is None:
			try:
				res = self.session.get(*args,**kwargs)
			except requests.exceptions.ConnectionError as e:
				# too many API calls can cause problems
				print("Warnung: API-Verbindungsproblem")
				time.sleep(1)
		return res


	def preprocess(self, params):
		"""convert dicts, lists to json"""
		for key, value in params.items():
			if isinstance(value, (dict, list)):
				params[key] = json.dumps(value)

		return params

	def post_process(self, response):
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
		if "message" in rjson:
			return rjson["message"]
		elif "data" in rjson:
			return rjson["data"]
		else:
			return None

	def post_process_file_stream(self, response):
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
