// One call to the Claude Messages API from the extension (browser-origin request, hence the
// anthropic-dangerous-direct-browser-access header). Returns {text, usage}.

export const API_URL = 'https://api.anthropic.com/v1/messages';
export const DEFAULT_MODEL = 'claude-opus-5-5';
export const TIMEOUT_MS = 180 * 1000;

export async function complete(apiKey, request, timeoutMs = TIMEOUT_MS) {
  let r;
  try {
    r = await fetch(API_URL, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'anthropic-dangerous-direct-browser-access': 'true',
      },
      body: JSON.stringify(request),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (e) {
    throw new Error('Claude nicht erreichbar: ' + networkError(e, timeoutMs));
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`Claude ${r.status}: ${(data.error && data.error.message) || 'unbekannter Fehler'}`);
  if (data.stop_reason === 'refusal') throw new Error('Claude hat die Anfrage abgelehnt');
  const text = (data.content || []).filter(b => b.type === 'text').map(b => b.text).join('').trim();
  return { text, usage: data.usage || {}, model: data.model };
}

// A fetch() rejection as a sentence: timeout or the browser's network error.
export function networkError(e, timeoutMs) {
  if (e && (e.name === 'TimeoutError' || e.name === 'AbortError')) return `keine Antwort nach ${Math.round(timeoutMs / 1000)} s`;
  return String((e && e.message) || e);
}

export function usageText(usage, model) {
  const cached = usage.cache_read_input_tokens || 0;
  const written = usage.cache_creation_input_tokens || 0;
  return `${model}: ${(usage.input_tokens || 0) + cached + written} Eingabe-, ${usage.output_tokens || 0} Ausgabe-Tokens` +
    (cached ? `, ${cached} aus dem Cache` : '') + (written ? `, ${written} in den Cache` : '');
}
