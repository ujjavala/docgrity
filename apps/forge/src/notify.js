/**
 * Notify consumer (async events queue "notify"): draft and post a comment for
 * an existing finding on demand ("Notify owner" button — human-approved).
 */
import { query } from './db';
import { postFindingComment } from './scans';

export const handler = async (event) => {
  const { findingId } = event.body;
  const findings = await query(`SELECT * FROM finding WHERE id = ?`, [findingId]);
  if (!findings.length) return;
  const finding = findings[0];

  const evidence = await query(
    `SELECT e.excerpt, e.source_label, k.id AS ki_id, k.external_id, k.title, k.url
     FROM finding_evidence e LEFT JOIN knowledge_item k ON k.id = e.knowledge_item_id
     WHERE e.finding_id = ?`,
    [findingId]
  );
  const owners = await query(
    `SELECT account_id, display_name FROM finding_person WHERE finding_id = ?`,
    [findingId]
  );

  const seen = new Set();
  const pages = evidence
    .filter((e) => e.ki_id && !seen.has(e.ki_id) && seen.add(e.ki_id))
    .map((e) => ({ id: e.ki_id, externalId: e.external_id, title: e.title, url: e.url }));
  if (!pages.length) return;

  await postFindingComment(
    findingId,
    finding.type,
    finding.summary,
    evidence.map((e) => ({ page: 'A', excerpt: e.excerpt, source_label: e.source_label })),
    pages,
    owners
  );
};
