/**
 * Docgrity resolvers — the API surface for the UI Kit dashboard.
 *
 * Deterministic CRUD/orchestration only; LLM work happens in agents (queue
 * consumers or explicit human-approved actions). Destructive actions
 * (archive, page edit) run only from human-approved dashboard clicks.
 */
import Resolver from '@forge/resolver';
import { Queue } from '@forge/events';
import { draftFix } from './agents';
import { archivePage, getPage, isSiteAdmin, listSpaces, updatePage } from './confluence';
import { audit, execute, query, uuid } from './db';
import { getLlmSettings, PROVIDERS, saveLlmSettings } from './llm';

const resolver = new Resolver();
const scansQueue = new Queue({ key: 'scans' });
const notifyQueue = new Queue({ key: 'notify' });

const escHtml = (s) =>
  String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/* ---------- Settings (BYO LLM key) ---------- */

resolver.define('getSettings', async ({ context }) => {
  const { settings, hasKey } = await getLlmSettings();
  return {
    providers: Object.entries(PROVIDERS).map(([id, p]) => ({
      id,
      label: p.label,
      defaultModel: p.defaultModel,
      supportsEmbeddings: p.supportsEmbeddings,
      models: p.models,
      embeddingModels: p.embeddingModels,
    })),
    settings,
    hasKey,
    isAdmin: await isSiteAdmin(context?.accountId),
  };
});

resolver.define('saveSettings', async ({ payload, context }) => {
  // Server-side gate: only site admins may change the provider or key.
  if (!(await isSiteAdmin(context?.accountId))) {
    await audit({
      actor: context?.accountId ?? 'unknown',
      eventType: 'settings.update_denied',
      policyDecision: 'DENIED',
      detail: { reason: 'not a site admin' },
    });
    throw new Error('Only Confluence site admins can change AI provider settings.');
  }
  await saveLlmSettings(payload);
  await audit({
    actor: context?.accountId ?? 'admin',
    eventType: 'settings.updated',
    detail: { provider: payload.provider, model: payload.model }, // never the key
  });
  return { ok: true };
});

/* ---------- Spaces & scans ---------- */

resolver.define('getSpaces', async () => listSpaces());

resolver.define('createScan', async ({ payload, context }) => {
  const { checks = [], post_comments = false, space_id = null } = payload;
  const { settings, hasKey } = await getLlmSettings();
  if (!settings || !hasKey) {
    throw new Error('Configure an LLM provider and API key in Settings before scanning.');
  }
  const ids = [];
  for (const check of checks) {
    const scanId = uuid();
    await execute(`INSERT INTO scan (id, status, checks) VALUES (?, 'PENDING', ?)`, [
      scanId,
      JSON.stringify([check]),
    ]);
    await scansQueue.push({
      body: { scanId, check, postComments: post_comments, spaceId: space_id },
    });
    ids.push(scanId);
  }
  await audit({
    actor: context?.accountId ?? 'user',
    eventType: 'scan.requested',
    detail: { checks, post_comments, space_id },
  });
  return { scan_ids: ids };
});

/* ---------- Findings ---------- */

const OPEN_STATUSES = `('NEW', 'AWAITING_OWNER', 'NOTIFIED')`;

resolver.define('getStats', async () => {
  try {
    return await computeStats();
  } catch (err) {
    // First run: tables may not exist yet (hourly migration trigger hasn't
    // fired). Run migrations once and retry.
    const { runner } = await import('./migrations');
    await runner();
    return computeStats();
  }
});

async function computeStats() {
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
    total_open: byType.reduce((sum, r) => sum + Number(r.n), 0),
    by_type: Object.fromEntries(byType.map((r) => [r.type, Number(r.n)])),
    by_severity: Object.fromEntries(bySeverity.map((r) => [r.severity, Number(r.n)])),
    last_scan_completed_at: lastScan[0]?.completed_at ?? null,
  };
}

