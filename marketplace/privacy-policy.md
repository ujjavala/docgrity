# Docgrity Privacy Policy & Data Statement

_Last updated: 5 September 2026. Host this at a public URL before Marketplace
submission and replace placeholders._

## Who we are

Docgrity is published by <VENDOR NAME> ("we"). Contact: <SUPPORT EMAIL>.

## The short version

- Docgrity runs **entirely inside Atlassian Forge** on your Atlassian site.
  We operate **no servers** and can never access your Confluence content.
- Page content is sent to **exactly one external service: the AI provider you
  choose and configure with your own API key** (Google Gemini, OpenAI, or
  Anthropic). That processing happens under **your** agreement with that
  provider, not ours.
- We receive **no data at all** — no content, no telemetry, no analytics.

## What data the app processes

| Data | Where it lives | Purpose |
| --- | --- | --- |
| Page text, titles, version history | Forge SQL (your site's Forge storage, Atlassian-hosted) | scanning for duplicates/contradictions/open questions |
| Text embeddings of page content | Forge SQL | candidate-pair selection |
| Findings, evidence quotes, audit log | Forge SQL | the product |
| Contributor account IDs and display names | Forge SQL | potential-owner inference (labelled *potential*) |
| Your AI provider API key | Forge KVS **secret** storage | calling your AI provider; never logged, never shown in the UI, never stored in SQL |
| Provider/model choice, thresholds | Forge KVS | configuration |

All of the above is stored in Atlassian's Forge platform storage, scoped to
your installation, and is deleted by Atlassian when you uninstall the app,
per [Forge data lifecycle](https://developer.atlassian.com/platform/forge/storage/).

## What leaves Atlassian

Only requests to the AI provider **you** configured, containing the page text
being analysed. Egress is platform-enforced (Forge manifest allowlist) to:

- `generativelanguage.googleapis.com` (Google Gemini)
- `api.openai.com` (OpenAI)
- `api.anthropic.com` (Anthropic)

Only the one provider you select is ever called. Review your chosen provider's
data-use terms (e.g. API-tier no-training commitments) — your key, your terms.

## What we collect

Nothing. We have no backend, no telemetry endpoint, and no access to your
site, content, findings, or keys.

## Permissions (Confluence scopes)

- Read pages, spaces, versions and contributors — to scan and infer ownership.
- Write pages and comments — only for actions a human explicitly approves in
  the dashboard (merge & redirect, apply fix, post comment).
- App storage — findings, embeddings, settings, audit log.

## Security measures

- API keys stored exclusively in Forge KVS **secret** storage.
- Settings changes restricted to Confluence site admins, enforced server-side.
- Every agent action is recorded in an audit log inside your installation.
- All LLM output is schema-validated; page content is treated as untrusted
  input and cannot override agent instructions.
- No destructive action (page edit, archive) occurs without human approval.

## Data subject rights & retention

Docgrity stores no personal data outside your Atlassian site. Contributor
names/IDs mirrored into findings are removed when findings are deleted or the
app is uninstalled. Per Atlassian's Forge user privacy guidelines, a weekly
scheduled job inside your installation refreshes stored display names and
automatically erases all stored personal data for accounts that have been
closed or erased. For rights requests concerning Confluence data itself,
contact your Atlassian admin; for the AI provider, see that provider's policy.

## Changes

We will update this page and the "last updated" date when practices change.

## Contact

<SUPPORT EMAIL>
