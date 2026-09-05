/**
 * heuristics.js quality tests — precision (false positives), recall
 * (false negatives, including DOCUMENTED limitations), and confidence
 * calibration against the scan thresholds (duplicateConfidence 0.75,
 * openQuestionConfidence 0.7).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  HEURISTIC_MODEL,
  heuristicAssessDuplicate,
  heuristicAssessOpenQuestions,
  lexicalSimilarity,
} from '../src/heuristics.js';

const DUP_THRESHOLD = 0.75; // scans.js DEFAULT_THRESHOLDS.duplicateConfidence
const OQ_THRESHOLD = 0.7; // scans.js DEFAULT_THRESHOLDS.openQuestionConfidence

const page = (title, text) => ({ id: title, title, text });

const RUNBOOK = `The payments service runs in the prod-east cluster behind the API gateway.
To restart the service, run kubectl rollout restart deployment payments in the prod namespace.
Alerts are routed to the payments-oncall channel via Opsgenie.
The SLA for incident response is 4 hours during business hours.
Database credentials are rotated every 90 days by the platform team.
Escalate to the platform team if the rollout does not complete within 10 minutes.`;

/* ---------- Duplicates: true positives ---------- */

test('duplicate: exact copy detected with very high confidence and evidence', () => {
  const { output, model, promptVersion } = heuristicAssessDuplicate(
    page('Runbook', RUNBOOK),
    page('Runbook (copy)', RUNBOOK)
  );
  assert.equal(model, HEURISTIC_MODEL);
  assert.equal(promptVersion, HEURISTIC_MODEL);
  assert.ok(output.is_duplicate);
  assert.ok(output.confidence >= 0.95, `confidence ${output.confidence} should be >= 0.95`);
  assert.ok(output.evidence.length > 0, 'evidence required');
  // Evidence excerpts must be real text from the pages (findings need evidence).
  for (const ev of output.evidence) assert.ok(RUNBOOK.includes(ev.excerpt));
  assert.match(output.summary, /heuristics/i);
});

test('duplicate: lightly edited copy still detected above the scan threshold', () => {
  const edited = RUNBOOK.replace('prod-east', 'prod-west').replace('4 hours', 'four hours');
  const { output } = heuristicAssessDuplicate(page('A', RUNBOOK), page('B', edited));
  assert.ok(output.is_duplicate);
  assert.ok(
    output.confidence >= DUP_THRESHOLD,
    `edited copy confidence ${output.confidence} fell below scan threshold ${DUP_THRESHOLD}`
  );
  assert.ok(output.evidence.length > 0);
});

test('duplicate: section copied into a much larger page (containment) → MERGE', () => {
  const bigPage = `This page documents the whole payments platform architecture.
It covers ingestion, ledger, reconciliation and reporting subsystems in detail.
The ledger is an append-only event store partitioned by merchant identifier.
Reconciliation jobs run nightly and compare the ledger against bank statements.
${RUNBOOK}
Reporting dashboards are refreshed hourly from the analytics warehouse.
Access to dashboards requires membership of the finance-analytics group.`;
  const { output } = heuristicAssessDuplicate(page('Big', bigPage), page('Small', RUNBOOK));
  assert.ok(output.is_duplicate);
  assert.ok(output.confidence >= DUP_THRESHOLD);
  assert.equal(output.recommended_action, 'MERGE');
});

/* ---------- Duplicates: false-positive guards ---------- */

test('duplicate FP guard: unrelated pages score near zero', () => {
  const other = `The marketing site is a static Next.js build deployed to the CDN.
Blog posts are written in MDX and reviewed by the content team before publishing.
Brand colours and typography are defined in the design tokens package.
Campaign landing pages are created from the launch template in Figma.`;
  const { output } = heuristicAssessDuplicate(page('A', RUNBOOK), page('B', other));
  assert.equal(output.is_duplicate, false);
  assert.ok(output.confidence < 0.2, `unrelated confidence ${output.confidence} should be < 0.2`);
});

test('duplicate FP guard: same topic, different content stays below threshold', () => {
  const sameTopic = `The payments service exposes a REST API for charge creation and refunds.
Merchants authenticate with signed JWTs issued by the identity service.
Webhooks notify merchants of settlement events within thirty seconds.
Rate limits are enforced per merchant at one hundred requests per second.`;
  const { output } = heuristicAssessDuplicate(page('A', RUNBOOK), page('B', sameTopic));
  assert.ok(
    output.confidence < DUP_THRESHOLD,
    `same-topic pages must not be flagged as duplicates (got ${output.confidence})`
  );
});

test('duplicate FP guard: tiny quoted snippet inside a big page is not a full duplicate', () => {
  const bigPage = `${'Completely different operational content about the search cluster. '.repeat(
    40
  )} As the runbook says: "Alerts are routed to the payments-oncall channel via Opsgenie."`;
  const snippet = 'Alerts are routed to the payments-oncall channel via Opsgenie.';
  const { output } = heuristicAssessDuplicate(page('Big', bigPage), page('Quote', snippet));
  // One shared sentence: containment is high for the tiny page but the 0.9
  // discount + short shingle set must keep it from a confident duplicate call.
  assert.ok(output.confidence <= 0.95);
});

/* ---------- Duplicates: documented false negatives ---------- */

