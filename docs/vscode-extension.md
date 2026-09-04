# Docgrity for VS Code — implementation plan

**Status: not started.** This document is the blueprint so implementation can begin in a
fresh session without re-deriving decisions.

## Goal

Bring Docgrity's knowledge-integrity checks to repository documentation (markdown, ADRs,
READMEs, code comments) inside VS Code — at **zero cost to us**: all LLM calls go through
the user's own GitHub Copilot subscription via the VS Code Language Model API
(`vscode.lm`). No servers, no keys, no telemetry backend.

## Surface symmetry with the Forge app

| Forge app (Confluence) | VS Code extension (repo docs) |
|---|---|
| Rovo agent in chat | `@docgrity` chat participant in Copilot Chat |
| Rovo actions | Language-model tools (`vscode.lm.registerTool`) usable by Copilot agent mode |
| Dashboard global page | Findings tree view + webview detail panel |
| Forge SQL | Workspace state / SQLite file in `.docgrity/` (gitignored) |
| Confluence comments | Diagnostics (squiggles) + code actions on markdown files |
| BYO provider key | User's Copilot subscription (`vscode.lm.selectChatModels`) |

## Architecture

```
extension/
  package.json          # contributes: chatParticipants, languageModelTools,
                        # views (docgrity.findings), commands, configuration
  src/
    extension.ts        # activate(): register participant, tools, tree view, commands
    scanner/
      corpus.ts         # collect docs: **/*.md, ADRs, configurable globs; chunk + hash
      candidates.ts     # candidate pair selection (embeddings if available, else
                        # TF-IDF cosine — cheap and local)
      scan.ts           # orchestrator: pairs -> LLM assess -> confidence gate -> findings
    agents/
      prompts.ts        # SAME versioned prompts as apps/forge/src/agents.js
                        # (duplicate v1, contradiction v1, open_question v1)
      assess.ts         # vscode.lm chat request + JSON extraction + typed validation
                        # (port of completeJson/extractJson from forge llm.js)
    findings/
      store.ts          # findings persistence (workspaceState or .docgrity/findings.json)
      tree.ts           # TreeDataProvider: type -> finding -> evidence
      diagnostics.ts    # DiagnosticCollection mapping evidence excerpts to doc ranges
    chat/
      participant.ts    # @docgrity participant: health summary, explain finding,
                        # run scan — mirrors rovo.js dispatch
      tools.ts          # lm tools: docgrity_scan, docgrity_list_findings,
                        # docgrity_get_finding — so Copilot agent mode can call them
```

## Key APIs (verified names)

- `vscode.chat.createChatParticipant('docgrity.chat', handler)` — chat participant.
- `vscode.lm.selectChatModels({ vendor: 'copilot', family: 'gpt-4o' })` then
  `model.sendRequest(messages, {}, token)` — user-consented, quota on user's Copilot.
- `vscode.lm.registerTool('docgrity_scan', ...)` + `languageModelTools` contribution
  point — lets Copilot agent mode invoke scans autonomously (with user approval UI).
- `vscode.languages.createDiagnosticCollection('docgrity')` — evidence as squiggles.
- Embeddings: **no embeddings API in vscode.lm** — use local TF-IDF/BM25 for candidate
  selection (deterministic, free), LLM only for pairwise assessment.

## Porting rules

1. Reuse prompt text from `apps/forge/src/agents.js` verbatim (keep versions in sync;
   findings record `prompt_version`).
2. Same architectural principles: typed outputs only, evidence required, potential
   ownership language (owner = last git author of the file via `git log -1 --format=%an`
   — label as *potential*), untrusted-content guard in every prompt.
3. Confidence thresholds in extension settings (`docgrity.thresholds.*`), not constants.
4. No network calls other than `vscode.lm` (Copilot handles transport). Optional later:
   sync findings to the Forge app via Atlassian REST with the user's own API token.

## MVP slice (build in this order)

1. `corpus.ts` + `candidates.ts` + `assess.ts` with duplicate check only; command
   `Docgrity: Scan workspace docs`; results in output channel. **Proves the lm loop.**
2. Findings tree view + diagnostics.
3. Chat participant (`@docgrity how healthy are our docs?`).
4. lm tools for agent mode; contradiction + open-question checks.
5. Marketplace packaging (publisher, README, icon, `vsce package`).

## Constraints & notes

- `vscode.lm` requests need user consent on first use per extension; quota errors
  (`LanguageModelError.Blocked`) must degrade gracefully.
- Copilot models rotate: always `selectChatModels` at call time, prefer family match,
  fall back to any available model.
- Large repos: cap corpus at N chunks (setting), incremental scan on file save via
  content hashing — mirror `knowledge_item.content_hash` semantics from the Forge app.
