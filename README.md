# Docgrity

**Find what your organisation doesn't agree on — and get the right person to fix it.**

Docgrity is an agentic knowledge-integrity platform that continuously checks whether an
organisation's documentation, code, decisions and conversations agree with each other.
MVP 1 targets Confluence: duplicate detection, ownership inference, findings with evidence,
and Confluence comments — distributed as an Atlassian Forge app with analysis in an external
backend.

## Documentation

- [Product requirements](docs/product-requirements.md)
- [Architecture](docs/architecture.md)
- [Agent architecture](docs/agent-architecture.md)
- [MCP architecture](docs/mcp-architecture.md)
- [Knowledge model](docs/knowledge-model.md)
- [Security](docs/security.md)
- [Evaluation](docs/evaluation.md)

## Development

Prerequisites: [uv](https://docs.astral.sh/uv/), Docker.

```bash
cp .env.example .env          # fill in credentials
uv sync                       # install dependencies
docker compose up -d postgres redis
uv run alembic upgrade head   # apply migrations
uv run uvicorn docgrity.api.main:app --reload   # API at http://localhost:8000
uv run pytest                 # tests
uv run ruff check .           # lint
```

Or run the whole stack in containers:

```bash
docker compose up --build
```

## Repository layout

```
apps/forge/        Atlassian Forge app (Confluence surface)
src/docgrity/
  api/             FastAPI application
  agents/          duplicate, ownership, action, verification
  mcp/confluence/  Confluence MCP server + REST client
  core/            models, schemas, llm router, policies, config
  workflows/       scan + ingestion pipelines (arq)
prompts/           versioned prompt files
evaluations/       eval datasets + harness
migrations/        Alembic
docs/              architecture documents
tests/
```