resolver.define('listFindings', async ({ payload }) => {
  const { type = null, limit = 100 } = payload ?? {};
  const rows = type
    ? await query(
        `SELECT * FROM finding WHERE type = ? ORDER BY created_at DESC LIMIT ${Math.min(Number(limit) || 100, 500)}`,
        [type]
      )
    : await query(
        `SELECT * FROM finding ORDER BY created_at DESC LIMIT ${Math.min(Number(limit) || 100, 500)}`
      );
  const out = [];
  for (const f of rows) {
    const owners = await query(
      `SELECT display_name FROM finding_person WHERE finding_id = ?`,
      [f.id]
    );
    out.push({ ...serializeFinding(f), owner_names: owners.map((o) => o.display_name) });
  }
  return out;
});

resolver.define('getFinding', async ({ payload }) => {
  const { id } = payload;
  const rows = await query(`SELECT * FROM finding WHERE id = ?`, [id]);
  if (!rows.length) throw new Error('Finding not found');
  const f = serializeFinding(rows[0]);

  const evidence = await query(
    `SELECT e.excerpt, e.source_label, k.id AS ki_id, k.external_id, k.title, k.url
     FROM finding_evidence e LEFT JOIN knowledge_item k ON k.id = e.knowledge_item_id
     WHERE e.finding_id = ?`,
    [id]
  );
  const owners = await query(
    `SELECT account_id, display_name, confidence, evidence FROM finding_person WHERE finding_id = ?`,
    [id]
  );
  const seen = new Set();
  f.pages = evidence
    .filter((e) => e.ki_id && !seen.has(e.ki_id) && seen.add(e.ki_id))
    .map((e) => ({ id: e.ki_id, external_id: e.external_id, title: e.title, url: e.url }));
  f.evidence = evidence.map((e) => ({ excerpt: e.excerpt, source_label: e.source_label }));
  f.potential_owners = owners.map((o) => ({
    account_id: o.account_id,
    display_name: o.display_name,
    confidence: Number(o.confidence) || 0,
    evidence: o.evidence ? [o.evidence] : [],
  }));
  return f;
});

resolver.define('setFindingStatus', async ({ payload, context }) => {
  const { id, status } = payload;
  if (!['DISMISSED', 'RESOLVED', 'NEW'].includes(status)) throw new Error('Invalid status');
  await execute(`UPDATE finding SET status = ? WHERE id = ?`, [status, id]);
  await audit({
    actor: context?.accountId ?? 'user',
    eventType: 'finding.status_changed',
    resourceType: 'finding',
    resourceId: id,
    policyDecision: 'HUMAN_APPROVED',
    detail: { status },
  });
  return { ok: true };
});

/* ---------- Human-approved actions ---------- */

resolver.define('notifyOwner', async ({ payload, context }) => {
  const { id } = payload;
  await notifyQueue.push({ body: { findingId: id } });
  await audit({
    actor: context?.accountId ?? 'user',
    eventType: 'action.notify_owner',
    resourceType: 'finding',
    resourceId: id,
    policyDecision: 'HUMAN_APPROVED',
    detail: {},
  });
  return { ok: true, queued: true };
});

