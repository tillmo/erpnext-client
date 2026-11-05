// One call to the Claude Messages API from the extension (browser-origin request, hence the
// anthropic-dangerous-direct-browser-access header). Returns {text, usage}.

export const API_URL = 'https://api.anthropic.com/v1/messages';
export const DEFAULT_MODEL = 'claude-opus-5-5';

export async function complete(apiKey, request) {
  const r = await fetch(API_URL, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
      'anthropic-dangerous-direct-browser-access': 'true',
    },
    body: JSON.stringify(request),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`Claude ${r.status}: ${(data.error && data.error.message) || 'unbekannter Fehler'}`);
  if (data.stop_reason === 'refusal') throw new Error('Claude hat die Anfrage abgelehnt');
  const text = (data.content || []).filter(b => b.type === 'text').map(b => b.text).join('').trim();
  return { text, usage: data.usage || {}, model: data.model };
}

export function usageText(usage, model) {
  const cached = usage.cache_read_input_tokens || 0;
  const written = usage.cache_creation_input_tokens || 0;
  return `${model}: ${(usage.input_tokens || 0) + cached + written} Eingabe-, ${usage.output_tokens || 0} Ausgabe-Tokens` +
    (cached ? `, ${cached} aus dem Cache` : '') + (written ? `, ${written} in den Cache` : '');
}
