// node --test thunderbird-addon/test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as m from '../lib/material.js';
import { loadMaterial } from '../lib/erpnext.js';

const KNOWLEDGE = `# Wissensdatei

## 1. Tonfall und Form
Duzen ist die Regel.

## 2. Fakten und Standardangaben
Abholung in der Schongauer Str. 7.

## 3. Standardantworten je Anliegen

### 3.1 Anfrage Balkonkraftwerk
Aufbau: Dank, Fotos erbitten, Preise nennen.

### 3.2 Terminabsprache
Termin bestätigen, Handynummer nennen.

## 4. Was das Team üblicherweise zurückfragt
Fotos vom Balkon.

## 5. Unklar
Prüfliste.
`;

test('addresses', () => {
  assert.equal(m.addressOf('Anna Meier <Anna@Example.org>'), 'anna@example.org');
  assert.equal(m.nameOf('"Meier, Anna" <anna@example.org>'), 'Meier, Anna');
  assert.equal(m.nameOf('anna@example.org'), '');
  assert.equal(m.domainOf('x@mail.bremer-solidarstrom.de'), 'bremer-solidarstrom.de');
  assert.ok(m.isTeam('mia.muster@bremer-solidarstrom.de'));
  assert.ok(m.isExternal('anna@example.org'));
  assert.ok(!m.isExternal('noreply@shop.example.org'));
  assert.equal(m.nameFromAddress('mia.muster@bremer-solidarstrom.de'), 'Mia Muster');
});

test('quotes and signatures', () => {
  assert.equal(m.stripQuotes('Hi,\npasst.\nAm 18.08.25 um 11:42 schrieb\nAnna:\n> alt'), 'Hi,\npasst.');
  assert.equal(m.stripQuotes('Moin\nVon: X <x@y.de>\nGesendet: Montag\nAn: z'), 'Moin');
  assert.equal(m.stripQuotes('Von: Max\nE-Mail: max@example.org'), 'Von: Max\nE-Mail: max@example.org');
  assert.equal(m.stripSignature('Hi\n-- \nMia Muster\nBremer SolidarStrom'), 'Hi');
  assert.equal(m.stripSignature('Hi\nSonnige Grüße\nM. Eng. Mia Muster\nBremer SolidarStrom\nTel', ['Mia Muster']), 'Hi\nSonnige Grüße');
  assert.equal(m.htmlToText('<style>x{}</style><p>Hallo,<br>Zeile &amp; 2</p><div>drei</div>'), 'Hallo,\nZeile & 2\ndrei');
  assert.equal(m.ownText({ content: '<p>Hallo<br>LG Mia</p><p>Mia Muster<br>Bremer SolidarStrom</p>',
    sender: 'mia.muster@bremer-solidarstrom.de', sender_full_name: '' }), 'Hallo\nLG Mia');
});

test('knowledge sections and matching', () => {
  const k = new m.Knowledge(KNOWLEDGE);
  assert.ok(k.stable.includes('## 1. Tonfall') && k.stable.includes('## 4. Was') && !k.stable.includes('Prüfliste'));
  assert.deepEqual(k.answers.map(a => a[0]), ['3.1 Anfrage Balkonkraftwerk', '3.2 Terminabsprache']);
  assert.equal(k.matchingAnswers('Anfrage Balkonkraftwerk Preise')[0][0], '3.1 Anfrage Balkonkraftwerk');
  assert.deepEqual(k.matchingAnswers('xyz'), []);
});

test('similar examples prefer the author', () => {
  const corpus = [
    { question: 'Was kostet ein Balkonkraftwerk mit zwei Modulen?', answer: 'A', author: 'x@bremer-solidarstrom.de' },
    { question: 'Was kostet ein Balkonkraftwerk mit zwei Modulen?', answer: 'B', author: 'mia@bremer-solidarstrom.de' },
    { question: 'Rechnung für die Solaranlage', answer: 'C', author: 'mia@bremer-solidarstrom.de' },
  ];
  assert.deepEqual(m.similarExamples(corpus, 'Balkonkraftwerk kostet Module', 'mia@bremer-solidarstrom.de', 2).map(e => e.answer), ['B', 'A']);
});

test('prompt and request', () => {
  const mail = { name: 'displayed', sender: 'Anna Meier <anna@example.org>', sender_full_name: 'Anna Meier',
    subject: 'Balkonkraftwerk', communication_date: '2026-03-01 10:00:00', content: 'Was kostet ein Balkonkraftwerk?' };
  const earlier = { name: 'c0', sender: 'mia.muster@bremer-solidarstrom.de', sender_full_name: 'Mia Muster',
    subject: 'Re: Hallo', communication_date: '2026-02-01 10:00:00', content: '<p>Frühere Mail</p>' };
  const req = m.claudeRequest('m', new m.Knowledge(KNOWLEDGE), mail, [earlier], [{ date: '2026-01-01', question: 'Balkonkraftwerk Preis', answer: 'A', author_name: 'Mia Muster' }], 'mia.muster@bremer-solidarstrom.de', 'Mia');
  assert.equal(req.model, 'm');
  assert.equal(req.system[0].text, m.SYSTEM);
  assert.deepEqual(req.system[1].cache_control, { type: 'ephemeral', ttl: '1h' });
  const prompt = req.messages[0].content;
  assert.ok(prompt.includes('### 3.1 Anfrage Balkonkraftwerk'));
  assert.ok(prompt.includes('Antwort von Mia:\nA'));
  assert.ok(prompt.includes('# Bisheriger Verlauf mit anna@example.org') && prompt.includes('Team (Mia Muster) am 2026-02-01'));
  assert.ok(prompt.includes('Von: Anna Meier <anna@example.org>') && prompt.endsWith('Schreibe die Antwort als Mia.'));
});

test('draft html', () => {
  assert.equal(m.draftHtml('Hallo Anna,\n\nja & nein.\n- a\n\nLG\nMia'), '<p>Hallo Anna,</p><p>ja &amp; nein.<br>- a</p><p>LG<br>Mia</p>');
  assert.equal(m.hintHtml('a < b'), '<p style="color:#b00000;border:1px solid #b00000;padding:.4em">a &lt; b</p>');
});

test('material cache', async () => {
  const store = {};
  const storage = { get: async () => ({ ...store }), set: async (v) => Object.assign(store, v), remove: async (k) => delete store[k] };
  let fetched = 0;
  const erp = {
    materialFile: async (name) => ({ file_url: '/private/files/' + name, modified: '2026-11-05 10:00:00' }),
    fileText: async (url) => { fetched++; return url.endsWith('.json') ? '[{"question":"q"}]' : '# Wissensdatei\n## 1. Ton\nx'; },
  };
  const first = await loadMaterial(erp, storage, 1000);
  assert.equal(first.corpus.length, 1);
  assert.equal(fetched, 2);
  await loadMaterial(erp, storage, 2000);                       // fresh: no fetch
  assert.equal(fetched, 2);
  await loadMaterial(erp, storage, 1000 + 25 * 3600 * 1000);     // stale but unchanged: only the File rows
  assert.equal(fetched, 2);
  erp.materialFile = async (name) => ({ file_url: '/private/files/' + name, modified: '2026-11-06 10:00:00' });
  await loadMaterial(erp, storage, 1000 + 50 * 3600 * 1000);     // changed: reloaded
  assert.equal(fetched, 4);
});
