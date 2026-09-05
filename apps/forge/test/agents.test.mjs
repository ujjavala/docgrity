/**
 * agents.js tests — typed-JSON validation (clamping, whitelists, filtering),
 * prompt-injection guards in prompts, versioning, and storage-HTML escaping.
 */
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { __kvs } from '@forge/kvs';
import { __setFetch } from '@forge/api';
import {
  PROMPTS,
  assessDuplicate,
  assessContradiction,
  assessOpenQuestions,
  commentToStorageHtml,
} from '../src/agents.js';

const pageA = { title: 'Page A', text: 'Deploys use Node 22.' };
const pageB = { title: 'Page B', text: 'Deploys use Node 16.' };

function configure() {
  __kvs.store.set('llm-settings', {
    provider: 'gemini',
    model: 'gemini-2.5-flash',
    embeddingModel: 'gemini-embedding-001',
  });
  __kvs.secrets.set('llm-api-key-gemini', 'k');
}

const modelReturns = (obj) =>
  __setFetch(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ candidates: [{ content: { parts: [{ text: JSON.stringify(obj) }] } }] }),
  }));

beforeEach(() => {
  __kvs.reset();
  configure();
});

test('every prompt is versioned and hardens against prompt injection', () => {
  for (const [name, p] of Object.entries(PROMPTS)) {
    assert.match(p.version, /^v\d+$/, `${name} must have a version`);
    assert.match(p.system, /untrusted|ignore any i?nstructions/i, `${name} must treat content as untrusted`);
  }
});

test('assessDuplicate clamps confidence and filters empty evidence', async () => {
  modelReturns({
    is_duplicate: 'yes', // truthy coercion
    confidence: 42, // out of range
    summary: 'Same content',
    recommended_action: 'MERGE',
    evidence: [
      { page: 'A', excerpt: 'Deploys use Node 22.' },
      { page: 'B', excerpt: '' }, // dropped
      { page: 'X', excerpt: 'weird page id' }, // coerced to A
    ],
  });
  const { output, model, promptVersion } = await assessDuplicate(pageA, pageB);
  assert.equal(output.is_duplicate, true);
  assert.equal(output.confidence, 1);
  assert.equal(output.evidence.length, 2);
  assert.equal(output.evidence[1].page, 'A');
  assert.equal(model, 'gemini:gemini-2.5-flash');
  assert.equal(promptVersion, PROMPTS.duplicate.version);
});

test('assessContradiction whitelists severity and coerces claims', async () => {
  modelReturns({
    is_contradiction: true,
    confidence: 0.9,
    severity: 'CATASTROPHIC', // not in whitelist
    summary: 'Node version conflict',
    conflicting_claims: 'not-an-array',
    evidence: [{ page: 'A', excerpt: 'Node 22' }],
  });
  const { output } = await assessContradiction(pageA, pageB);
  assert.equal(output.severity, 'MEDIUM');
  assert.deepEqual(output.conflicting_claims, []);
});

test('assessOpenQuestions drops questions without excerpt or question text', async () => {
  modelReturns({
    questions: [
      { question: 'Who owns sharding?', excerpt: 'TBD: sharding', confidence: 0.8, severity: 'HIGH' },
      { question: '', excerpt: 'orphan excerpt', confidence: 0.9 },
      { question: 'No excerpt', excerpt: '', confidence: 0.9 },
    ],
  });
  const { output } = await assessOpenQuestions({ title: 'Notes', text: 'TBD: sharding' });
  assert.equal(output.questions.length, 1);
  assert.equal(output.questions[0].severity, 'HIGH');
});

test('commentToStorageHtml escapes HTML (stored-XSS guard)', () => {
  const html = commentToStorageHtml(
    { paragraphs: ['<script>alert(1)</script> & "quotes"'] },
    [{ url: 'https://x.test/page?a=1&b=2', title: '<b>Title</b>' }],
    [{ account_id: 'abc"><evil' }]
  );
  assert.ok(!html.includes('<script>'), 'script tag not escaped');
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('a=1&amp;b=2'));
  assert.ok(html.includes('&lt;b&gt;Title&lt;/b&gt;'));
  assert.ok(html.includes('abc&quot;&gt;&lt;evil'));
});

test('commentToStorageHtml dedupes page links and skips owners without account_id', () => {
  const html = commentToStorageHtml(
    { paragraphs: ['p'] },
    [
      { url: 'https://x.test/1', title: 'One' },
      { url: 'https://x.test/1', title: 'One again' },
    ],
    [{ display_name: 'No id' }]
  );
  assert.equal((html.match(/<a /g) ?? []).length, 1);
  assert.ok(!html.includes('ri:user'));
});
