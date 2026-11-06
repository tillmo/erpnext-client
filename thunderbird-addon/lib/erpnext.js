// ERPNext REST access with the user's API key: the conversation with an address and the private
// files that hold the knowledge file and the reply corpus (uploaded by reply_material_upload.py).

import { networkError } from './claude.js';

export const FIELDS = ['name', 'sender', 'sender_full_name', 'recipients', 'subject', 'content',
  'communication_date', 'reference_doctype', 'reference_name'];
export const THREAD_MAILS = 12;
export const MATERIAL_FOLDER = 'Home/Antworten';
export const KNOWLEDGE_FILE = 'reply-knowledge.md';
export const CORPUS_FILE = 'reply-corpus.json';
export const MATERIAL_MAX_AGE_MS = 24 * 3600 * 1000;
export const TIMEOUT_MS = 60 * 1000;          // one REST call
export const FILE_TIMEOUT_MS = 300 * 1000;    // the corpus is a few MB

// A fetch() that fails before a response (no network, no permission for the origin, timeout)
// raises a TypeError with little information; say what it usually means.
async function fetchOrExplain(url, options, timeoutMs, what) {
  try {
    return await fetch(url, { ...options, signal: AbortSignal.timeout(timeoutMs) });
  } catch (e) {
    throw new Error(`ERPNext nicht erreichbar ${what}: ${networkError(e, timeoutMs)}` +
      (e && e.name === 'TypeError' ? ' (Server falsch, offline, oder der Zugriff auf den Server ist dem Add-on nicht erlaubt: ' +
        'in den Add-on-Einstellungen „Speichern“ drücken)' : ''));
  }
}

export class ErpNext {
  constructor(server, key, secret) {
    this.server = server.replace(/\/+$/, '');
    this.headers = { Authorization: `token ${key}:${secret}`, Accept: 'application/json' };
  }

  async get(path, params = {}) {
    const url = new URL(this.server + path);
    for (const [k, v] of Object.entries(params)) url.searchParams.set(k, typeof v === 'string' ? v : JSON.stringify(v));
    const r = await fetchOrExplain(url, { headers: this.headers }, TIMEOUT_MS, `bei ${path}`);
    if (!r.ok) throw new Error(`ERPNext ${r.status} bei ${path}: ${(await r.text()).slice(0, 200)}`);
    return r.json();
  }

  async getList(doctype, fields, filters, extra = {}) {
    const data = await this.get(`/api/resource/${encodeURIComponent(doctype)}`, { fields, filters, ...extra });
    return data.data || [];
  }

  async loggedUser() {
    return (await this.get('/api/method/frappe.auth.get_logged_user')).message;
  }

  // The last mails exchanged with the address (sent by or to it), oldest first; with `until`
  // only mails up to that date, so that a reply to an older mail does not use what came later.
  async conversation(address, limit = THREAD_MAILS, until = '') {
    const common = { order_by: 'communication_date desc', limit_page_length: String(limit) };
    const sent = await this.getList('Communication', FIELDS,
      [['communication_type', '=', 'Communication'], ['sender', 'like', `%${address}%`]], common);
    const received = await this.getList('Communication', FIELDS,
      [['communication_type', '=', 'Communication'], ['recipients', 'like', `%${address}%`]], common);
    const byName = new Map();
    for (const m of [...sent, ...received]) byName.set(m.name, m);
    let ordered = [...byName.values()].sort((a, b) => (a.communication_date || '').localeCompare(b.communication_date || ''));
    if (until) ordered = ordered.filter(m => (m.communication_date || '') <= until);
    return ordered.slice(-limit);
  }

  // Mails of the address newer than the answered one: the user should know before replying.
  async laterMails(address, after) {
    const all = await this.conversation(address);
    return all.filter(m => (m.communication_date || '') > after && (m.sender || '').toLowerCase().includes(address));
  }

  // Private file by name in the material folder: {file_url, modified} or null.
  async materialFile(fileName) {
    const rows = await this.getList('File', ['name', 'file_url', 'modified'],
      [['file_name', '=', fileName], ['folder', '=', MATERIAL_FOLDER], ['is_private', '=', 1]], { limit_page_length: '1' });
    return rows[0] || null;
  }

  async fileText(fileUrl) {
    const r = await fetchOrExplain(this.server + fileUrl, { headers: this.headers }, FILE_TIMEOUT_MS, `beim Laden von ${fileUrl}`);
    if (!r.ok) throw new Error(`ERPNext ${r.status} beim Laden von ${fileUrl}`);
    return r.text();
  }
}

// Knowledge text and corpus, cached in storage.local for a day (the corpus is a few MB).
export async function loadMaterial(erp, storage, now = Date.now()) {
  const cached = (await storage.get(['material'])).material;
  if (cached && now - cached.loaded < MATERIAL_MAX_AGE_MS) return cached;
  const knowledge = await erp.materialFile(KNOWLEDGE_FILE);
  const corpus = await erp.materialFile(CORPUS_FILE);
  if (!knowledge) throw new Error(`Wissensdatei ${KNOWLEDGE_FILE} fehlt in ERPNext (Ordner ${MATERIAL_FOLDER})`);
  if (cached && cached.knowledgeModified === knowledge.modified && (!corpus || cached.corpusModified === corpus.modified)) {
    cached.loaded = now;
    await storage.set({ material: cached });
    return cached;
  }
  const material = {
    loaded: now,
    knowledgeModified: knowledge.modified,
    knowledgeText: await erp.fileText(knowledge.file_url),
    corpusModified: corpus ? corpus.modified : null,
    corpus: corpus ? JSON.parse(await erp.fileText(corpus.file_url)) : [],
  };
  await storage.set({ material });
  return material;
}
