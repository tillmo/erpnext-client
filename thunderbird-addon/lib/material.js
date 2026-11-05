// Pure functions of the reply draft: text of a mail without quotes and signature, the knowledge
// file split into its sections, the choice of matching model answers and similar corpus pairs,
// the prompt for Claude and the HTML of the draft. Ported from reply_corpus.py / reply_draft.py
// of the ERPNext client; no Thunderbird or network access here, so node can test it.

export const OWN_DOMAINS = ['bremer-solidarstrom.de', 'solidarische-oekonomie-bremen.de', 'cafe-sunshine.de'];
export const MODEL_ANSWERS = 3;
export const EXAMPLES = 4;
export const MAX_MAIL_CHARS = 3000;
export const STABLE_SECTIONS = ['1.', '2.', '4.'];

const QUOTE_START = /^\s*(Am .{6,80} schrieb(\s.*)?|On .{6,80} wrote:|-{2,}\s*(Ursprüngliche|Original|Weitergeleitete|Forwarded)\b.*)\s*$/i;
const OUTLOOK_FROM = /^\s*(Von|From):\s*\S/i;
const OUTLOOK_SENT = /^\s*(Gesendet|Sent|Datum|Date):\s*\S/i;
const SIGNATURE_SEPARATOR = /^-- ?$/;
const ORGANISATION = /Bremer SolidarStrom|Solidarische Ökonomie|Café Sunshine/i;
const AUTOMATIC = /mailer-daemon|no-?reply|do-?not-?reply|postmaster|notification|newsletter|mattermost|wordpress|^termine@/i;

const STOPWORDS = new Set(('aber alle also auch bitte dann dass dein deine dem den der des die dies diese doch durch eine ' +
  'einem einen einer eines euch euer eure für gern gerne gibt grüße habe haben hallo hatte ich ihr ihre ihnen ist kann ' +
  'können liebe lieber mal mehr mein meine mich mir mit moin nach nicht noch nur oder schon sehr sein sich sie sind und ' +
  'uns unser unsere viele vielen vom von war was wenn wie wir wird wurde würde zum zur über dank danke freundlichen beste ' +
  'sonnige herzliche solidarstrom bremer solar mail email anfrage').split(' '));

export const SYSTEM = `Du entwirfst E-Mail-Antworten für das Team von Bremer SolidarStrom (Solidarische Ökonomie Bremen e.V.). \
Du schreibst im Namen der Person, die dir genannt wird, in deren Tonfall, wie er in der Wissensdatei und den \
Beispielen zu sehen ist. Regeln:
- Antworte nur mit dem Mailtext: Anrede, Text, Grußformel und Vorname. Kein Betreff, keine Erklärungen, keine Signatur \
mit Adresse (die fügt Thunderbird an).
- Du oder Sie wie im bisherigen Verlauf; bei Erstkontakt wie in der Wissensdatei beschrieben.
- Erfinde keine Fakten, Preise, Termine oder Zusagen. Was nicht in der Wissensdatei, dem Verlauf oder den Beispielen \
steht, formulierst du als Rückfrage oder markierst es mit [bitte prüfen].
- Beantworte alles, was in der Mail gefragt wird, und frage nach, was das Team üblicherweise braucht.
- Kurz und konkret, Aufzählungen bei mehreren Punkten, keine Floskelketten.
- Jeder Absatz ist eine Zeile; Absätze werden durch eine Leerzeile getrennt. Keine Zeilenumbrüche innerhalb eines Absatzes.
- Wenn aus der Mail nicht klar hervorgeht, was die Person will, deute nichts hinein und unterstelle nichts: frage \
freundlich nach, worum es geht. Keine Absage auf Verdacht.`;

// ---- addresses -------------------------------------------------------------------------------
export function addressOf(text) {
  const m = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/.exec(text || '');
  return m ? m[0].toLowerCase() : '';
}

export function nameOf(text) {
  // 'Anna Meier <anna@example.org>' -> 'Anna Meier'; a bare address gives ''.
  const m = /^\s*"?([^"<]+?)"?\s*<[^>]+>\s*$/.exec(text || '');
  return m ? m[1].trim() : '';
}

export function domainOf(address) {
  const addr = addressOf(address);
  const host = addr.split('@')[1] || '';
  return host.split('.').slice(-2).join('.');
}

export function isTeam(address) {
  return OWN_DOMAINS.includes(domainOf(address));
}

export function isExternal(address) {
  const addr = addressOf(address);
  return Boolean(addr) && !isTeam(addr) && !AUTOMATIC.test(addr);
}

export function nameFromAddress(address) {
  const local = addressOf(address).split('@')[0];
  return local.split(/[._-]+/).filter(Boolean).map(p => p[0].toUpperCase() + p.slice(1)).join(' ');
}

// ---- mail text -------------------------------------------------------------------------------
export function stripQuotes(text) {
  const lines = (text || '').replace(/\r/g, '').split('\n');
  const kept = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (QUOTE_START.test(line)) break;
    if (OUTLOOK_FROM.test(line) && lines.slice(i + 1, i + 4).some(l => OUTLOOK_SENT.test(l))) break;
    if (line.trimStart().startsWith('>')) continue;
    kept.push(line.trimEnd());
  }
  return kept.join('\n').trim();
}

export function stripSignature(text, authorNames = []) {
  const lines = text.split('\n');
  const names = authorNames.map(n => (n || '').trim()).filter(Boolean);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (SIGNATURE_SEPARATOR.test(lines[i])) return lines.slice(0, i).join('\n').trim();
    if (names.some(n => line.endsWith(n)) && lines.slice(i + 1, i + 4).some(l => ORGANISATION.test(l))) {
      return lines.slice(0, i).join('\n').trim();
    }
  }
  return text.trim();
}

