# Docgrity launch posts

## DEV.to / dev++ launch post

**Title:** In the age of AI docslop, your wiki disagrees with itself more than ever — so I built an agent that catches it

**Tags:** ai, atlassian, documentation, showdev

---

We're generating documentation faster than we've ever been able to read it.

AI writes our design docs, our runbooks, our onboarding guides, our meeting summaries.
Every sprint adds pages; almost nothing retires them. The result isn't a knowledge
base — it's **docslop**: an ever-growing pile of plausible-sounding pages where the
onboarding doc says deploys go through Jenkins, the runbook says GitHub Actions, two
near-identical pages describe the same process differently, and "TBD — confirm with the
team" has been sitting there for a year.

The cognitive load lands on humans: nobody can hold the whole wiki in their head anymore,
so nobody notices the contradictions until one bites someone at 2am.

And it's about to get worse in an interesting way. **Your docs are no longer just for
humans.** Agentic workflows, spec-driven development, RAG pipelines, AI harnesses — they
all treat your documentation as ground truth. When your wiki contradicts itself, you're
not just confusing the new hire; you're feeding conflicting context straight into every
AI agent that reads it. Garbage in, confidently-wrong agent out. If AI is going to build
from your specs, your specs need to actually agree with each other.

So I built **Docgrity** — an agent whose only job is to find where your Confluence wiki
disagrees with itself:

- **Contradictions** — pages that make conflicting claims about the same topic, with the
  exact conflicting excerpts quoted as evidence
- **Duplicates** — semantically overlapping pages that should be merged, found via
  embeddings, confirmed by an LLM
- **Open questions** — unresolved "TBD", "TODO", "who owns this?" markers buried in
  supposedly authoritative docs

For each finding it identifies a *potential* owner (last meaningful author, labelled as
potential — never asserted) and, with one click and your approval, posts a polite
Confluence comment asking them to reconcile it. Nothing is ever changed or posted
without human approval. It's AI used to *reduce* doc entropy, not add to it — the agent
never writes a page, it only asks humans to fix the ones that disagree.

### The interesting constraint: zero infrastructure

The whole thing runs on **Atlassian Forge** — no servers, no database I operate, no
queues, no vector DB:

- Forge SQL (MySQL) stores findings; embeddings live as JSON columns — at wiki scale
  (thousands of pages, not billions) brute-force cosine similarity in JS is fine
- Forge async events fan out scan work per space
- Scheduled triggers re-scan weekly and run a privacy job that erases data for
  deactivated Atlassian accounts
- The UI is Forge UI Kit, rendered inside Confluence

**You bring your own LLM key** (Gemini, OpenAI, or Anthropic — Gemini has a free tier).
Your key is stored encrypted in Forge's secret store, and the app's egress is
allowlisted to exactly three LLM API domains. Your page content never goes anywhere
else. That's not a policy claim — it's enforced by the platform manifest.

### Agent design notes

- Every LLM call returns **typed JSON validated in code** — no prose parsing
- Every finding requires **verbatim evidence excerpts**, which are checked against the
  source page before the finding is stored — hallucinated quotes get dropped
- Prompts are versioned; every finding records the model + prompt version that produced it
- Wiki content is treated as untrusted input — it can't override agent instructions

### Try it

It's free — I don't even have a billing account attached, so I couldn't charge you if I
wanted to.

→ **[ujjavala.github.io/docgrity-site](https://ujjavala.github.io/docgrity-site/)** —
screenshots, a full walkthrough of the three scenarios, and the install link
(you need to be a Confluence site admin).

Feedback very welcome — especially on false-positive rates on your real wikis.

---

## LinkedIn post

Your wiki is lying to you — and Docgrity can prove it. 📄⚔️📄

Every organisation's documentation eventually contradicts itself: two pages describing
the same process differently, near-duplicate docs drifting apart, "TBD — confirm with
the team" sitting untouched for a year.

I built **Docgrity**, a free Confluence app that scans your spaces and finds:

🔍 Contradictions — with the exact conflicting excerpts as evidence
🔁 Duplicate pages that should be merged
❓ Unresolved open questions buried in "authoritative" docs

For each finding it suggests a *potential* owner and — only with your approval — posts a
polite Confluence comment asking them to reconcile it. Humans stay in the loop for
every action.

What made it fun to build: the entire thing runs on Atlassian Forge with **zero
infrastructure** — no servers, no database, no vector store. You bring your own AI key
(Gemini / OpenAI / Anthropic), and the app is platform-restricted from sending your
content anywhere else.

It's free. Screenshots, walkthrough, and the install link:
👉 https://ujjavala.github.io/docgrity-site/

Would love feedback from anyone whose wiki has ever disagreed with itself (so:
everyone).

#AI #Confluence #Atlassian #KnowledgeManagement #BuildInPublic
