# Docgrity — Marketplace listing

> Source material for the Atlassian Marketplace listing form. Copy fields into
> the developer console when creating the listing.

## App name

Docgrity — Knowledge Integrity for Confluence

## Tagline (≤130 chars)

Find where your wiki disagrees with itself: duplicates, contradictions and open
questions — with evidence and likely owners.

## Summary

Your Confluence has pages that contradict each other, duplicate each other, and
ask questions nobody ever answered. Docgrity is an AI agent that scans your
spaces, finds these integrity problems, shows the evidence side by side, and
identifies who most likely owns the fix.

**Bring your own AI key.** Docgrity does not proxy your content through our
servers — there are no servers. It runs entirely on Atlassian Forge and calls
the LLM provider *you* configure (Google Gemini, OpenAI, or Anthropic) with
*your* API key. Your content goes only where you already send it.

### What it finds

- **Duplicates** — near-identical pages that should be merged, with a
  recommended survivor.
- **Contradictions** — pages that state conflicting facts (dates, owners,
  processes, numbers), with the conflicting claims quoted as evidence.
- **Open questions** — unanswered questions and stale TODOs living in your
  pages.

### What it does about them

- Dashboard with findings by type and severity, filterable per space.
- Potential owner inference from edit history — always labelled *potential*,
  never asserted.
- One-click actions, always human-approved: merge & redirect, draft a fix,
  notify the owner, ignore.
- A **Rovo agent** so you can ask "what does my wiki disagree about?" in chat.
- Full audit trail of every agent action.

### Why teams pick Docgrity

- **Zero infrastructure** — 100% Atlassian Forge: Forge SQL, Forge KVS, Forge
  queues. Nothing to host, no vendor cloud holding your data.
- **BYO LLM key** — no per-token markup; your data-processing relationship is
  with your existing AI provider, under your existing terms.
- **Evidence or it didn't happen** — every finding quotes the exact text it is
  based on. No unexplainable AI verdicts.
- **Humans approve every change** — the agent never edits or archives a page
  on its own.

## Category

AI / Content management / Document management

## Search keywords

duplicate pages, contradictions, content quality, stale documentation, wiki
cleanup, knowledge management, documentation audit, AI agent, Rovo

## Screenshots to capture (before submission)

1. Overview dashboard with findings by type/severity
2. Findings list with confidence + potential owners
3. Finding detail with side-by-side evidence
4. Draft-fix flow (human approval step visible)
5. Settings — provider choice showing BYO key
6. Rovo chat asking "what does my wiki disagree about?"

## Pricing suggestion

- **Free** during beta (build installs + reviews).
- Then Standard: ~USD 1.25/user/month via Atlassian licensing, free ≤10 users
  (Atlassian's starter-tier convention).

## Support

- Support contact: <fill in email>
- Documentation: repository `docs/` (publish to a public site before listing)
- Privacy policy: see `marketplace/privacy-policy.md` (host on a public URL)

## Review-readiness checklist

- [x] Production deploy with egress limited to the 3 LLM provider domains
- [x] Dev-only Ollama provider gated behind `ENABLE_DEV_PROVIDERS` (off in prod)
- [x] Secrets only in Forge KVS secrets; never logged or returned to UI
- [x] Admin-only settings enforced server-side
- [x] All destructive actions human-approved + audited
- [ ] Privacy policy hosted at a public URL
- [ ] Support email / help desk set up
- [ ] Screenshots + demo video captured
- [ ] Vendor account created on marketplace.atlassian.com
- [ ] Data-security & privacy questionnaire (Marketplace "Trust" tab) completed
- [ ] Test install on a fresh site as a non-admin user