export function htmlToText(html) {
  // Block elements and <br> become line breaks; tags and entities go. Good enough for mails.
  let t = html || '';
  t = t.replace(/<(style|script)[\s\S]*?<\/\1>/gi, '');
  t = t.replace(/<br\s*\/?>/gi, '\n');
  t = t.replace(/<\/(p|div|tr|li|h[1-6]|blockquote|pre)>/gi, '\n');
  t = t.replace(/<[^>]+>/g, '');
  t = t.replace(/&nbsp;/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'").replace(/&amp;/g, '&');
  return t.split('\n').map(l => l.replace(/[ \t]+/g, ' ').trim()).join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

export function ownText(mail) {
  // mail: {content (html or text), sender, sender_full_name}
  const text = /<[a-z][\s\S]*>/i.test(mail.content || '') ? htmlToText(mail.content) : (mail.content || '');
  return stripSignature(stripQuotes(text), [mail.sender_full_name || '', nameFromAddress(mail.sender)]).slice(0, MAX_MAIL_CHARS);
}

// ---- knowledge file --------------------------------------------------------------------------
function splitOn(text, marker) {
  const parts = text.split(new RegExp('^' + marker, 'm')).slice(1);
  return parts.map(p => {
    const nl = p.indexOf('\n');
    return nl < 0 ? [p.trim(), ''] : [p.slice(0, nl).trim(), p.slice(nl + 1)];
  });
}

export function words(text) {
  const out = new Set();
  for (const w of (text || '').toLowerCase().match(/[a-zäöüß]{4,}/g) || []) {
    if (!STOPWORDS.has(w)) out.add(w);
  }
  return out;
}

export function similarity(a, b) {
  if (!a.size || !b.size) return 0;
  let shared = 0;
  for (const w of a) if (b.has(w)) shared++;
  return shared / (a.size + b.size - shared);
}

export class Knowledge {
  constructor(text) {
    this.stable = '';
    this.answers = [];
    for (const [heading, body] of splitOn(text, '## ')) {
      if (STABLE_SECTIONS.some(s => heading.startsWith(s))) this.stable += '## ' + heading + '\n' + body;
      else if (heading.startsWith('3.')) this.answers = splitOn(body, '### ');
    }
  }

  matchingAnswers(text, n = MODEL_ANSWERS) {
    const request = words(text);
    return this.answers
      .map(([h, b]) => [similarity(request, words(h)) * 3 + similarity(request, words(b)), h, b])
      .filter(s => s[0] > 0)
      .sort((x, y) => y[0] - x[0])
      .slice(0, n)
      .map(s => [s[1], s[2]]);
  }
}

export function similarExamples(entries, text, author = '', n = EXAMPLES) {
  const request = words(text);
  return entries
    .map(e => {
      let score = similarity(request, words(e.question || ''));
      if (score && author && e.author === author) score += 0.1;
      return [score, e];
    })
    .filter(s => s[0] > 0)
    .sort((x, y) => y[0] - x[0])
    .slice(0, n)
    .map(s => s[1]);
}

// ---- prompt ----------------------------------------------------------------------------------
function who(mail) {
  const addr = addressOf(mail.sender);
  const name = mail.sender_full_name || nameOf(mail.sender) || addr;
  return isTeam(addr) ? `Team (${name})` : `Absender*in (${name})`;
}

export function conversationText(mails) {
  return mails.map(m => `--- ${who(m)} am ${(m.communication_date || '').slice(0, 10)}: ${m.subject || ''}\n${ownText(m)}`)
    .join('\n\n');
}

export function userPrompt(mail, thread, answers, examples, authorName) {
  const parts = [];
  if (answers.length) {
    parts.push('# Passende Musterantworten aus der Wissensdatei\n\n' +
      answers.map(([h, b]) => '### ' + h + '\n' + b.trim()).join('\n\n'));
  }
  if (examples.length) {
    parts.push('# Ähnliche frühere Anfragen und die Antworten des Teams\n\n' +
      examples.map(e => `Anfrage (${(e.date || '').slice(0, 10)}):\n${(e.question || '').slice(0, 1500)}\n\n` +
        `Antwort von ${((e.author_name || e.author || '').split(/\s+/)[0])}:\n${e.answer || ''}`).join('\n\n'));
  }
  const earlier = thread.filter(m => m.name !== mail.name);
  if (earlier.length) parts.push(`# Bisheriger Verlauf mit ${addressOf(mail.sender)}\n\n${conversationText(earlier)}`);
  parts.push(`# Zu beantwortende Mail\n\nVon: ${mail.sender_full_name || nameOf(mail.sender)} <${addressOf(mail.sender)}>\n` +
    `Datum: ${(mail.communication_date || '').slice(0, 16)}\nBetreff: ${mail.subject || ''}\n\n${ownText(mail)}`);
  parts.push(`Schreibe die Antwort als ${authorName}.`);
  return parts.join('\n\n');
}

export function claudeRequest(model, knowledge, mail, thread, corpus, author, authorName) {
  const request = (mail.subject || '') + '\n' + ownText(mail);
  return {
    model,
    max_tokens: 2000,
    system: [
      { type: 'text', text: SYSTEM },
      { type: 'text', text: '# Wissensdatei\n\n' + knowledge.stable, cache_control: { type: 'ephemeral', ttl: '1h' } },
    ],
    messages: [{ role: 'user', content: userPrompt(mail, thread, knowledge.matchingAnswers(request),
      similarExamples(corpus, request, author), authorName) }],
  };
}

// ---- draft as HTML -----------------------------------------------------------------------------
export function escapeHtml(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export function draftHtml(text) {
  return text.trim().split(/\n\s*\n/).map(block => '<p>' + escapeHtml(block).replace(/\n/g, '<br>') + '</p>').join('');
}