resolver.define('mergeRedirect', async ({ payload, context }) => {
  const { id, keep_item_id } = payload;
  const rows = await query(`SELECT * FROM finding WHERE id = ?`, [id]);
  if (!rows.length) throw new Error('Finding not found');
  const f = serializeFinding(rows[0]);
  const ids = [f.detail?.item_a_id, f.detail?.item_b_id];
  if (!ids.includes(keep_item_id)) throw new Error('keep_item_id is not part of this finding');
  const archiveId = ids.find((i) => i !== keep_item_id);

  const [keep] = await query(`SELECT * FROM knowledge_item WHERE id = ?`, [keep_item_id]);
  const [arch] = await query(`SELECT * FROM knowledge_item WHERE id = ?`, [archiveId]);
  if (!keep || !arch) throw new Error('Knowledge items not found');

  const page = await getPage(arch.external_id);
  const notice =
    '<ac:structured-macro ac:name="info"><ac:rich-text-body>' +
    `<p><strong>This page has moved.</strong> The maintained version is ` +
    `<a href="${escHtml(keep.url)}">${escHtml(keep.title)}</a>. ` +
    'This copy was archived by Docgrity after a human-approved merge.</p>' +
    '</ac:rich-text-body></ac:structured-macro>';
  const body = page.body?.storage?.value ?? '';
  await updatePage(
    arch.external_id,
    page.title ?? arch.title,
    notice + body,
    (page.version?.number ?? 1) + 1,
    'Docgrity merge & redirect (human-approved)'
  );
  await archivePage(arch.external_id);
  await execute(`UPDATE finding SET status = 'RESOLVED' WHERE id = ?`, [id]);
  await audit({
    actor: context?.accountId ?? 'user',
    eventType: 'action.merge_redirect',
    resourceType: 'finding',
    resourceId: id,
    policyDecision: 'HUMAN_APPROVED',
    detail: { kept: keep.external_id, archived: arch.external_id },
  });
  return { kept: keep.external_id, archived: arch.external_id };
});

resolver.define('draftFix', async ({ payload }) => {
  const { id } = payload;
  const rows = await query(`SELECT * FROM finding WHERE id = ?`, [id]);
  if (!rows.length) throw new Error('Finding not found');
  const f = serializeFinding(rows[0]);
  const [a] = await query(`SELECT * FROM knowledge_item WHERE id = ?`, [f.detail?.item_a_id]);
  const [b] = await query(`SELECT * FROM knowledge_item WHERE id = ?`, [f.detail?.item_b_id]);
  if (!a || !b) throw new Error('Pages for this finding are no longer available');

  const draft = await draftFix(
    f,
    { title: a.title, text: a.content },
    { title: b.title, text: b.content }
  );
  return {
    reasoning: draft.reasoning,
    patches: draft.patches.map((p) => {
      const item = p.page === 'B' ? b : a;
      return {
        page_external_id: item.external_id,
        page_title: item.title,
        find_text: p.find_text,
        replace_text: p.replace_text,
        rationale: p.rationale,
        confidence: p.confidence,
      };
    }),
  };
});

resolver.define('applyFix', async ({ payload, context }) => {
  const { id, page_external_id, find_text, replace_text } = payload;
  if (!find_text || find_text === replace_text) throw new Error('Patch is empty or a no-op');

  const page = await getPage(page_external_id);
  const body = page.body?.storage?.value ?? '';
  const candidates = [find_text, escHtml(find_text)];
  const target = candidates.find((c) => body.split(c).length - 1 === 1);
  if (!target) {
    throw new Error(
      'Patch rejected: find_text must occur exactly once on the page. It may have changed since drafting.'
    );
  }
  const replacement = target === find_text ? replace_text : escHtml(replace_text);
  await updatePage(
    page_external_id,
    page.title ?? '',
    body.replace(target, replacement),
    (page.version?.number ?? 1) + 1,
    'Docgrity contradiction fix (human-approved)'
  );
  await execute(`UPDATE finding SET status = 'RESOLVED' WHERE id = ?`, [id]);
  await audit({
    actor: context?.accountId ?? 'user',
    eventType: 'action.apply_fix',
    resourceType: 'finding',
    resourceId: id,
    policyDecision: 'HUMAN_APPROVED',
    detail: { page: page_external_id },
  });
  return { page: page_external_id, applied: true };
});

function serializeFinding(row) {
  return {
    id: row.id,
    type: row.type,
    severity: row.severity,
    status: row.status,
    title: row.title,
    summary: row.summary,
    confidence: Number(row.confidence) || 0,
    recommended_action: row.recommended_action,
    detail: typeof row.detail === 'string' ? JSON.parse(row.detail || '{}') : row.detail ?? {},
    created_at: row.created_at,
  };
}

export const handler = resolver.getDefinitions();
