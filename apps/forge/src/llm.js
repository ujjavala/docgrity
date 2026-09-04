/**
 * Provider-agnostic LLM layer (BYO key).
 *
 * The tenant admin picks a provider + model + API key in Docgrity settings
 * (stored as a Forge KVS secret — never in SQL, never logged). Agents ask for
 * capabilities (reason / embed); this module maps them to the configured
 * provider. All output is JSON parsed and shape-checked — never free prose.
 */
import { fetch } from '@forge/api';
import { kvs } from '@forge/kvs';

const SETTINGS_KEY = 'llm-settings'; // {provider, model, embeddingModel}
const SECRET_KEY = 'llm-api-key'; // legacy single-key slot (pre per-provider)

const secretKeyFor = (provider) => `llm-api-key-${provider}`;

/** Stored key for a provider; falls back to the legacy shared slot only when
 * that provider is the currently-selected one (so an old OpenAI key is never
 * sent to Google, etc.). */
async function getProviderKey(provider) {
  const key = await kvs.getSecret(secretKeyFor(provider));
  if (key) return key;
  const settings = await kvs.get(SETTINGS_KEY);
  if (settings?.provider === provider) return kvs.getSecret(SECRET_KEY);
  return null;
}

// `models`/`embeddingModels` here are a static FALLBACK catalog, used only
// until an API key is available — listModels() fetches the live list from
// each provider's /models endpoint.
export const PROVIDERS = {
  gemini: {
    label: 'Google Gemini',
    defaultModel: 'gemini-2.0-flash',
    defaultEmbeddingModel: 'gemini-embedding-001',
    supportsEmbeddings: true,
    models: [
      'gemini-2.5-pro',
      'gemini-2.5-flash',
      'gemini-2.5-flash-lite',
      'gemini-2.0-flash',
      'gemini-2.0-flash-lite',
    ],
    embeddingModels: ['gemini-embedding-001'],
  },
  openai: {
    label: 'OpenAI',
    defaultModel: 'gpt-4o-mini',
    defaultEmbeddingModel: 'text-embedding-3-small',
    supportsEmbeddings: true,
    models: ['gpt-5', 'gpt-5-mini', 'gpt-5-nano', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-4o', 'gpt-4o-mini'],
    embeddingModels: ['text-embedding-3-small', 'text-embedding-3-large'],
  },
  anthropic: {
    label: 'Anthropic Claude',
    defaultModel: 'claude-3-5-haiku-latest',
    defaultEmbeddingModel: null,
    supportsEmbeddings: false,
    models: [
      'claude-sonnet-4-5',
      'claude-opus-4-1',
      'claude-sonnet-4-0',
      'claude-3-7-sonnet-latest',
      'claude-3-5-haiku-latest',
    ],
    embeddingModels: [],
  },
  // DEV ONLY: local Ollama exposed via an HTTPS tunnel (the Forge runtime is
  // HTTPS-only, so http://localhost is not reachable). Run:
  //   cloudflared tunnel --url http://localhost:11434
  // and paste the https URL as the base URL in Settings. Keyless.
  ollama: {
    label: 'Ollama (local dev — via HTTPS tunnel)',
    defaultModel: 'llama3.1:8b',
    defaultEmbeddingModel: 'nomic-embed-text',
    supportsEmbeddings: true,
    keyless: true,
    needsBaseUrl: true,
    models: ['llama3.1:8b', 'llama3.2:3b', 'qwen2.5:7b', 'mistral:7b'],
    embeddingModels: ['nomic-embed-text', 'mxbai-embed-large'],
  },
};

function ollamaBaseUrl(settings) {
  const url = settings?.baseUrl;
  if (!url || !/^https:\/\//.test(url)) {
    throw new Error(
      'Ollama needs an HTTPS base URL (Forge cannot reach http://localhost). Run: cloudflared tunnel --url http://localhost:11434 and paste the https URL in Settings.'
    );
  }
  return url.replace(/\/$/, '');
}

export async function getLlmSettings() {
  const settings = (await kvs.get(SETTINGS_KEY)) ?? null;
  const hasKey = Boolean(
    settings?.provider &&
      (PROVIDERS[settings.provider]?.keyless || (await getProviderKey(settings.provider)))
  );
  return { settings, hasKey };
}

export async function saveLlmSettings({ provider, model, embeddingModel, apiKey, baseUrl }) {
  if (!PROVIDERS[provider]) throw new Error(`Unknown provider: ${provider}`);
  const p = PROVIDERS[provider];
  await kvs.set(SETTINGS_KEY, {
    provider,
    model: model || p.defaultModel,
    embeddingModel: embeddingModel || p.defaultEmbeddingModel,
    ...(p.needsBaseUrl ? { baseUrl: baseUrl || null } : {}),
  });
  if (apiKey) await kvs.setSecret(secretKeyFor(provider), apiKey);
}

async function requireConfig() {
  const settings = await kvs.get(SETTINGS_KEY);
  const keyless = settings && PROVIDERS[settings.provider]?.keyless;
  const apiKey = settings && !keyless ? await getProviderKey(settings.provider) : null;
  if (!settings || (!keyless && !apiKey)) {
    throw new Error('LLM not configured. Set a provider and API key in Docgrity settings.');
  }
  // Self-heal retired embedding models saved by earlier versions.
  if (settings.provider === 'gemini' && settings.embeddingModel === 'text-embedding-004') {
    settings.embeddingModel = 'gemini-embedding-001';
    await kvs.set(SETTINGS_KEY, settings);
  }
  return { ...settings, apiKey };
}

/* ---------- Live model listing ---------- */

/**
 * Fetch the current model list from the provider's own /models API.
 * `apiKey` may be a transient key from the settings form; otherwise the stored
 * secret is used. Falls back to the static catalog if no key or the call fails.
 * Returns {models, embeddingModels, live}.
 */
export async function listModels(provider, apiKey = null) {
  const p = PROVIDERS[provider];
  if (!p) throw new Error(`Unknown provider: ${provider}`);
  const key = apiKey || (await getProviderKey(provider));
  const fallback = { models: p.models, embeddingModels: p.embeddingModels, live: false };
  if (!key && !p.keyless) return fallback;
  try {
    if (provider === 'ollama') {
      const settings = await kvs.get(SETTINGS_KEY);
      const res = await fetch(`${ollamaBaseUrl(settings)}/api/tags`);
      if (!res.ok) throw new Error(`Ollama tags API: ${res.status}`);
      const data = await res.json();
      const names = (data.models ?? []).map((m) => m.name);
      return {
        models: names.filter((n) => !/embed/.test(n)),
        embeddingModels: names.filter((n) => /embed/.test(n)),
        live: true,
      };
    }
    if (provider === 'gemini') {
      const res = await fetch(
        'https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000',
        { headers: { 'x-goog-api-key': key } },
      );
      if (!res.ok) throw new Error(`Gemini models API: ${res.status}`);
      const data = await res.json();
      const all = (data.models ?? []).map((m) => ({
        id: (m.name ?? '').replace(/^models\//, ''),
        methods: m.supportedGenerationMethods ?? [],
      }));
      return {
        models: all
          .filter(
            (m) =>
              m.methods.includes('generateContent') &&
              m.id.startsWith('gemini-') &&
              !/image|tts|transcribe|audio|live|robotics/.test(m.id),
          )
          .map((m) => m.id)
          .sort()
          .reverse(),
        embeddingModels: all
          .filter((m) => m.methods.includes('embedContent'))
          .map((m) => m.id)
          .sort(),
        live: true,
      };
    }
    if (provider === 'openai') {
      const res = await fetch('https://api.openai.com/v1/models', {
        headers: { Authorization: `Bearer ${key}` },
      });
      if (!res.ok) throw new Error(`OpenAI models API: ${res.status}`);
      const data = await res.json();
      const ids = (data.data ?? []).map((m) => m.id);
      const excluded =
        /instruct|embedding|audio|realtime|tts|whisper|transcribe|moderation|image|dall-e|search|davinci|babbage|codex/;
      return {
        models: ids
          .filter((id) => /^(gpt-|o\d)/.test(id) && !excluded.test(id))
          .sort()
          .reverse(),
        embeddingModels: ids.filter((id) => id.includes('embedding')).sort(),
        live: true,
      };
    }
    if (provider === 'anthropic') {
      const res = await fetch('https://api.anthropic.com/v1/models?limit=100', {
        headers: { 'x-api-key': key, 'anthropic-version': '2023-06-01' },
      });
      if (!res.ok) throw new Error(`Anthropic models API: ${res.status}`);
      const data = await res.json();
      return {
        models: (data.data ?? []).map((m) => m.id),
        embeddingModels: [],
        live: true,
      };
    }
    return fallback;
  } catch (err) {
    console.warn(`listModels(${provider}) fell back to static catalog:`, String(err));
    return fallback;
  }
}

/* ---------- Completion (JSON-typed) ---------- */

/**
 * Ask the configured model for a JSON object following `schemaHint`.
 * Retries on malformed output. Returns {output, model}.
 */
export async function completeJson({ system, prompt, validate, maxRetries = 3 }) {
  const cfg = await requireConfig();
  let lastError;
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    const raw = await withRetry(() => complete(cfg, system, prompt));
    try {
      const parsed = JSON.parse(extractJson(raw));
      const output = validate ? validate(parsed) : parsed;
      return { output, model: `${cfg.provider}:${cfg.model}` };
    } catch (err) {
      lastError = err;
    }
  }
  throw new Error(`Model returned invalid JSON after ${maxRetries} attempts: ${lastError}`);
}

function extractJson(text) {
  // Strip markdown fences the model may add despite instructions.
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = fenced ? fenced[1] : text;
  const start = body.indexOf('{');
  const end = body.lastIndexOf('}');
  if (start === -1 || end === -1) throw new Error('no JSON object found');
  return body.slice(start, end + 1);
}

async function complete(cfg, system, prompt) {
  if (cfg.provider === 'gemini') {
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${cfg.model}:generateContent`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-goog-api-key': cfg.apiKey },
        body: JSON.stringify({
          system_instruction: { parts: [{ text: system }] },
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: { responseMimeType: 'application/json' },
        }),
      }
    );
    const data = await checkResponse(res, 'gemini');
    return data.candidates?.[0]?.content?.parts?.[0]?.text ?? '';
  }
  if (cfg.provider === 'openai') {
    const res = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${cfg.apiKey}` },
      body: JSON.stringify({
        model: cfg.model,
        messages: [
          { role: 'system', content: system },
          { role: 'user', content: prompt },
        ],
        response_format: { type: 'json_object' },
      }),
    });
    const data = await checkResponse(res, 'openai');
    return data.choices?.[0]?.message?.content ?? '';
  }
  if (cfg.provider === 'anthropic') {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': cfg.apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: cfg.model,
        max_tokens: 2048,
        system,
        messages: [{ role: 'user', content: prompt }],
      }),
    });
    const data = await checkResponse(res, 'anthropic');
    return data.content?.[0]?.text ?? '';
  }
  if (cfg.provider === 'ollama') {
    const res = await fetch(`${ollamaBaseUrl(cfg)}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: cfg.model,
        messages: [
          { role: 'system', content: system },
          { role: 'user', content: prompt },
        ],
        response_format: { type: 'json_object' },
      }),
    });
    const data = await checkResponse(res, 'ollama');
    return data.choices?.[0]?.message?.content ?? '';
  }
  throw new Error(`Unknown provider: ${cfg.provider}`);
}

/* ---------- Embeddings ---------- */

export async function embed(texts) {
  const cfg = await requireConfig();
  if (cfg.provider === 'gemini') {
    const out = [];
    for (const text of texts) {
      const data = await withRetry(async () => {
        const res = await fetch(
          `https://generativelanguage.googleapis.com/v1beta/models/${cfg.embeddingModel}:embedContent`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'x-goog-api-key': cfg.apiKey },
            body: JSON.stringify({
              content: { parts: [{ text: text.slice(0, 8000) }] },
            }),
          }
        );
        return checkResponse(res, 'gemini');
      });
      out.push(data.embedding.values);
    }
    return out;
  }
  if (cfg.provider === 'openai') {
    const data = await withRetry(async () => {
      const res = await fetch('https://api.openai.com/v1/embeddings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${cfg.apiKey}` },
        body: JSON.stringify({ model: cfg.embeddingModel, input: texts.map((t) => t.slice(0, 8000)) }),
      });
      return checkResponse(res, 'openai');
    });
    return data.data.map((d) => d.embedding);
  }
  if (cfg.provider === 'ollama') {
    const res = await fetch(`${ollamaBaseUrl(cfg)}/api/embed`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: cfg.embeddingModel, input: texts.map((t) => t.slice(0, 8000)) }),
    });
    const data = await checkResponse(res, 'ollama');
    return data.embeddings;
  }
  throw new Error(
    `Provider ${cfg.provider} does not support embeddings; similarity checks are unavailable.`
  );
}

export async function supportsEmbeddings() {
  const settings = await kvs.get(SETTINGS_KEY);
  return Boolean(settings && PROVIDERS[settings.provider]?.supportsEmbeddings);
}

async function checkResponse(res, provider) {
  if (!res.ok) {
    const text = await res.text();
    // Never echo API keys; provider error bodies are safe to log truncated.
    throw new Error(`${provider} API error ${res.status}: ${text.slice(0, 300)}`);
  }
  return res.json();
}

/** Retry rate-limit (429) and transient (5xx) provider errors with backoff. */
async function withRetry(fn, retries = 4) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn();
    } catch (err) {
      const retriable = /API error (429|5\d\d)/.test(String(err));
      if (!retriable || attempt >= retries) throw err;
      await new Promise((r) => setTimeout(r, Math.min(2000 * 2 ** attempt, 30000)));
    }
  }
}

export function cosineSimilarity(a, b) {
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  return dot / (Math.sqrt(na) * Math.sqrt(nb) || 1);
}
