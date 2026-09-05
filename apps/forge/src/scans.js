/**
 * Scan consumer (async events queue "scans").
 *
 * Deterministic orchestration: ingest pages → candidate selection → LLM
 * assessment (agents.js) → confidence gate → finding + evidence + potential
 * owners → optional policy-gated comment. Every step audited.
 */
import { kvs } from '@forge/kvs';
import {
  assessContradiction,
  assessDuplicate,
  assessOpenQuestions,
  commentToStorageHtml,
  draftComment,
} from './agents';
import {
  addFooterComment,
  getPageVersionAuthor,
  getSiteBaseUrl,
  getUserDisplayName,
  listAllPages,
  storageToText,
} from './confluence';
import { audit, execute, query, uuid } from './db';
import { heuristicAssessDuplicate, heuristicAssessOpenQuestions } from './heuristics';
import { cosineSimilarity, embed, isHeuristicMode, supportsEmbeddings } from './llm';

const DEFAULT_THRESHOLDS = {
  candidateSimilarity: 0.8,
  duplicateConfidence: 0.75,
  contradictionConfidence: 0.75,
  openQuestionConfidence: 0.7,
  maxPairsPerScan: 15,
  // Heuristic comparisons are pure local CPU (no LLM calls), so far more
  // pairs can be assessed per scan.
  maxPairsHeuristic: 400,
};

async function getThresholds() {
  return { ...DEFAULT_THRESHOLDS, ...((await kvs.get('thresholds')) ?? {}) };
}

export const handler = async (event) => {
  const { scanId, check, postComments = false, spaceId = null } = event.body;
  await execute(`UPDATE scan SET status = 'RUNNING', started_at = NOW() WHERE id = ?`, [scanId]);
  const heuristic = await isHeuristicMode();
  await audit({ actor: 'system', eventType: 'scan.started', resourceType: 'scan', resourceId: scanId, detail: { check, postComments, mode: heuristic ? 'heuristic' : 'llm' } });

  const stats = { pages: 0, assessed: 0, findings: 0, mode: heuristic ? 'heuristic' : 'llm' };
  try {
    // Contradiction detection needs semantic reasoning — not possible with
    // built-in heuristics. Complete the scan as skipped so the user sees why.
    if (heuristic && check === 'contradictions') {
      stats.skipped = 'Contradiction detection requires an AI provider (Settings).';
      await execute(
        `UPDATE scan SET status = 'COMPLETED', completed_at = NOW(), stats = ? WHERE id = ?`,
        [JSON.stringify(stats), scanId]
      );
      await audit({ actor: 'system', eventType: 'scan.skipped', resourceType: 'scan', resourceId: scanId, detail: stats });
      return;
    }

    const pages = await ingestPages(spaceId);
    stats.pages = pages.length;
    const thresholds = await getThresholds();

    if (check === 'duplicates') {
      await scanPairs(pages, thresholds, scanId, heuristic ? false : postComments, stats, {
        type: 'DUPLICATE',
        assess: heuristic ? async (a, b) => heuristicAssessDuplicate(a, b) : assessDuplicate,
        accept: (o) => o.is_duplicate && o.evidence.length && o.confidence >= thresholds.duplicateConfidence,
        severity: () => 'MEDIUM',
        action: (o) => o.recommended_action,
        maxPairs: heuristic ? thresholds.maxPairsHeuristic : thresholds.maxPairsPerScan,
      });
    } else if (check === 'contradictions') {
      await scanPairs(pages, thresholds, scanId, postComments, stats, {
        type: 'CONTRADICTION',
        assess: assessContradiction,
        accept: (o) => o.is_contradiction && o.evidence.length && o.confidence >= thresholds.contradictionConfidence,
        severity: (o) => o.severity,
        action: () => 'REVIEW',
      });
    } else if (check === 'open_questions') {
      await scanOpenQuestions(pages, thresholds, scanId, heuristic ? false : postComments, stats, {
        assess: heuristic ? async (page) => heuristicAssessOpenQuestions(page) : assessOpenQuestions,
      });
    }

    await execute(
      `UPDATE scan SET status = 'COMPLETED', completed_at = NOW(), stats = ? WHERE id = ?`,
      [JSON.stringify(stats), scanId]
    );
    await audit({ actor: 'system', eventType: 'scan.completed', resourceType: 'scan', resourceId: scanId, detail: stats });
  } catch (err) {
    console.error('scan failed', err);
    await execute(
      `UPDATE scan SET status = 'FAILED', completed_at = NOW(), error = ?, stats = ? WHERE id = ?`,
      [String(err).slice(0, 2000), JSON.stringify(stats), scanId]
    );
    await audit({ actor: 'system', eventType: 'scan.failed', resourceType: 'scan', resourceId: scanId, detail: { error: String(err).slice(0, 500) } });
  }
};

