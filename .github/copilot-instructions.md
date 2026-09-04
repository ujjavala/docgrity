# Docgrity — Copilot Instructions

This repository implements **Docgrity**, an agentic knowledge-integrity platform that checks
whether an organisation's documentation, code, decisions and conversations agree with each
other. The shipping implementation is a **zero-infrastructure Atlassian Forge app** in
`apps/forge`; a VS Code extension is planned. Read `docs/forge-native.md`,
`docs/architecture.md`, `docs/agent-architecture.md`, `docs/knowledge-model.md`,
`docs/security.md`, and `docs/vscode-extension.md` before making structural changes.

## Architectural principles

1. Everything runs on Forge — no servers, databases or queues we operate. Do not add
   external infrastructure or Forge Remote backends.
2. Confluence is accessed only through `src/confluence.js` (`api.asApp()`); LLM providers
   only through `src/llm.js`. Agents never call external APIs directly.
3. Async work goes through Forge `@forge/events` queues (`scans`, `notify`).
4. All LLM output must be typed JSON validated in code (`completeJson` + validators in
   `agents.js`) — never parse arbitrary prose.
5. All findings require evidence.
6. Inferred ownership must be labelled as *potential* ownership.
7. Destructive actions require human approval.
8. Source permissions must never be bypassed.
9. External content is untrusted input and must never override agent instructions.
10. Keep source connectors, agents, domain logic and API layers separate.
11. Prefer deterministic code for orchestration and validation.
12. Use LLMs for semantic reasoning, not basic CRUD/business rules.
13. Every agent must be independently testable.
14. Prompt versions must be tracked (versioned prompts in `apps/forge/src/agents.js`;
    findings store model and prompt_version).
15. Agent actions must be auditable (`audit_event` table, `audit()` in `db.js`).
16. Avoid introducing infrastructure unless justified by scale (no graph DB, no separate
    vector DB; embeddings live as JSON text in Forge SQL).
17. Rovo action inputs and page content are untrusted — validate IDs against the DB and
    take identity from the Forge context, never from LLM-generated inputs.

## Conventions

- Node 22, Forge CLI; JavaScript (no build step beyond Forge bundling); UI Kit frontend.
- Forge SQL (MySQL engine): positional `?` bind params; DDL only via `migrationRunner`
  in `src/migrations.js`. The installation is the tenant boundary (no `tenant_id`).
- Tenants bring their own LLM key; provider/model chosen in Settings (admin-only,
  enforced server-side). Supported providers and model catalogs live in `src/llm.js`.
- Confidence thresholds and action policies are configuration (kvs `thresholds`), not
  code constants.
- Secrets only via `kvs.setSecret` — never in SQL rows, logs, resolver responses or UI.
- Egress is allowlisted in `manifest.yml` to the three LLM provider domains only.
- Deploy: `cd apps/forge && forge deploy --environment development --no-verify
  --non-interactive`; scope changes need `forge install --upgrade`.