test('duplicate FN (documented limitation): full paraphrase is NOT detected', () => {
  const paraphrase = `Payments lives on the eastern production Kubernetes environment, sitting
behind our gateway layer. Restarting it means issuing a rollout restart against the payments
deployment. On-call notifications go through Opsgenie into the payments on-call room.
We promise a four-hour response window inside working hours. The platform crew rotates the
database passwords quarterly. If a rollout stalls past ten minutes, page the platform crew.`;
  const { output } = heuristicAssessDuplicate(page('A', RUNBOOK), page('B', paraphrase));
  // This is the designed trade-off of no-AI mode: lexical matching cannot see
  // semantic equivalence. Assert it explicitly so the limitation is pinned.
  assert.equal(output.is_duplicate, false);
});

/* ---------- Duplicates: confidence calibration ---------- */

test('duplicate confidence is monotonic: exact > edited > same-topic > unrelated', () => {
  const exact = heuristicAssessDuplicate(page('A', RUNBOOK), page('B', RUNBOOK)).output.confidence;
  const edited = heuristicAssessDuplicate(
    page('A', RUNBOOK),
    page('B', RUNBOOK.replace('prod-east', 'prod-west'))
  ).output.confidence;
  const sameTopic = heuristicAssessDuplicate(
    page('A', RUNBOOK),
    page('B', 'The payments service exposes a REST API for charge creation and refunds.')
  ).output.confidence;
  const unrelated = heuristicAssessDuplicate(
    page('A', RUNBOOK),
    page('B', 'Brand colours and typography live in the design tokens package.')
  ).output.confidence;
  assert.ok(exact >= edited, `${exact} >= ${edited}`);
  assert.ok(edited > sameTopic, `${edited} > ${sameTopic}`);
  assert.ok(sameTopic >= unrelated, `${sameTopic} >= ${unrelated}`);
  assert.ok(exact <= 0.98, 'confidence is capped below 1 — heuristics are never certain');
});

test('duplicate: empty or whitespace pages never crash and never match', () => {
  const { output } = heuristicAssessDuplicate(page('A', ''), page('B', '   '));
  assert.equal(output.is_duplicate, false);
  assert.equal(output.confidence, 0);
  assert.deepEqual(lexicalSimilarity('', 'anything at all here'), { jaccard: 0, containment: 0 });
});

/* ---------- Open questions: true positives ---------- */

test('open questions: explicit markers detected above the scan threshold', () => {
  const { output, model } = heuristicAssessOpenQuestions(
    page(
      'Design doc',
      `The ingestion flow is TODO: describe retry semantics.
Capacity planning is TBD after the load test.
FIXME the diagram below is out of date.
What is the failover behaviour???`
    )
  );
  assert.equal(model, HEURISTIC_MODEL);
  const kept = output.questions.filter((q) => q.confidence >= OQ_THRESHOLD);
  assert.equal(kept.length, 4, `expected 4 marker findings, got ${kept.length}`);
  for (const q of kept) {
    assert.ok(q.confidence >= 0.9);
    assert.ok(q.excerpt.length > 0, 'every question needs evidence');
  }
});

test('open questions: unfilled template placeholders detected', () => {
  const { output } = heuristicAssessOpenQuestions(
    page(
      'Onboarding',
      `Welcome to the team, {new starter name}.
Your buddy is [TBD] and your first project is <insert project here>.`
    )
  );
  const kept = output.questions.filter((q) => q.confidence >= OQ_THRESHOLD);
  assert.ok(kept.length >= 2, `expected >=2 placeholder findings, got ${kept.length}`);
});

test('open questions: genuine uncertainty questions detected via cues', () => {
  const { output } = heuristicAssessOpenQuestions(
    page(
      'ADR',
      `We chose Postgres for the ledger.
Should we retire the v1 API before the migration?
Who owns the reconciliation job after the re-org?`
    )
  );
  const kept = output.questions.filter((q) => q.confidence >= OQ_THRESHOLD);
  assert.equal(kept.length, 2);
  for (const q of kept) assert.equal(q.confidence, 0.75);
});

/* ---------- Open questions: false-positive guards ---------- */

test('open questions FP guard: FAQ headings score below the scan threshold', () => {
  const { output } = heuristicAssessOpenQuestions(
    page(
      'FAQ',
      `How do I reset my password?
Where can I find the holiday calendar?
Contact IT support for anything else.`
    )
  );
  // Surfaced with low confidence, but the scan-level filter must drop them.
  const kept = output.questions.filter((q) => q.confidence >= OQ_THRESHOLD);
  assert.equal(kept.length, 0, 'FAQ headings must not become findings at default thresholds');
  assert.ok(output.questions.every((q) => q.confidence <= 0.5));
});

test('open questions FP guard: plain prose yields no findings', () => {
  const { output } = heuristicAssessOpenQuestions(page('Runbook', RUNBOOK));
  const kept = output.questions.filter((q) => q.confidence >= OQ_THRESHOLD);
  assert.equal(kept.length, 0);
});

test('open questions: repeated identical sentence is deduplicated', () => {
  const { output } = heuristicAssessOpenQuestions(
    page('Doc', 'Capacity is TBD.\nCapacity is TBD.\nCapacity is TBD.')
  );
  assert.equal(output.questions.length, 1);
});