/* ---------- Ingestion ---------- */

async function ingestPages(spaceId) {
  const base = await getSiteBaseUrl();
  const raw = await listAllPages(spaceId);
  const canEmbed = await supportsEmbeddings();
  const pages = [];

  for (const p of raw) {
    const text = storageToText(p.body?.storage?.value);
    if (!text) continue;
    const url = `${base}/pages/viewpage.action?pageId=${p.id}`;
    const existing = await query(
      `SELECT id, version, embedding FROM knowledge_item WHERE external_id = ?`,
      [String(p.id)]
    );
    let id;
    let embedding = null;
    if (existing.length && existing[0].version === p.version?.number) {
      id = existing[0].id;
      embedding = existing[0].embedding ? JSON.parse(existing[0].embedding) : null;
    } else if (existing.length) {
      id = existing[0].id;
      await execute(
        `UPDATE knowledge_item SET title = ?, url = ?, version = ?, content = ?, embedding = NULL, last_author_account_id = ? WHERE id = ?`,
        [p.title, url, p.version?.number ?? null, text.slice(0, 100000), p.authorId ?? null, id]
      );
    } else {
      id = uuid();
      // Two staggered scan invocations can ingest concurrently (fast heuristic
      // mode especially) — make the insert race-safe: if another invocation
      // inserted this page first, fall back to updating the existing row.
      await execute(
        `INSERT INTO knowledge_item (id, external_id, title, url, space_id, version, content, last_author_account_id)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)
         ON DUPLICATE KEY UPDATE title = VALUES(title), url = VALUES(url), version = VALUES(version),
           content = VALUES(content), last_author_account_id = VALUES(last_author_account_id)`,
        [id, String(p.id), p.title, url, p.spaceId ?? null, p.version?.number ?? null, text.slice(0, 100000), p.authorId ?? null]
      );
      // On a duplicate-key upsert our new id was NOT used — read back the real one.
      const row = await query(`SELECT id FROM knowledge_item WHERE external_id = ?`, [String(p.id)]);
      id = row[0].id;
    }
    pages.push({ id, externalId: String(p.id), title: p.title, url, text, embedding });
  }

  if (canEmbed) {
    const missing = pages.filter((p) => !p.embedding);
    if (missing.length) {
      const vectors = await embed(missing.map((p) => `${p.title}\n${p.text}`));
      for (let i = 0; i < missing.length; i++) {
        missing[i].embedding = vectors[i];
        await execute(`UPDATE knowledge_item SET embedding = ? WHERE id = ?`, [
          JSON.stringify(vectors[i]),
          missing[i].id,
        ]);
      }
    }
  }
  return pages;
}

/* ---------- Pairwise checks (duplicates / contradictions) ---------- */

