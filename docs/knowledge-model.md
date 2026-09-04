# Docgrity — Knowledge Model

## Core concepts

- **KnowledgeItem** — any piece of knowledge from any source (Confluence page, Slack
  message/thread, GitHub file/PR, README, ADR, code section).
- **Claim** — a factual assertion extracted from a KnowledgeItem
  (`subject / predicate / object`, e.g. `Access Token / expires_after / 1 hour`). MVP 2.
- **Entity** — a resolved real-world thing with `canonical_name` + aliases
  (e.g. "Auth Service" ≡ "auth-service"). MVP 2.
- **Finding** — an identified problem with evidence, confidence, potential owner, and a
  recommended action.
- **Person** — a potential human owner/answerer. Ownership is probabilistic unless
  authoritative.
- **Decision / Question** — made or pending decisions; unresolved questions. MVP 2–3.

## Tables (MVP 1)

```
tenant, user, team
source, source_connection, source_scope
knowledge_item, knowledge_item_version
finding, finding_evidence, finding_person, finding_action
agent_task
scan, scan_source, scan_finding
comment_action
audit_event
```

Reserved for MVP 2+: `entity`, `entity_alias`, `claim`, `claim_evidence`, `question`,
`decision` (enums created now).

## KnowledgeItem

```
id, tenant_id
source_type, source_id, external_id
type, title, content, url
author_id, owner_id
created_at, updated_at
content_hash, metadata (JSONB)
embedding (pgvector)
last_scanned_at
```

Types: `CONFLUENCE_PAGE`, `SLACK_MESSAGE`, `SLACK_THREAD`, `GITHUB_FILE`, `GITHUB_PR`,
`README`, `ADR`, `CODE`.

## Finding

```
id, tenant_id
type, severity, status
title, summary, description
confidence
model, prompt_version, input_hash
created_at, updated_at, resolved_at
```

Types: `DUPLICATE`, `CONTRADICTION`, `OPEN_QUESTION`, `UNDOCUMENTED_DECISION`, `STALE`,
`CODE_DOC_DRIFT`, `MISSING_OWNER`, `TERMINOLOGY_DRIFT`.

Statuses: `NEW`, `INVESTIGATING`, `AWAITING_OWNER`, `AWAITING_DECISION`, `ACTION_REQUIRED`,
`RESOLVED`, `DISMISSED`, `FALSE_POSITIVE`.

## Evidence

Every finding must have evidence — the agent must never assert a problem without it.

```
Finding ── FindingEvidence ── knowledge_item_id, claim_id?, excerpt, source, timestamp
```

## Confidence

Every inference is scored: detection confidence, ownership confidence, recommended-action
confidence. Bands: 90–100 HIGH, 70–89 MEDIUM, 50–69 LOW. Precision-first: below-threshold
findings are suppressed or flagged for review, never actioned.

## Source authority

Neither Confluence nor code is absolute truth. Authority is configurable evidence weighting,
e.g.:

```
production configuration  1.00
approved ADR              0.95
current code              0.90
Confluence page           0.75
Slack discussion          0.40
```

## Multi-tenancy

Every persisted object carries `tenant_id`. Never rely solely on application-level filtering;
use database-level safeguards where practical. Embeddings, findings, tasks, and people are all
tenant-scoped.

## Relationships / graph

Initial graph lives in PostgreSQL relations (`person → owns → document → mentions → entity →
has_claim → claim → conflicts_with → claim`). A dedicated graph database is introduced only if
scale/use cases justify it. Dependency edges (documents ↔ entities) drive targeted re-analysis
when a mentioned entity's context changes.
