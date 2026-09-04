# Docgrity — Evaluation Framework

Evaluation is a first-class component. The product optimises for **precision first**: a false
positive that publicly comments on someone's Confluence page is much worse than missing a
low-confidence issue.

## Curated datasets

Build and maintain labelled datasets in `evaluations/datasets/`:

```
duplicate pairs            (positive + hard negatives)
contradiction pairs        (MVP 2)
non-contradictions         (MVP 2)
open questions / non-questions (MVP 2)
ownership examples         (item → correct owner)
```

Target sizes ~100 per category; start small (10–20) and grow with every false positive found
in real usage. Every production false positive becomes a regression case.

## Metrics

Global: precision, recall, false-positive rate, owner accuracy, recommended-action accuracy.

Per agent:

| Agent | Metrics |
|---|---|
| Duplicate | duplicate precision, recall, canonical-page accuracy |
| Contradiction (MVP 2) | precision, false-positive rate, evidence correctness |
| Ownership | top-1 owner accuracy, top-3 owner recall, evidence quality |
| Action | recommendation accuracy, unsafe-action rate |

MVP acceptance thresholds: duplicate precision >85%, top-3 owner recall >70%, ≥80% of findings
with useful evidence.

## Reproducibility

Every finding stores `model`, `prompt_version`, `temperature`, `input_hash`. Prompt changes
bump the version (versioned `PROMPTS` in `apps/forge/src/agents.js`); the eval harness runs the dataset against the
new version before it ships and compares against the previous baseline.

## Harness

`evaluations/` contains a pytest-based harness:

- loads a dataset,
- runs the target agent with a pinned model + prompt version,
- scores structured outputs against labels,
- writes a metrics report (JSON) for comparison across runs.

Run locally and in CI (with recorded/canned LLM responses for the deterministic parts; live
model runs are a manual/nightly job to control cost).

## Confidence calibration

Track predicted confidence vs observed correctness per band (HIGH 90–100, MEDIUM 70–89,
LOW 50–69). Action gating thresholds are tuned from this data — thresholds are configuration,
not code constants.
