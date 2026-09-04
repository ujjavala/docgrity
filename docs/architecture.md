# Docgrity — System Architecture

## Overview

Docgrity is a monorepo with a Python backend (FastAPI + async worker), a shared knowledge model
in PostgreSQL (+ pgvector), MCP servers as the interface to external systems, specialised agents
for semantic reasoning, and a Confluence Forge app as the first user surface.

```
                Atlassian Cloud
                      |
              Forge app (apps/forge)
        byline panel · global page · lifecycle
                      |
            Forge Remote (FIT-signed)
                      |
               FastAPI API (apps/api)
                      |
         +------------+------------+
         |                         |
   arq worker (scans)        Policy layer
         |                         |
     Agents (agents/)  --MCP-->  mcp/confluence --> Confluence REST v2
         |
   +-----+------+--------+
   |            |        |
PostgreSQL    Redis     S3 (later)
+ pgvector
```

## Key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Backend language | Python 3.13, uv | AI ecosystem, MCP SDK, Pydantic, FastAPI |
| API | FastAPI | async, typed, OpenAPI |
| Agent engine | PydanticAI behind our own `Agent` abstraction | avoid framework lock-in |
| LLM providers | OpenAI **and** Anthropic behind `LLMProvider` + capability router | no single-vendor dependency |
| Embeddings | Configurable provider; pgvector storage | avoid separate vector DB initially |
| Database | PostgreSQL + pgvector | one store for relational + vector |
| Orchestration | arq (Redis) worker for MVP 1; Temporal deferred | avoid infra before scale justifies it |
| Cache/queue | Redis | short-lived cache, locks, job queue |
| Confluence surface | Forge app + Forge Remote to external backend | Marketplace distribution; AI platform stays outside the Forge runtime |
| External-system access | MCP servers only | uniform tool contract, permissioning, auditability |

## Layering rules

1. **External systems are accessed through MCP.** Agents never call Confluence/Slack/GitHub
   APIs directly.
2. **Agents** do semantic reasoning only; they communicate via structured task messages.
3. **Deterministic code** owns auth, permissions, DB writes, dedup, hashing, thresholds,
   policies, workflow state, rate limiting, audit logging.
4. **Findings are the common language** between agents; every finding carries evidence.
5. Source connectors, agents, domain logic, and API layers stay separate.

## Repository structure

Python code lives under `src/docgrity/` (a top-level `mcp/` package would shadow the MCP SDK
import); non-Python assets stay top-level.

```
docgrity/
├── apps/
│   └── forge/            Atlassian Forge app (Confluence surface)
├── src/docgrity/
│   ├── api/              FastAPI application
│   ├── agents/           duplicate, ownership, action, verification (MVP 1)
│   ├── mcp/confluence/   Confluence MCP server + REST client
│   ├── core/             models, schemas, llm, policies, security, config
│   └── workflows/        scan + ingestion pipelines (arq tasks)
├── prompts/              versioned prompt files
├── evaluations/          curated eval datasets + harness
├── migrations/           Alembic
├── infrastructure/       deployment
├── docs/
└── tests/
```

## Scan lifecycle

```
CREATE SCAN → validate permissions → discover sources → collect KnowledgeItems
→ dedupe ingestion (external_id + content_hash) → generate embeddings
→ build candidate relationships → run analysis agents → collect findings
→ ownership analysis → resolution recommendation → policy evaluation
→ execute allowed actions → persist findings → report
```

Incremental scanning: track `content_hash`, `updated_at`, `last_scanned_at`; skip expensive
analysis for unchanged items; re-analyse affected relationships on change.

## Agentic vs deterministic

- **Agentic (LLM):** semantic similarity verification, claim extraction, contradiction
  reasoning, question interpretation, decision detection, entity resolution, ownership
  reasoning, recommended actions, natural-language explanation.
- **Deterministic:** authentication, permissions, DB writes, external-ID dedup, hashing,
  timestamps, confidence thresholds, action policies, workflow state, rate limiting, audit.

## Observability

OpenTelemetry across API, worker, agents. Track: scan_id, task_id, agent, model, tool calls,
MCP calls, latency, tokens, cost, finding, confidence.

## Deployment (beta)

Single containerised backend (api + worker) on a public HTTPS host, managed Postgres with
pgvector, Redis. Forge app deployed via Forge CLI to Atlassian's cloud. Secrets in a secrets
manager (never DB rows); `.env` for local dev only.
