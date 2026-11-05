import { ErpNext, loadMaterial, KNOWLEDGE_FILE } from './lib/erpnext.js';
import { Knowledge } from './lib/material.js';

const KEYS = ['server', 'apiKey', 'apiSecret', 'claudeKey', 'model', 'sender', 'name'];
const storage = messenger.storage.local;
const status = document.getElementById('status');

function values() {
  const out = {};
  for (const k of KEYS) out[k] = document.getElementById(k).value.trim();
  out.server = out.server.replace(/\/+$/, '');
  return out;
}

async function requestServerPermission(server) {
  if (!server) return true;
  const origin = new URL(server).origin + '/*';
  return messenger.permissions.request({ origins: [origin] });
}

async function save() {
  const v = values();
  const ok = await requestServerPermission(v.server);
  await storage.set(v);
  status.textContent = ok ? 'Gespeichert.' : 'Gespeichert, aber der Zugriff auf den Server wurde nicht erlaubt.';
}

async function test() {
  const v = values();
  try {
    const erp = new ErpNext(v.server, v.apiKey, v.apiSecret);
    const user = await erp.loggedUser();
    const file = await erp.materialFile(KNOWLEDGE_FILE);
    status.textContent = `ERPNext: angemeldet als ${user}. Wissensdatei: ${file ? 'vorhanden, Stand ' + file.modified : 'FEHLT'}.`;
  } catch (e) {
    status.textContent = 'Fehler: ' + (e.message || e);
  }
}

async function reload() {
  const v = values();
  try {
    await storage.remove('material');
    const material = await loadMaterial(new ErpNext(v.server, v.apiKey, v.apiSecret), storage);
    const k = new Knowledge(material.knowledgeText);
    status.textContent = `Geladen: Wissensdatei (${k.answers.length} Musterantworten, Stand ${material.knowledgeModified}), ` +
      `Korpus mit ${(material.corpus || []).length} Antwortpaaren.`;
  } catch (e) {
    status.textContent = 'Fehler: ' + (e.message || e);
  }
}

(async () => {
  const s = await storage.get(KEYS);
  for (const k of KEYS) document.getElementById(k).value = s[k] || '';
  document.getElementById('save').addEventListener('click', save);
  document.getElementById('test').addEventListener('click', test);
  document.getElementById('reload').addEventListener('click', reload);
})();
