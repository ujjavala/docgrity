# Docgrity for Confluence (Forge app)

Zero-infrastructure Forge app: ingestion, agents, findings, dashboard and Rovo agent all
run inside the Forge runtime (Forge SQL, `@forge/events` queues, scheduled triggers).
There is no external backend. See [docs/forge-native.md](../../docs/forge-native.md).

## Marketplace compliance checklist

- **Naming**: listed as "Docgrity for Confluence" (product name after the app name).
- **Auth**: Confluence is accessed via `api.asApp()` — no basic auth anywhere.
- **Performance**: no blocking work at render; findings load async with a spinner.
- **Egress**: allowlisted in `manifest.yml` to the three LLM provider domains only;
  in no-AI (heuristics) mode nothing leaves the site.
- Forge apps keep 100% of revenue up to USD 1M lifetime per vendor.

## One-time setup (requires your Atlassian account — do this yourself)

```sh
npm install -g @forge/cli@latest
forge login                        # email + API token from id.atlassian.com
cd apps/forge
npm install
forge register                     # writes the real app id into manifest.yml
```

## Deploy & install

```sh
forge deploy --environment development --no-verify --non-interactive
forge install --site <your-site>.atlassian.net --product confluence \
  --environment development
# scope changes need: forge install --upgrade
```

Then in Confluence: **Apps → Docgrity → Settings** (site admins only), optionally add an
AI provider key (Gemini / OpenAI / Anthropic), and run a scan. Heuristic duplicate and
open-question detection works with no key at all.

## Tests

```sh
npm test
```
