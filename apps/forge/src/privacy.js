/**
 * Personal-data lifecycle (Forge user privacy guidelines).
 *
 * Docgrity stores Atlassian account IDs and display names inside the
 * installation's own Forge SQL (finding_person, knowledge_item.last_author_account_id)
 * to support potential-owner inference. This scheduled job keeps that data
 * accurate and erases it when an account no longer exists (closed/erased):
 *
 *  - account still active  -> refresh stored display_name if it changed
 *  - account gone (404)    -> delete finding_person rows and null out
 *                             last_author_account_id references
 *
 * Runs weekly via the `privacy-runner` scheduled trigger.
 */
import api, { route } from '@forge/api';
import { query, execute, audit } from './db.js';

/** Returns {exists, displayName} for an accountId. */
async function lookupAccount(accountId) {
  const res = await api
    .asApp()
    .requestConfluence(route`/wiki/rest/api/user?accountId=${accountId}`);
  if (res.status === 404) return { exists: false };
  if (!res.ok) throw new Error(`user lookup failed: ${res.status}`);
  const data = await res.json();
  return { exists: true, displayName: data.displayName || data.publicName || null };
}

export const runner = async () => {
  const rows = await query(
    `SELECT DISTINCT account_id FROM finding_person
     UNION
     SELECT DISTINCT last_author_account_id FROM knowledge_item
     WHERE last_author_account_id IS NOT NULL`
  );
  let refreshed = 0;
  let erased = 0;

  for (const row of rows) {
    const accountId = row.account_id;
    if (!accountId) continue;
    let info;
    try {
      info = await lookupAccount(accountId);
    } catch (e) {
      console.warn(`privacy: lookup failed for account, skipping: ${e.message}`);
      continue;
    }

    if (!info.exists) {
      await execute(`DELETE FROM finding_person WHERE account_id = ?`, [accountId]);
      await execute(
        `UPDATE knowledge_item SET last_author_account_id = NULL WHERE last_author_account_id = ?`,
        [accountId]
      );
      erased++;
    } else if (info.displayName) {
      await execute(
        `UPDATE finding_person SET display_name = ? WHERE account_id = ? AND display_name <> ?`,
        [info.displayName, accountId, info.displayName]
      );
      refreshed++;
    }
  }

  await audit({
    actor: 'system',
    eventType: 'privacy.account_sync',
    resourceType: 'installation',
    resourceId: 'personal-data',
    detail: { checked: rows.length, refreshed, erased },
  });
  console.log(`privacy sync: checked=${rows.length} refreshed=${refreshed} erased=${erased}`);
};
