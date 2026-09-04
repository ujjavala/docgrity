/**
 * Thin helpers over Forge SQL. Positional params only (mysql engine).
 */
import { sql } from '@forge/sql';

export async function query(q, params = []) {
  const stmt = sql.prepare(q);
  const result = params.length ? await stmt.bindParams(...params).execute() : await stmt.execute();
  return result.rows ?? [];
}

export async function execute(q, params = []) {
  const stmt = sql.prepare(q);
  return params.length ? stmt.bindParams(...params).execute() : stmt.execute();
}

export function uuid() {
  return crypto.randomUUID();
}

export async function audit({ actor, eventType, resourceType, resourceId, policyDecision, detail }) {
  await execute(
    `INSERT INTO audit_event (id, actor, event_type, resource_type, resource_id, policy_decision, detail)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [
      uuid(),
      actor,
      eventType,
      resourceType ?? null,
      resourceId ?? null,
      policyDecision ?? null,
      JSON.stringify(detail ?? {}),
    ]
  );
}
