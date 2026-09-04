# docgrity-mcp

MCP server for [Docgrity](https://docgrity.com) — bring knowledge-integrity
findings (duplicate docs, contradictions, stale content) into **your own
agent**: VS Code Copilot, Claude Desktop/Code, Cursor, or any MCP host.

This package is a thin client for the Docgrity API. All analysis runs in the
Docgrity service; your agent does the conversing.

## Install & run

```sh
uvx docgrity-mcp        # or: pip install docgrity-mcp && docgrity-mcp
```

## Configuration (environment)

| Variable | Description |
|---|---|
| `DOCGRITY_API_URL` | Docgrity API base URL (default `https://api.docgrity.com`) |
| `DOCGRITY_API_KEY` | Your tenant API key |
| `DOCGRITY_TENANT_ID` | Your tenant id |

## VS Code (`.vscode/mcp.json`)

```json
{
  "servers": {
    "docgrity": {
      "type": "stdio",
      "command": "uvx",
      "args": ["docgrity-mcp"],
      "env": {
        "DOCGRITY_API_KEY": "${input:docgrity-key}",
        "DOCGRITY_TENANT_ID": "${input:docgrity-tenant}"
      }
    }
  }
}
```

## Tools

- `list_findings` — list findings (filter by status)
- `get_finding` — a finding with evidence and potential owners
- `trigger_scan` — run an ingest and/or duplicate scan
- `list_scans` — recent scans with stats

## License

MIT — see [LICENSE](LICENSE). The Docgrity service itself is a commercial
product; an API key requires a Docgrity account.
