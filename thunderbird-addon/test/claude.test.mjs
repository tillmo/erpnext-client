// node --test thunderbird-addon/test/claude.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { complete, networkError } from '../lib/claude.js';
import { ErpNext } from '../lib/erpnext.js';

const realFetch = globalThis.fetch;

test('claude: network failure and API error become one sentence', async (t) => {
  t.after(() => { globalThis.fetch = realFetch; });
  globalThis.fetch = async () => { throw new TypeError('NetworkError when attempting to fetch resource.'); };
  await assert.rejects(complete('k', {}), /^Error: Claude nicht erreichbar: NetworkError/);
  globalThis.fetch = async () => ({ ok: false, status: 529, json: async () => ({ error: { message: 'Overloaded' } }) });
  await assert.rejects(complete('k', {}), /^Error: Claude 529: Overloaded$/);
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ content: [{ type: 'text', text: ' Hallo ' }], usage: {}, model: 'm' }) });
  assert.equal((await complete('k', {})).text, 'Hallo');
});

test('claude: timeout', async (t) => {
  t.after(() => { globalThis.fetch = realFetch; });
  // AbortSignal.timeout's timer does not keep node alive, so the mock holds its own timer.
  globalThis.fetch = (url, { signal }) => new Promise((_, reject) => {
    const keep = setTimeout(() => reject(new Error('nicht abgebrochen')), 5000);
    signal.addEventListener('abort', () => { clearTimeout(keep); reject(signal.reason); });
  });
  await assert.rejects(complete('k', {}, 20), /keine Antwort nach 0 s/);
  assert.equal(networkError({ name: 'TimeoutError' }, 180000), 'keine Antwort nach 180 s');
});

test('erpnext: a failed fetch names the usual causes', async (t) => {
  t.after(() => { globalThis.fetch = realFetch; });
  globalThis.fetch = async () => { throw new TypeError('NetworkError when attempting to fetch resource.'); };
  const erp = new ErpNext('https://erp.example.org/', 'k', 's');
  await assert.rejects(erp.loggedUser(), /ERPNext nicht erreichbar bei \/api\/method\/frappe.auth.get_logged_user: NetworkError.*nicht erlaubt/);
  globalThis.fetch = async () => ({ ok: false, status: 403, text: async () => 'Forbidden' });
  await assert.rejects(erp.fileText('/private/files/x.md'), /^Error: ERPNext 403 beim Laden von \/private\/files\/x.md$/);
});
