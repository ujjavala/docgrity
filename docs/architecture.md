# Docgrity — System Architecture

## Overview

Docgrity runs entirely on **Atlassian Forge** — no servers, databases, queues or remotes we
operate. The app lives in `apps/forge`: Forge SQL for the knowledge model, `@forge/events`
queues for async scans, KVS for settings/secrets, UI Kit for the dashboard, and a Rovo agent
as the conversational surface. The only external calls are to the tenant's chosen LLM
provider. Implementation detail lives in [forge-native.md](forge-native.md).

```
                Atlassian Cloud (Forge runtime)
                      |
        +-------------+---------------------------+
        |             |               |           |
  Global page    Resolvers      Rovo agent   Scheduled trigger
  (UI Kit)      (index.js)      (rovo.js)    (migrations, hourly)
        \             |               |           |
         +------------+------+-------+-----------+
                             |
              @forge/events queues: scans · notify
                             |
              Consumers: scans.js · notify.js
                     |               |
              agents.js (LLM)   confluence.js (asApp REST v2)
                     |
               llm.js  ── egress allowlist ──► Gemini / OpenAI / Anthropic
                     |
        Forge SQL (knowledge model) · KVS (settings, secret key)
```

## Key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Platform | 100% Forge-native | zero infrastructure cost, Marketplace "Runs on Atlassian" |
| Language | Node 22 JavaScript | Forge runtime; no build step |
| Database | Forge SQL (MySQL engine) | relational store inside the tenant boundary |
| Embeddings | JSON text columns + cosine in JS | Forge SQL has no vector type; scale doesn't justify more |
| Async work | `@forge/events` queues + consumers | scans exceed resolver limits; 900 s consumer timeout |
| LLM providers | BYO key: Gemini / OpenAI / Anthropic via `llm.js` | tenant choice, no vendor lock-in, no cost to us |
| Secrets | `kvs.setSecret` only | never in SQL rows, logs, responses, UI |
| Conversational surface | Rovo agent + actions | free (Atlassian LLM), native chat UX |
| Tenancy | Forge installation boundary | no `tenant_id`; data isolation by platform |

## Layering rules

1. **Confluence is accessed only through `confluence.js`** (`api.asApp()`); LLM providers
   only through `llm.js`. Agents never call external APIs directly.
2. **Agents (`agents.js`)** do semantic reasoning only, with versioned prompts and typed
   JSON outputs validated in code.
3. **Deterministic code** owns permissions, DB writes, dedup, hashing, thresholds,
   policies, workflow state, and audit logging.
4. **Findings are the common language**; every finding carries evidence and records
   model + prompt_version.
5. Rovo/LLM-generated inputs are untrusted: IDs validated against the DB, identity taken
   from the Forge context.

## Scan lifecycle

```
CREATE SCAN (resolver or Rovo action) → scan rows PENDING → queue push per check
→ consumer: ingest pages (external_id + version dedupe) → embed missing items
→ candidate pairs (cosine ≥ threshold, or capped all-pairs when no embeddings)
→ LLM assess (duplicate / contradiction / open questions) → confidence gate
→ persist finding + evidence + potential owners → policy-gated comment → audit
```

Incremental scanning: unchanged page versions are skipped; already-reported pairs are
deduped against open findings.

## Agentic vs deterministic

- **Agentic (LLM):** duplicate verification, contradiction reasoning, open-question
  detection, comment drafting, contradiction patch drafting.
- **Deterministic:** admin checks, DB writes, dedup, cosine candidate selection,
  confidence thresholds, action policies, exact-match patch application, audit.

## Deployment

`forge deploy` to Atlassian's cloud; no other hosting. Egress allowlisted in
`manifest.yml` to the three LLM provider domains. See [forge-native.md](forge-native.md)
for commands and operational gotchas.
