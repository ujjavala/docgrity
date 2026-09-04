"""Versioned prompt loading (prompts/<agent>/v<N>.md).

Findings store model + prompt_version + input_hash for reproducibility.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_VERSION_RE = re.compile(r"^v(\d+)\.md$")


@lru_cache
def load_prompt(agent: str, version: int | None = None) -> tuple[str, str]:
    """Return (prompt_text, version_label). Latest version if none specified."""
    agent_dir = PROMPTS_DIR / agent
    if version is None:
        versions = sorted(
            int(m.group(1)) for p in agent_dir.glob("v*.md") if (m := _VERSION_RE.match(p.name))
        )
        if not versions:
            raise FileNotFoundError(f"No prompts found in {agent_dir}")
        version = versions[-1]
    path = agent_dir / f"v{version}.md"
    return path.read_text(), f"v{version}"