function candidatePairs(pages, minSimilarity, maxPairs) {
  const withVec = pages.filter((p) => p.embedding);
  const pairs = [];
  if (withVec.length >= 2) {
    for (let i = 0; i < withVec.length; i++) {
      for (let j = i + 1; j < withVec.length; j++) {
        const sim = cosineSimilarity(withVec[i].embedding, withVec[j].embedding);
        if (sim >= minSimilarity) pairs.push({ a: withVec[i], b: withVec[j], sim });
      }
    }
    pairs.sort((x, y) => y.sim - x.sim);
    return pairs.slice(0, maxPairs);
  }
  // No embeddings (e.g. Anthropic-only): fall back to all pairs, capped.
  for (let i = 0; i < pages.length && pairs.length < maxPairs; i++) {
    for (let j = i + 1; j < pages.length && pairs.length < maxPairs; j++) {
      pairs.push({ a: pages[i], b: pages[j], sim: null });
    }
  }
  return pairs;
}

async function alreadyReported(type, aId, bId) {
  const rows = await query(
    `SELECT f.id FROM finding f
     JOIN finding_evidence e1 ON e1.finding_id = f.id AND e1.knowledge_item_id = ?
     JOIN finding_evidence e2 ON e2.finding_id = f.id AND e2.knowledge_item_id = ?
     WHERE f.type = ? AND f.status NOT IN ('DISMISSED') LIMIT 1`,
    [aId, bId, type]
  );
  return rows.length > 0;
}

