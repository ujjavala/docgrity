"""Contradiction-agent evaluation harness.

Runs the contradiction prompt against the curated dataset in
``evaluations/datasets/contradictions.json`` and reports precision, recall, F1
and per-category accuracy. Use it to regression-test prompt changes:

    uv run python evaluations/run_contradiction_eval.py [--limit N] [--dataset PATH]

Requires LLM credentials in the environment (same settings as the app).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

from docgrity.agents.base import build_agent, run_agent
from docgrity.agents.schemas import ContradictionAssessment
from docgrity.core.enums import LLMCapability

DATASET = Path(__file__).parent / "datasets" / "contradictions.json"


def _render(page_a: dict, page_b: dict) -> str:
    return (
        f"## Page A (external_id=eval-a)\nTitle: {page_a['title']}\n"
        f"Last source update: None\n\n{page_a['text']}\n\n"
        f"## Page B (external_id=eval-b)\nTitle: {page_b['title']}\n"
        f"Last source update: None\n\n{page_b['text']}"
    )


async def evaluate(dataset_path: Path, limit: int | None) -> int:
    scenarios = json.loads(dataset_path.read_text())["scenarios"]
    if limit:
        scenarios = scenarios[:limit]

    agent, model_id, prompt_version = build_agent(
        "contradiction", LLMCapability.REASONING_HIGH, ContradictionAssessment
    )
    print(f"model={model_id} prompt_version={prompt_version} scenarios={len(scenarios)}\n")

    tp = fp = tn = fn = 0
    by_category: dict[str, list[bool]] = defaultdict(list)
    failures: list[str] = []

    for scenario in scenarios:
        payload = _render(scenario["page_a"], scenario["page_b"])
        try:
            output = await run_agent(agent, payload)
        except Exception as exc:  # noqa: BLE001 - eval keeps going per-scenario
            failures.append(f"{scenario['id']}: ERROR {exc}")
            continue
        predicted, expected = output.is_contradiction, scenario["expected"]
        correct = predicted == expected
        by_category[scenario["category"]].append(correct)
        if expected and predicted:
            tp += 1
        elif expected and not predicted:
            fn += 1
            failures.append(f"{scenario['id']}: MISSED (conf={output.confidence:.2f})")
        elif not expected and predicted:
            fp += 1
            failures.append(f"{scenario['id']}: FALSE POSITIVE (conf={output.confidence:.2f})")
        else:
            tn += 1
        print(f"  {'PASS' if correct else 'FAIL'}  {scenario['id']}")

    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    print(f"\n== Results ({total} scored) ==")
    print(f"precision={precision:.3f} recall={recall:.3f} f1={f1:.3f}")
    print(f"tp={tp} fp={fp} tn={tn} fn={fn}")
    print("\nPer-category accuracy:")
    for category, results in sorted(by_category.items()):
        print(f"  {category:<24} {sum(results)}/{len(results)}")
    if failures:
        print("\nFailures:")
        for line in failures:
            print(f"  {line}")
    return 0 if f1 >= 0.8 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    sys.exit(asyncio.run(evaluate(args.dataset, args.limit)))


if __name__ == "__main__":
    main()
