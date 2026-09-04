/**
 * Forge SQL schema migrations for Docgrity.
 *
 * Run by the `db-migrations` scheduled trigger (hourly; each statement is
 * applied once). Forge SQL is per-installation, so there is no tenant_id —
 * the installation IS the tenant.
 */
import { migrationRunner } from '@forge/sql';

const MIGRATIONS = [
  [
    'v001_knowledge_item',
    `CREATE TABLE IF NOT EXISTS knowledge_item (
      id VARCHAR(36) PRIMARY KEY,
      external_id VARCHAR(64) NOT NULL UNIQUE,
      title VARCHAR(512) NOT NULL,
      url VARCHAR(1024),
      space_id VARCHAR(64),
      version INT,
      content MEDIUMTEXT,
      content_hash VARCHAR(64),
      embedding TEXT,
      last_author_account_id VARCHAR(128),
      updated_at_source TIMESTAMP NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )`,
  ],
  [
    'v002_finding',
    `CREATE TABLE IF NOT EXISTS finding (
      id VARCHAR(36) PRIMARY KEY,
      type VARCHAR(32) NOT NULL,
      severity VARCHAR(16) NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'NEW',
      title VARCHAR(512) NOT NULL,
      summary TEXT,
      confidence DOUBLE,
      recommended_action VARCHAR(32),
      detail JSON,
      model VARCHAR(128),
      prompt_version VARCHAR(16),
      input_hash VARCHAR(64),
      scan_id VARCHAR(36),
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )`,
  ],
  [
    'v003_finding_evidence',
    `CREATE TABLE IF NOT EXISTS finding_evidence (
      id VARCHAR(36) PRIMARY KEY,
      finding_id VARCHAR(36) NOT NULL,
      knowledge_item_id VARCHAR(36),
      excerpt TEXT,
      source_label VARCHAR(512),
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_evidence_finding (finding_id)
    )`,
  ],
  [
    'v004_finding_person',
    `CREATE TABLE IF NOT EXISTS finding_person (
      id VARCHAR(36) PRIMARY KEY,
      finding_id VARCHAR(36) NOT NULL,
      account_id VARCHAR(128) NOT NULL,
      display_name VARCHAR(255),
      confidence DOUBLE,
      evidence VARCHAR(512),
      INDEX idx_person_finding (finding_id)
    )`,
  ],
  [
    'v005_scan',
    `CREATE TABLE IF NOT EXISTS scan (
      id VARCHAR(36) PRIMARY KEY,
      status VARCHAR(16) NOT NULL,
      checks JSON,
      stats JSON,
      error TEXT,
      started_at TIMESTAMP NULL,
      completed_at TIMESTAMP NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )`,
  ],
  [
    'v006_audit_event',
    `CREATE TABLE IF NOT EXISTS audit_event (
      id VARCHAR(36) PRIMARY KEY,
      actor VARCHAR(128) NOT NULL,
      event_type VARCHAR(64) NOT NULL,
      resource_type VARCHAR(32),
      resource_id VARCHAR(64),
      policy_decision VARCHAR(16),
      detail JSON,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_audit_created (created_at)
    )`,
  ],
  [
    'v007_comment_action',
    `CREATE TABLE IF NOT EXISTS comment_action (
      id VARCHAR(36) PRIMARY KEY,
      finding_id VARCHAR(36) NOT NULL,
      knowledge_item_id VARCHAR(36),
      external_comment_id VARCHAR(64),
      state VARCHAR(16),
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )`,
  ],
];

export const runner = async () => {
  let queue = migrationRunner;
  for (const [name, ddl] of MIGRATIONS) {
    queue = queue.enqueue(name, ddl);
  }
  const applied = await queue.run();
  console.log('Migrations applied:', JSON.stringify(applied));
  const all = await migrationRunner.list();
  for (const m of all) {
    console.log(`${m.name} migrated at ${m.migratedAt}`);
  }
};