async function scanPairs(pages, thresholds, scanId, postComments, stats, cfg) {
  const maxPairs = cfg.maxPairs ?? thresholds.maxPairsPerScan;
  const pairs = candidatePairs(pages, thresholds.candidateSimilarity, maxPairs);
  for (const { a, b } of pairs) {
    if (await alreadyReported(cfg.type, a.id, b.id)) continue;
    const { output, model, promptVersion } = await cfg.assess(a, b);
    stats.assessed++;
    if (!cfg.accept(output)) continue;

    const findingId = uuid();
    await execute(
      `INSERT INTO finding (id, type, severity, status, title, summary, confidence, recommended_action, detail, model, prompt_version, scan_id)
       VALUES (?, ?, ?, 'NEW', ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        findingId,
        cfg.type,
        cfg.severity(output),
        `${cfg.type === 'DUPLICATE' ? 'Possible duplicate' : 'Possible contradiction'}: "${a.title}" vs "${b.title}"`,
        output.summary,
        output.confidence,
        cfg.action(output),
        JSON.stringify({
          item_a_id: a.id,
          item_b_id: b.id,
          ...(output.conflicting_claims ? { conflicting_claims: output.conflicting_claims } : {}),
        }),
        model,
        promptVersion,
        scanId,
      ]
    );
    for (const ev of output.evidence) {
      const page = ev.page === 'B' ? b : a;
      await execute(
        `INSERT INTO finding_evidence (id, finding_id, knowledge_item_id, excerpt, source_label) VALUES (?, ?, ?, ?, ?)`,
        [uuid(), findingId, page.id, ev.excerpt, page.title]
      );
    }
    const owners = await attachPotentialOwners(findingId, [a, b]);
    await audit({ actor: 'agent', eventType: 'finding.created', resourceType: 'finding', resourceId: findingId, detail: { type: cfg.type, confidence: output.confidence } });
    if (postComments) await postFindingComment(findingId, cfg.type, output.summary, output.evidence, [a, b], owners);
    stats.findings++;
  }
}

/* ---------- Open questions ---------- */

async function scanOpenQuestions(pages, thresholds, scanId, postComments, stats, opts = {}) {
  const assess = opts.assess ?? assessOpenQuestions;
  for (const page of pages) {
    const dup = await query(
      `SELECT f.id FROM finding f JOIN finding_evidence e ON e.finding_id = f.id
       WHERE f.type = 'OPEN_QUESTION' AND e.knowledge_item_id = ? AND f.status NOT IN ('DISMISSED') LIMIT 1`,
      [page.id]
    );
    if (dup.length) continue;
    const { output, model, promptVersion } = await assess(page);
    stats.assessed++;
    const kept = output.questions.filter((q) => q.confidence >= thresholds.openQuestionConfidence);
    if (!kept.length) continue;

    const findingId = uuid();
    const top = kept.reduce((m, q) => (rank(q.severity) > rank(m.severity) ? q : m), kept[0]);
    await execute(
      `INSERT INTO finding (id, type, severity, status, title, summary, confidence, recommended_action, detail, model, prompt_version, scan_id)
       VALUES (?, ?, ?, 'NEW', ?, ?, ?, 'REVIEW', ?, ?, ?, ?)`,
      [
        findingId,
        'OPEN_QUESTION',
        top.severity,
        `Open question(s) on "${page.title}"`,
        kept.map((q) => q.question).join(' | ').slice(0, 2000),
        Math.max(...kept.map((q) => q.confidence)),
        JSON.stringify({ questions: kept }),
        model,
        promptVersion,
        scanId,
      ]
    );
    for (const q of kept) {
      await execute(
        `INSERT INTO finding_evidence (id, finding_id, knowledge_item_id, excerpt, source_label) VALUES (?, ?, ?, ?, ?)`,
        [uuid(), findingId, page.id, q.excerpt, page.title]
      );
    }
    const owners = await attachPotentialOwners(findingId, [page]);
    await audit({ actor: 'agent', eventType: 'finding.created', resourceType: 'finding', resourceId: findingId, detail: { type: 'OPEN_QUESTION' } });
    if (postComments)
      await postFindingComment(
        findingId,
        'OPEN_QUESTION',
        kept.map((q) => q.question).join(' '),
        kept.map((q) => ({ page: 'A', excerpt: q.excerpt })),
        [page],
        owners
      );
    stats.findings++;
  }
}

const rank = (s) => ({ LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4 })[s] ?? 2;

/* ---------- Potential ownership (deterministic signals, labelled potential) ---------- */

async function attachPotentialOwners(findingId, pages) {
  const owners = [];
  const seen = new Set();
  for (const page of pages) {
    const accountId = await getPageVersionAuthor(page.externalId);
    if (!accountId || seen.has(accountId)) continue;
    seen.add(accountId);
    const displayName = await getUserDisplayName(accountId);
    await execute(
      `INSERT INTO finding_person (id, finding_id, account_id, display_name, confidence, evidence) VALUES (?, ?, ?, ?, ?, ?)`,
      [uuid(), findingId, accountId, displayName, 0.5, `Last editor of "${page.title}"`]
    );
    owners.push({ account_id: accountId, display_name: displayName });
  }
  return owners;
}

/* ---------- Comment posting (policy-gated by postComments flag) ---------- */

export async function postFindingComment(findingId, type, summary, evidence, pages, owners) {
  try {
    const draft = await draftComment(
      {
        type,
        summary,
        evidence: evidence.map((ev) => ({
          source_label: (ev.page === 'B' ? pages[1] : pages[0])?.title ?? pages[0].title,
          excerpt: ev.excerpt,
        })),
      },
      owners
    );
    const html = commentToStorageHtml(draft, pages, owners);
    const result = await addFooterComment(pages[0].externalId, html);
    await execute(
      `INSERT INTO comment_action (id, finding_id, knowledge_item_id, external_comment_id, state) VALUES (?, ?, ?, ?, 'POSTED')`,
      [uuid(), findingId, pages[0].id, String(result.id ?? ''), ]
    );
    await execute(`UPDATE finding SET status = 'NOTIFIED' WHERE id = ?`, [findingId]);
    await audit({ actor: 'agent', eventType: 'comment.posted', resourceType: 'finding', resourceId: findingId, policyDecision: 'ALLOWED', detail: { commentId: result.id, pageId: pages[0].externalId } });
  } catch (err) {
    console.error('comment post failed', err);
    await audit({ actor: 'agent', eventType: 'comment.failed', resourceType: 'finding', resourceId: findingId, detail: { error: String(err).slice(0, 500) } });
  }
}
