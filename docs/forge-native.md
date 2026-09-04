# Docgrity — Forge-native implementation

This is the shipping implementation of Docgrity: a **zero-infrastructure Atlassian Forge
app**. All compute, storage, queues and scheduling run on Atlassian's Forge platform.
The only external calls are to the LLM provider the tenant admin configures (BYO key).

> A previous FastAPI/PostgreSQL/arq reference implementation lives in git history
> (checkpoint commit "Docgrity MVP: FastAPI backend, agents, MCP connectors, Forge
> remote app"). It was removed from the working tree once the Forge-native port shipped.

## Runtime layout (`apps/forge`)

| File | Role |
|---|---|
| `manifest.yml` | Modules: global page, resolvers, Forge SQL (mysql), 2 async queues, hourly scheduled trigger, Rovo agent + 6 actions. Egress restricted to the 3 LLM provider domains. |
| `src/index.js` | Resolvers (dashboard API): stats, findings, scans, settings, human-approved actions (notify owner, merge & redirect, draft/apply fix). |
| `src/migrations.js` | Forge SQL DDL via `migrationRunner`; run hourly by scheduled trigger and lazily from `getStats` on first load. |
| `src/db.js` | `sql.prepare().bindParams()` helpers + `audit()` (every action writes `audit_event`). |
| `src/llm.js` | Provider-agnostic LLM layer: Gemini / OpenAI / Anthropic. Model catalogs, JSON-typed completion with retry, embeddings, cosine similarity. Key stored via `kvs.setSecret` — never in SQL, logs, or responses. |
| `src/agents.js` | Versioned prompts (duplicate v1, contradiction v1, open_question v1, action v2, editor v1) + typed output validation. Findings record `model` + `prompt_version`. |
| `src/confluence.js` | All Confluence access via `api.asApp().requestConfluence` (v2 REST). Pages, comments, page update/archive, `isSiteAdmin` group check. |
| `src/scans.js` | Queue consumer (`scans`, 900 s timeout): ingest → embed (or capped pair fallback when provider has no embeddings) → LLM assess → confidence gate → finding + evidence + potential owners → policy-gated comment. |
| `src/notify.js` | Queue consumer (`notify`): drafts + posts an owner-mention comment for an existing finding. |
| `src/rovo.js` | Rovo agent action handler (single function, dispatch on `moduleKey`): stats, list/get findings, trigger scan, dismiss, notify. |
| `src/frontend/index.jsx` | UI Kit dashboard: overview → list → detail, plus Settings (provider/model/key, admin-gated). |

## Data model (Forge SQL, per-installation = per-tenant)

`knowledge_item` (page content + JSON-text embedding), `finding`,
`finding_evidence`, `finding_person` (potential owners), `scan`, `audit_event`,
`comment_action`. No `tenant_id` — the Forge installation is the tenant boundary.

## Key decisions

- **BYO LLM key, any provider.** Admin picks Gemini/OpenAI/Anthropic + model in
  Settings. Key is a Forge secret. Anthropic has no embeddings API → candidate
  selection falls back to capped all-pairs comparison.
- **Egress allowlist** in the manifest means the app *cannot* send data anywhere except
  the chosen provider. Custom/self-hosted LLM endpoints are not possible on Forge.
- **Settings writes are admin-only**, enforced server-side (`isSiteAdmin` group check),
  denials audited.
- **As-app identity everywhere**: comments and page edits are authored by the
  "docgrity" app user; source permissions are enforced by Confluence itself.
- **Destructive actions** (archive, page edit, dismiss) only run from explicit human
  clicks/chat requests; all are audited with `policy_decision: HUMAN_APPROVED`.
- **Rovo agent** is the free conversational surface (Atlassian's LLM). It cannot be
  used programmatically for batch scans, so scans still use the tenant's key.

## Dev workflow

```bash
cd apps/forge
forge lint                     # manifest + scope validation (--fix for scopes)
forge deploy --environment development --no-verify --non-interactive
forge install --upgrade --non-interactive \
  --site one-atlas-nbtc.atlassian.net --product confluence --environment development
forge logs --environment development   # runtime logs
```

Gotchas learned the hard way:
- Forge caches the UI bundle — hard refresh (Cmd+Shift+R) after deploy.
- Scope/egress changes trigger `MAJOR_VERSION_RULE` and require `forge install --upgrade`.
- Forge SQL is MySQL-engine: positional `?` params only, no vector type (embeddings
  stored as JSON text, cosine computed in JS).
- Queue payloads must be `{ body: {...} }`, max 50 events / 200 KB per push.
- Migrations only auto-run hourly — `getStats` has a lazy fallback for first load.
