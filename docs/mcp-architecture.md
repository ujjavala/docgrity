# Docgrity — MCP Architecture

MCP (Model Context Protocol) is the standard interface between agents and external systems.
Agents never call external APIs directly.

## Source capability contract

Every source connector implements a common contract:

```
SourceConnector
    ├── discover()      # enumerate scannable scopes (spaces, channels, repos)
    ├── search()
    ├── get()
    ├── get_history()
    ├── get_people()
    └── capabilities()  # declared read/write capabilities
```

Actions are capability-based and policy-gated, e.g. Confluence: `READ_PAGE`, `READ_HISTORY`,
`READ_COMMENTS`, `WRITE_COMMENT`, `UPDATE_PAGE` (write capabilities disabled by default).

## Confluence MCP server (MVP 1)

Tools:

```
search          CQL / text search across selected spaces
get_page        page content + metadata (v2 REST)
get_children    child pages
get_history     version history
get_comments    footer + inline comments
get_owner       page owner / author metadata
add_comment     create or update a Docgrity comment  [policy-gated]
update_page     stubbed, disabled in MVP 1           [policy-gated]
```

Implementation: Python MCP SDK server wrapping a thin `httpx` Confluence Cloud REST v2 client.
Auth: API token (email + token) for development; per-tenant OAuth 2.0 (3LO) or Forge-mediated
calls for production tenants.

## Future MCP servers

- **Slack MCP** — search, get_message, get_thread, get_channel, find_people, post_message.
- **GitHub MCP** — search_code, get_file, get_history, get_pr, get_review, get_codeowners,
  create_issue, create_pr.
- **Knowledge MCP** — Docgrity itself exposes MCP: search_knowledge, get_claims,
  get_decisions, get_questions, get_findings, get_relationships, get_owner_candidates,
  create_finding, update_finding. This is how agents read/write the knowledge model and how
  external assistants will eventually consume Docgrity.

## Permissions & safety

- Each agent has an explicit MCP tool allowlist (see agent-architecture.md).
- Write tools evaluate action policy + tenant configuration before executing, and emit
  `audit_event` rows.
- Source ACLs are enforced **before** content enters any agent context: if a user cannot see
  a source, agents acting for that user must not surface its content.
- All MCP calls are traced (OpenTelemetry) with scan_id / task_id / agent attribution.
