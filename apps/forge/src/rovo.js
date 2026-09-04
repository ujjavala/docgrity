/**
 * Rovo agent actions — one handler, dispatched on the invoked action's
 * moduleKey. Reuses the same deterministic logic as the dashboard resolvers;
 * returns JSON the Rovo LLM turns into a conversational answer.
 *
 * Security notes:
 * - Action inputs come from an LLM and are untrusted: ids are validated
 *   against the database before use.
 * - Destructive-ish actions (dismiss, notify) are only exposed as explicit
 *   Rovo actions the user asks for in chat — the chat request is the human
 *   approval, and everything is audited.
 */
import { Queue } from '@forge/events';
import { audit, execute, query, uuid } from './db';
import { getLlmSettings } from './llm';

const scansQueue = new Queue({ key: 'scans' });
const notifyQueue = new Queue({ key: 'notify' });

const CHECKS = ['duplicates', 'contradictions', 'open_questions'];
const OPEN_STATUSES = `('NEW', 'AWAITING_OWNER', 'NOTIFIED')`;

export const handler = async (payload, context) => {
  const action = payload?.context?.moduleKey ?? '';
  const accountId = context?.principal?.accountId ?? payload?.context?.accountId ?? 'rovo-user';
  try {
    switch (action) {
      case 'get-integrity-stats':
        return await getStats();
      case 'list-findings':
        return await listFindings(payload.type);
      case 'get-finding':
        return await getFinding(payload.id);
      case 'trigger-scan':
        return await triggerScan(accountId);
      case 'dismiss-finding':
        return await dismissFinding(payload.id, accountId);
      case 'notify-owner':
        return await notifyOwner(payload.id, accountId);
      default:
        return { error: `Unknown action: ${action}` };
    }
  } catch (err) {
    return { error: String(err).slice(0, 500) };
  }
};

async function getStats() {
  const byType = await query(
    `SELECT type, COUNT(*) AS n FROM finding WHERE status IN ${OPEN_STATUSES} GROUP BY type`
  );
  const bySeverity = await query(
    `SELECT severity, COUNT(*) AS n FROM finding WHERE status IN ${OPEN_STATUSES} GROUP BY severity`
  );
  const lastScan = await query(
    `SELECT completed_at FROM scan WHERE status = 'COMPLETED' ORDER BY completed_at DESC LIMIT 1`
  );
  return {
    total_open: byType.reduce((s, r) => s + Number(r.n), 0),
    by_type: Object.fromEntries(byType.map((r) => [r.type, Number(r.n)])),
    by_severity: Object.fromEntries(bySeverity.map((r) => [r.severity, Number(r.n)])),
    last_scan_completed_at: lastScan[0]?.completed_at ?? null,
  };
}

const VALID_TYPES = new Set(['DUPLICATE', 'CONTRADICTION', 'OPEN_QUESTION']);

async function listFindings(type) {
  const t = VALID_TYPES.has(String(type).toUpperCase()) ? String(type).toUpperCase() : null;
  const rows = t
    ? await query(`SELECT * FROM finding WHERE type = ? ORDER BY created_at DESC LIMIT 25`, [t])
    : await query(`SELECT * FROM finding ORDER BY created_at DESC LIMIT 25`);
  const out = [];
  for (const f of rows) {
    const owners = await query(`SELECT display_name FROM finding_person WHERE finding_id = ?`, [
      f.id,
    ]);
    out.push({
      id: f.id,
      type: f.type,
      severity: f.severity,
      status: f.status,
      title: f.title,
      confidence: Number(f.confidence) || 0,
      potential_owners: owners.map((o) => o.display_name),
    });
  }
  return { findings: out, note: 'Ownership is potential ownership inferred from edit signals.' };
}

async function getFinding(id) {
  const rows = await query(`SELECT * FROM finding WHERE id = ?`, [String(id)]);
  if (!rows.length) return { error: 'Finding not found' };
  const f = rows[0];
  const evidence = await query(
    `SELECT e.excerpt, e.source_label, k.title, k.url
     FROM finding_evidence e LEFT JOIN knowledge_item k ON k.id = e.knowledge_item_id
     WHERE e.finding_id = ?`,
    [f.id]
  );
  const owners = await query(
    `SELECT display_name, confidence, evidence FROM finding_person WHERE finding_id = ?`,
    [f.id]
  );
  return {
    id: f.id,
    type: f.type,
    severity: f.severity,
    status: f.status,
    title: f.title,
    summary: f.summary,
    confidence: Number(f.confidence) || 0,
    recommended_action: f.recommended_action,
    evidence: evidence.map((e) => ({
      page: e.title ?? e.source_label,
      url: e.url,
      excerpt: e.excerpt,
    })),
    potential_owners: owners.map((o) => ({
      name: o.display_name,
      confidence: Number(o.confidence) || 0,
      signal: o.evidence,
    })),
  };
}

async function triggerScan(accountId) {
  const { settings, hasKey } = await getLlmSettings();
  if (!settings || !hasKey) {
    return {
      error:
        'Docgrity is not configured yet: a site admin must set an AI provider and API key in Docgrity Settings.',
    };
  }
  const ids = [];
  for (const check of CHECKS) {
    const scanId = uuid();
    await execute(`INSERT INTO scan (id, status, checks) VALUES (?, 'PENDING', ?)`, [
      scanId,
      JSON.stringify([check]),
    ]);
    await scansQueue.push({ body: { scanId, check, postComments: false, spaceId: null } });
    ids.push(scanId);
  }
  await audit({
    actor: accountId,
    eventType: 'scan.requested',
    detail: { via: 'rovo', checks: CHECKS },
  });
  return { started: true, scan_ids: ids, note: 'Results appear in the Docgrity dashboard in a few minutes.' };
}

async function dismissFinding(id, accountId) {
  const rows = await query(`SELECT id FROM finding WHERE id = ?`, [String(id)]);
  if (!rows.length) return { error: 'Finding not found' };
  await execute(`UPDATE finding SET status = 'DISMISSED' WHERE id = ?`, [String(id)]);
  await audit({
    actor: accountId,
    eventType: 'finding.status_changed',
    resourceType: 'finding',
    resourceId: String(id),
    policyDecision: 'HUMAN_APPROVED',
    detail: { status: 'DISMISSED', via: 'rovo' },
  });
  return { dismissed: true, id };
}

async function notifyOwner(id, accountId) {
  const rows = await query(`SELECT id FROM finding WHERE id = ?`, [String(id)]);
  if (!rows.length) return { error: 'Finding not found' };
  await notifyQueue.push({ body: { findingId: String(id) } });
  await audit({
    actor: accountId,
    eventType: 'action.notify_owner',
    resourceType: 'finding',
    resourceId: String(id),
    policyDecision: 'HUMAN_APPROVED',
    detail: { via: 'rovo' },
  });
  return {
    queued: true,
    note: 'A Docgrity comment mentioning the potential owners will be posted on the page shortly.',
  };
}
