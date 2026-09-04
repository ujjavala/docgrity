# Docgrity

**Find what your organisation doesn't agree on — and get the right person to fix it.**

Docgrity is an agentic knowledge-integrity platform that checks whether an organisation's
documentation agrees with itself: duplicate pages, contradictory claims, unanswered open
questions — each finding backed by evidence and linked to *potential* owners.

Two zero-infrastructure implementations:

1. **Atlassian Forge app** (`apps/forge`) — ships to the Atlassian Marketplace. Runs
   entirely on Forge (SQL, async events, scheduled triggers). Tenants bring their own
   LLM API key (Gemini / OpenAI / Anthropic) and get a dashboard, Confluence comments,
   and a Rovo agent. See [docs/forge-native.md](docs/forge-native.md).
2. **VS Code extension** (planned) — same checks for repository docs, powered by the
   user's own GitHub Copilot subscription via `vscode.lm`.
   See [docs/vscode-extension.md](docs/vscode-extension.md).

> The original FastAPI/PostgreSQL reference implementation is preserved in git history
> (checkpoint commit) and was removed from the working tree after the Forge-native port.

## Documentation

- [Product requirements](docs/product-requirements.md)
- [Architecture](docs/architecture.md)
- [Forge-native implementation](docs/forge-native.md)
- [VS Code extension plan](docs/vscode-extension.md)
- [Agent architecture](docs/agent-architecture.md)
- [Knowledge model](docs/knowledge-model.md)
- [Security](docs/security.md)
- [Evaluation](docs/evaluation.md)

## Development (Forge app)

Prerequisites: Node 22+, [Forge CLI](https://developer.atlassian.com/platform/forge/getting-started/) (`npm i -g @forge/cli`), an Atlassian developer site.

```bash
cd apps/forge
npm install
forge lint
forge deploy --environment development --no-verify --non-interactive
forge install --site <your-site>.atlassian.net --product confluence \
  --environment development
```

Then in Confluence: **Apps → Docgrity → Settings**, choose an AI provider and paste an
API key (site admins only), and run a scan.

## Repository layout

```
apps/forge/          Forge app: manifest, resolvers, agents, consumers, UI
  src/               backend functions (see docs/forge-native.md)
  src/frontend/      UI Kit dashboard + settings
docs/                architecture and implementation documents
```
