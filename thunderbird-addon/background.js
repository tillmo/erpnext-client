// "Antwort entwerfen" in the message header: draft a reply to the displayed message with Claude
// and open it as a reply (In-Reply-To set by Thunderbird), the draft above the quoted original.

import { ErpNext, loadMaterial } from './lib/erpnext.js';
import { complete, usageText, DEFAULT_MODEL } from './lib/claude.js';
import { Knowledge, claudeRequest, draftHtml, addressOf, nameOf, isExternal, nameFromAddress } from './lib/material.js';

const storage = messenger.storage.local;

async function notify(message, title = 'Antwort entwerfen') {
  await messenger.notifications.create({ type: 'basic', iconUrl: 'icon.svg', title, message });
}

async function settings() {
  const s = await storage.get(['server', 'apiKey', 'apiSecret', 'claudeKey', 'model', 'sender', 'name']);
  const missing = ['server', 'apiKey', 'apiSecret', 'claudeKey', 'sender'].filter(k => !s[k]);
  if (missing.length) throw new Error('Bitte in den Add-on-Einstellungen eintragen: ' + missing.join(', '));
  s.model = s.model || DEFAULT_MODEL;
  s.name = s.name || nameFromAddress(s.sender).split(' ')[0];
  return s;
}

// The displayed message as a Communication-like object: sender, subject, date, text.
async function displayedMail(tab) {
  const header = await messenger.messageDisplay.getDisplayedMessage(tab.id);
  if (!header) throw new Error('Keine Nachricht angezeigt');
  const full = await messenger.messages.getFull(header.id);
  return {
    id: header.id,
    name: 'displayed',
    sender: header.author,
    sender_full_name: nameOf(header.author),
    subject: header.subject,
    communication_date: new Date(header.date).toISOString().replace('T', ' ').slice(0, 19),
    content: bodyOf(full),
  };
}

function bodyOf(part) {
  // Prefer text/plain, else text/html (material.js converts), from the first matching leaf part.
  const leaves = [];
  (function walk(p) { if (p.parts && p.parts.length) p.parts.forEach(walk); else leaves.push(p); })(part);
  const plain = leaves.find(p => (p.contentType || '').startsWith('text/plain') && p.body);
  if (plain) return plain.body;
  const html = leaves.find(p => (p.contentType || '').startsWith('text/html') && p.body);
  return html ? html.body : '';
}

async function draft(tab) {
  const s = await settings();
  const mail = await displayedMail(tab);
  const address = addressOf(mail.sender);
  if (!isExternal(address)) throw new Error(`Absender ${address} ist das Team oder ein Automat`);
  const erp = new ErpNext(s.server, s.apiKey, s.apiSecret);
  const material = await loadMaterial(erp, storage);
  const knowledge = new Knowledge(material.knowledgeText);
  const thread = await erp.conversation(address);
  const request = claudeRequest(s.model, knowledge, mail, thread, material.corpus || [], s.sender, s.name);
  const result = await complete(s.claudeKey, request);
  const composeTab = await messenger.compose.beginReply(mail.id, 'replyToSender');
  const details = await messenger.compose.getComposeDetails(composeTab.id);
  const quoted = details.isPlainText ? '' : (details.body || '');
  await messenger.compose.setComposeDetails(composeTab.id, { isPlainText: false, body: draftHtml(result.text) + quoted });
  console.log('Antwortentwurf', usageText(result.usage, result.model));
}

messenger.messageDisplayAction.onClicked.addListener(async (tab) => {
  try {
    await messenger.messageDisplayAction.disable(tab.id);
    await draft(tab);
  } catch (e) {
    console.error(e);
    await notify(String(e.message || e), 'Antwortentwurf fehlgeschlagen');
  } finally {
    await messenger.messageDisplayAction.enable(tab.id);
  }
});
