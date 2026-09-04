"""Action agent: drafts the Docgrity Confluence comment for a finding.

Drafting is LLM work (typed CommentDraft); posting goes through the Confluence
MCP server's policy-gated add_comment tool, never a direct API call from here.
"""

from __future__ import annotations

import json
import re

from docgrity.agents.base import AgentRun, build_agent, input_hash, run_agent
from docgrity.agents.schemas import CommentDraft
from docgrity.core.enums import LLMCapability


async def draft_comment(finding_context: dict) -> tuple[CommentDraft, AgentRun]:
    """Draft a comment for a finding.

    finding_context: {"finding_type", "summary", "evidence": [...],
    "potential_owners": [{"account_id", "confidence", "evidence"}],
    "pages": [{"title", "url"}], "recommended_action"}
    """
    payload = json.dumps(finding_context, indent=2, default=str)
    agent, model_id, prompt_version = build_agent(
        "action", LLMCapability.REASONING_FAST, CommentDraft
    )
    output = await run_agent(agent, payload)
    run = AgentRun(model=model_id, prompt_version=prompt_version, input_hash=input_hash(payload))
    return output, run


def comment_to_storage_html(draft: CommentDraft, pages: list[dict] | None = None) -> str:
    """Render a CommentDraft to Confluence storage format with real @-mentions."""
    lines = []
    for raw_line in _decode_literal_escapes(draft.body_markdown).splitlines():
        line = raw_line.strip()
        if line:
            lines.append(f"<p>{_escape(line)}</p>")
    seen_urls: set[str] = set()
    for page in pages or []:
        url, title = page.get("url"), page.get("title")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        lines.append(f'<p><a href="{_escape(url)}">{_escape(title or url)}</a></p>')
    for account_id in draft.mentions_account_ids:
        lines.append(
            "<p>Potential owner: "
            f'<ac:link><ri:user ri:account-id="{_escape(account_id)}" /></ac:link></p>'
        )
    return "".join(lines)


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _decode_literal_escapes(value: str) -> str:
    """Turn literal \\uXXXX sequences the model sometimes emits into real chars."""
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), value)
