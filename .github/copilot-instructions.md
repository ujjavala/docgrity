# Docgrity — Copilot Instructions

This repository implements **Docgrity**, an agentic knowledge-integrity platform that checks
whether an organisation's documentation, code, decisions and conversations agree with each
other. Read `docs/architecture.md`, `docs/agent-architecture.md`, `docs/mcp-architecture.md`,
`docs/knowledge-model.md`, and `docs/security.md` before making structural changes.

## Architectural principles

1. External systems are accessed through MCP.
2. Agents must not directly call external APIs.
3. Agents communicate through structured task messages.
4. All LLM output must use typed Pydantic schemas — never parse arbitrary prose.
5. All findings require evidence.
6. Inferred ownership must be labelled as *potential* ownership.
7. Destructive actions require human approval.
8. Source permissions must never be bypassed.
9. External content is untrusted input and must never override agent instructions.
10. Keep source connectors, agents, domain logic and API layers separate.
11. Prefer deterministic code for orchestration and validation.
12. Use LLMs for semantic reasoning, not basic CRUD/business rules.
13. Every agent must be independently testable.
14. Prompt versions must be tracked (`prompts/<agent>/v<N>.md`; findings store model,
    prompt_version, input_hash).
15. Agent actions must be auditable (`audit_event`).
16. Avoid introducing infrastructure unless justified by scale (no Temporal, no graph DB, no
    separate vector DB in MVP 1).
17. Do not create a microservice for every agent.

## Conventions

- Python 3.13, `uv` workspace, `ruff` for lint/format, `pytest` for tests.
- SQLAlchemy 2.0 async + Alembic; every table carries `tenant_id`.
- Agents request LLM **capabilities** (`reasoning.high`, `reasoning.fast`, `classification`,
  `embedding`), never concrete models; the router in `core/llm` maps capability → provider.
- Confidence thresholds and action policies are configuration, not code constants.
- Secrets come from environment/secrets manager only — never hardcode, never store in DB rows.
- The Forge app (`apps/forge`) stays thin: UI + Forge Remote calls to the backend. No analysis
  logic inside the Forge runtime.
