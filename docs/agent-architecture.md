# Docgrity — Agent Architecture

## Principles

- Specialised agents, controlled by deterministic orchestration — not an uncontrolled swarm.
- Agents communicate through **structured task messages**, never free-form chat.
- Agents access external systems **only via MCP tools** on an explicit allowlist.
- Every LLM output is a typed Pydantic schema. No prose parsing.
- Every inference has a confidence score; every finding has evidence.
- External source content is **untrusted data** and is always delimited as such in prompts.
- Destructive or consequential actions require policy approval and human confirmation.

## Agent roster (MVP 1)

| Agent | Purpose | Reads | Writes |
|---|---|---|---|
| Duplicate | Verify candidate duplicate pairs, recommend action + canonical page | knowledge.search, confluence.get_page | knowledge.create_finding |
| Ownership | Rank potential owners with evidence | knowledge items, page owner/author/editors | finding_person |
| Action | Execute policy-approved actions (Confluence comments only in MVP 1) | findings | confluence.add_comment, comment_action |
| Verification | Re-fetch, re-analyse, close the loop | confluence.get_page, findings | finding status, comment update |

Added in later MVPs: Coordinator, Discovery, Contradiction, Question, Conversation (Slack),
Code (GitHub), Resolution.

## Full pipeline shape (target)

```
Coordinator → Discovery / Source agents → Analysis agents (duplicate, contradiction,
question, drift) → Ownership → Resolution → Action → Verification
```

Each stage is distinct. **Never collapse detection, reasoning, ownership, recommendation,
action, and verification into one prompt.**

## Task messages

```json
{
  "task_id": "task-123",
  "parent_task_id": "task-100",
  "from_agent": "coordinator",
  "to_agent": "duplicate-agent",
  "task_type": "VERIFY_DUPLICATE",
  "input": {"item_a": "ki-1", "item_b": "ki-2"}
}
```

Responses carry `status`, `results`, and `evidence`. Persisted as `agent_task` rows with
model, prompt_version, token_usage, cost, and error.

## LLM abstraction

Agents request **capabilities**, not models:

```
reasoning.high    → strongest reasoning model (default: Anthropic Claude)
reasoning.fast    → fast/cheap reasoning (default: small OpenAI model)
classification    → cheap classification (default: small OpenAI model)
embedding         → embedding model (default: OpenAI text-embedding-3-small)
```

The model router maps capability → provider/model and is configuration-driven. Providers:
`OpenAIProvider`, `AnthropicProvider` (both implemented from day one).

Cost control ladder: cheap retrieval → embeddings → candidate filtering → small model →
strong model only when required.

## Structured output example

```python
class DuplicateResult(BaseModel):
    is_duplicate: bool
    confidence: float
    overlap: list[str]
    recommended_action: DuplicateAction  # KEEP_A | KEEP_B | MERGE | ARCHIVE_A | ARCHIVE_B | REVIEW | UNKNOWN
    canonical_candidate: str | None
    explanation: str
```

## Ownership reasoning

Signals: page owner, author, last editor, frequent editors (MVP 1); later CODEOWNERS, git
history, PR authors, Slack participation, service ownership. Output is always
**"potential owner"** with per-candidate confidence and evidence bullets, unless an
authoritative ownership source exists.

## Tool permissions

Each agent has an explicit tool allowlist enforced by the harness. Example: the Duplicate
agent may read pages and create findings but may never call `confluence.update_page` or any
delete operation. The Action agent has broader write access but every call passes policy
evaluation and is audited.

## Prompt management

Prompts live in `prompts/<agent>/v<N>.md` and are versioned. Every finding records
`model`, `prompt_version`, `temperature`, and `input_hash` for evaluation and reproducibility.

## Memory

- **Working memory** — current task context (assembled per task; retrieval, never full-corpus dumps).
- **Knowledge memory** — persisted knowledge items, claims, entities, findings (PostgreSQL).
- **Agent memory** — previous task outcomes (`agent_task`).
- **Source memory** — source metadata, versions, scan history.
