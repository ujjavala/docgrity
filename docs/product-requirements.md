# Docgrity — Product Requirements

**Tagline:** Find what your organisation doesn't agree on — and get the right person to fix it.

## Summary

Docgrity is an agentic knowledge-integrity platform. It continuously analyses organisational
knowledge (Confluence first; Slack, GitHub, and others later) and detects:

- duplicate documentation
- contradictory information
- unresolved / open-ended questions
- decisions discussed but never documented
- stale documentation and documentation/code drift
- missing or unclear ownership

It does not stop at "something looks wrong". Every finding answers:

> What is wrong? Why do we think so? What evidence supports this?
> Who can potentially fix it? What should they do? Has it since been resolved?

The loop is: **Detect → Understand → Assign → Act → Verify**.

## Problem

Knowledge is fragmented across Confluence, Slack, and repositories. Humans are expected to
reconcile the sources manually. The result: engineers follow outdated docs, decisions get lost in
chat, duplicate pages proliferate, ownership is unclear, and AI assistants return contradictory
answers. Existing tools answer "is this page healthy?"; Docgrity answers
**"can we trust this information, and who needs to do something about it?"**

## Goals

- **G1 Detect** — duplicates, contradictions, open questions, undocumented decisions, stale
  content, code/doc drift, missing owners.
- **G2 Explain** — every finding carries affected sources, claims/evidence, reasoning,
  confidence, and a recommended action.
- **G3 Identify potential owners** — probabilistic, evidence-backed, always labelled
  *potential* unless an authoritative ownership source exists.
- **G4 Act** — Confluence comments, Slack notifications, Jira/GitHub issues, suggested PRs
  (approval-gated).
- **G5 Verify** — after action, re-fetch, re-analyse, and mark findings RESOLVED / STILL_OPEN.
- **G6 Arbitrary source combinations** — users control the analysis scope.

## Non-goals (MVP)

No automatic deletion, rewriting, or merging of content. No unrestricted agent tool execution.
No general-purpose enterprise search or generic chatbot. No exhaustive connector coverage.
MVP priority: **high-confidence detection + explainability + ownership + comments**.

## Personas

| Persona | Core question |
|---|---|
| Software engineer | Does the documentation match what the code actually does? |
| Tech lead / architect | What decisions are unresolved or contradictory? |
| Engineering manager | Where is knowledge becoming unreliable? |
| Documentation owner | Which docs need attention and who should fix them? |
| AI / platform team | Can our internal AI safely rely on this knowledge? |

## Core concepts

`KnowledgeItem` (any piece of knowledge), `Claim` (extracted factual assertion),
`Finding` (identified problem with evidence), `Person` (potential owner),
`Decision`, `Question`. See [knowledge-model.md](knowledge-model.md).

## Finding types

`DUPLICATE`, `CONTRADICTION`, `OPEN_QUESTION`, `UNDOCUMENTED_DECISION`, `STALE`,
`CODE_DOC_DRIFT`, `MISSING_OWNER`, `TERMINOLOGY_DRIFT`.

## MVP roadmap

1. **MVP 1 (current)** — Confluence only: connect, select spaces, ingest, embeddings,
   duplicate detection + LLM verification, ownership inference, findings, Confluence comments,
   verification. Distributed as a **Forge app** targeting the Atlassian Marketplace, with heavy
   analysis in the external Docgrity backend (Forge Remote).
2. **MVP 2** — contradictions, claims, open questions, recommended actions, dashboard.
3. **MVP 3** — Slack ingestion, decision detection, cross-source comparison, notifications.
4. **MVP 4** — GitHub: repo indexing, ADR analysis, code/doc drift, CODEOWNERS.
5. **MVP 5** — VS Code extension.
6. **MVP 6** — full agentic platform: connector registry, delegation, memory, scheduled scans,
   action policies.

## Killer demo (MVP 1 acceptance)

1. Connect Confluence, scan 100–500 pages.
2. System reports duplicate clusters, contradictions, unresolved questions.
3. Open a duplicate: recommended action MERGE, potential owner with confidence + evidence.
4. Click "Add Confluence comment" → 🤖 Docgrity comment appears on the page.
5. A human merges the docs; verification run marks the finding ✅ RESOLVED and updates the
   comment.

## Success metrics (MVP)

- >85% precision on duplicate detection
- >90% precision on high-confidence contradictions (MVP 2)
- >70% top-3 owner recall
- 80% of findings contain useful evidence
- Median time from detection → resolution (product north star)

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| False positives | High thresholds, evidence required, human review, eval dataset, no auto-modification |
| Incorrect ownership | Always "potential owner" + evidence unless authoritative |
| Agent cost | Cheap retrieval → embeddings → candidate filtering → small model → strong model only when required |
| Permission leakage | Source-level ACL enforcement before agent context creation |
| Agent complexity | Coordinator + specialised agents, no uncontrolled swarm |
| Distrust of AI comments | Every comment includes evidence, confidence, potential owner, recommended action, finding ID |
