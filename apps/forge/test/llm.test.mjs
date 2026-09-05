/**
 * llm.js tests — provider config, secret handling, JSON extraction/retry,
 * and pure math. Run via `npm test` (uses test/loader.mjs Forge stubs).
 */
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { __kvs } from '@forge/kvs';
import { __setFetch } from '@forge/api';
import {
  PROVIDERS,
  cosineSimilarity,
  getLlmSettings,
  saveLlmSettings,
  completeJson,
} from '../src/llm.js';

const geminiOk = (text) => ({
  ok: true,
  status: 200,
  json: async () => ({ candidates: [{ content: { parts: [{ text }] } }] }),
});

function configureGemini() {
  __kvs.store.set('llm-settings', {
    provider: 'gemini',
    model: 'gemini-2.5-flash',
    embeddingModel: 'gemini-embedding-001',
  });
  __kvs.secrets.set('llm-api-key-gemini', 'test-key-123');
}

beforeEach(() => __kvs.reset());

test('cosineSimilarity: identical vectors = 1, orthogonal = 0', () => {
  assert.ok(Math.abs(cosineSimilarity([1, 2, 3], [1, 2, 3]) - 1) < 1e-9);
  assert.equal(cosineSimilarity([1, 0], [0, 1]), 0);
  // zero vector must not divide by zero
  assert.equal(cosineSimilarity([0, 0], [1, 1]), 0);
});

test('saveLlmSettings stores the API key ONLY as a secret, never in settings', async () => {
  await saveLlmSettings({ provider: 'gemini', apiKey: 'sk-very-secret' });
  const settingsJson = JSON.stringify([...__kvs.store.entries()]);
  assert.ok(!settingsJson.includes('sk-very-secret'), 'secret leaked into KVS store');
  assert.equal(__kvs.secrets.get('llm-api-key-gemini'), 'sk-very-secret');
});

test('saveLlmSettings rejects unknown providers', async () => {
  await assert.rejects(() => saveLlmSettings({ provider: 'evil-llm' }), /Unknown provider/);
});

test('saveLlmSettings applies provider default models', async () => {
  await saveLlmSettings({ provider: 'gemini', apiKey: 'k' });
  const s = __kvs.store.get('llm-settings');
  assert.equal(s.model, PROVIDERS.gemini.defaultModel);
  assert.equal(s.embeddingModel, PROVIDERS.gemini.defaultEmbeddingModel);
});

test('getLlmSettings reports hasKey correctly', async () => {
  assert.deepEqual(await getLlmSettings(), { settings: null, hasKey: false });
  configureGemini();
  const { hasKey } = await getLlmSettings();
  assert.equal(hasKey, true);
});

test('completeJson requires configuration', async () => {
  await assert.rejects(() => completeJson({ system: 's', prompt: 'p' }), /LLM not configured/);
});

test('completeJson parses fenced JSON and reports provider:model', async () => {
  configureGemini();
  __setFetch(async () => geminiOk('```json\n{"a": 1}\n```'));
  const { output, model } = await completeJson({ system: 's', prompt: 'p' });
  assert.deepEqual(output, { a: 1 });
  assert.equal(model, 'gemini:gemini-2.5-flash');
});

test('completeJson retries malformed output then succeeds', async () => {
  configureGemini();
  let calls = 0;
  __setFetch(async () => geminiOk(++calls === 1 ? 'not json at all' : '{"ok": true}'));
  const { output } = await completeJson({ system: 's', prompt: 'p' });
  assert.deepEqual(output, { ok: true });
  assert.equal(calls, 2);
});

test('completeJson gives up after maxRetries and never echoes the API key', async () => {
  configureGemini();
  __setFetch(async () => geminiOk('garbage'));
  await assert.rejects(
    () => completeJson({ system: 's', prompt: 'p', maxRetries: 2 }),
    (err) => {
      assert.match(String(err), /invalid JSON after 2 attempts/);
      assert.ok(!String(err).includes('test-key-123'), 'API key leaked in error');
      return true;
    }
  );
});

test('provider error surfaces truncated body without the API key', async () => {
  configureGemini();
  __setFetch(async () => ({
    ok: false,
    status: 400,
    text: async () => 'Bad request: model not found. '.repeat(50),
  }));
  await assert.rejects(
    () => completeJson({ system: 's', prompt: 'p', maxRetries: 1 }),
    (err) => {
      assert.match(String(err), /gemini API error 400/);
      assert.ok(!String(err).includes('test-key-123'));
      return true;
    }
  );
});
