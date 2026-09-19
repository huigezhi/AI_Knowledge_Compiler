"""Prompt 模板 —— 全部版本化。

规则：
* 每个模板都有 ``*_VERSION`` 常量，写入 compile_runs 与 knowledge frontmatter；
* **不得把模型名硬编码在这里**，模型由配置注入；
* 修改 Prompt = 升级版本号，保证历史结果可复现。
"""

from __future__ import annotations

import textwrap
from typing import Any

EXTRACTOR_PROMPT_VERSION = "extractor-v1"
MERGE_PLANNER_PROMPT_VERSION = "merge-planner-v1"

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are a Personal Knowledge Compiler.

    Your job is to compile durable knowledge from AI conversations.
    Do NOT merely summarize.
    Preserve source traceability.
    Separate facts, opinions, assumptions, and hypotheses.
    Never invent unsupported facts.
    Prefer merge/update over creating duplicates.
    When uncertain, output uncertainty explicitly.
    Return only the requested structured output.

    Hard rules:
    - Never upgrade an `opinion` or `hypothesis` into a `fact`.
    - Any statement without source support must be marked as `hypothesis`,
      `question` or `opinion`, and `needs_verification` must be true.
    - Every item MUST cite at least one `source_message_ids` entry that appears
      in the conversation.
    - Respond with a single JSON object that validates against the provided schema,
      with no prose before or after it.
    """
).strip()

TAXONOMY = "fact, concept, method, heuristic, decision, question, hypothesis, opinion"

_EXTRACTOR_TEMPLATE = textwrap.dedent(
    """
    <conversation>
    <metadata>
    provider: {provider}
    title: {title}
    conversation_id: {conversation_id}
    </metadata>
    {messages}
    </conversation>

    <related_knowledge>
    {related_knowledge}
    </related_knowledge>

    <taxonomy>{taxonomy}</taxonomy>

    Extract durable knowledge items from the conversation above.

    Output a single JSON object with this shape:
    {{
      "items": [
        {{
          "title": "string",
          "type": "{taxonomy_inline}",
          "summary": "string",
          "body_markdown": "string",
          "source_message_ids": ["m1"],
          "confidence": 0.0,
          "needs_verification": true,
          "entities": ["..."],
          "candidate_existing_knowledge_ids": [],
          "merge_action": "create|update|merge|ignore|review"
        }}
      ],
      "entities": [{{"name": "string", "type": "string", "canonical_name": "string"}}],
      "relations": [{{"source": "string", "relation": "string", "target": "string", "confidence": 0.0}}],
      "contradictions": [{{"knowledge_id": "string", "field": "string", "existing": "string", "new": "string", "severity": "low|medium|high", "reason": "string"}}],
      "notes": ["string"]
    }}
    """
).strip()

_MERGE_TEMPLATE = textwrap.dedent(
    """
    You are resolving whether a new knowledge candidate should be merged into an
    existing verified knowledge entry.

    <existing_knowledge>
    title: {existing_title}
    type: {existing_type}
    status: {existing_status}
    body:
    {existing_body}
    </existing_knowledge>

    <candidate>
    title: {candidate_title}
    type: {candidate_type}
    summary: {candidate_summary}
    body:
    {candidate_body}
    </candidate>

    Rules:
    - Same meaning and same evidence -> ignore
    - Same meaning but different evidence -> merge
    - Existing knowledge is more complete and the candidate adds detail -> update
    - The candidate conflicts with verified content -> review (never overwrite silently)
    - Candidate is only an opinion or a temporary question -> ignore

    Return a single JSON object:
    {{"action": "create|update|merge|ignore|review", "reason": "string",
      "proposed_markdown_patch": "string",
      "conflicts": [{{"field": "string", "existing": "string", "new": "string", "severity": "low|medium|high"}}]}}
    """
).strip()


def render_message_xml(messages: list[dict[str, Any]], *, max_chars: int = 50_000) -> str:
    """把消息渲染成带 id / role 的 XML，供 Prompt 使用。

    ``max_chars`` 由配置的 ``claude_max_context_tokens`` 换算后传入，超出时截断并标注。
    """
    from akc.services.hasher import message_text  # 局部导入避免循环依赖

    parts: list[str] = []
    used = 0
    for msg in messages:
        body = message_text(msg.get("content") or [])
        chunk = f'<message id="{msg.get("id")}" role="{msg.get("role")}">\n{body}\n</message>'
        if used + len(chunk) > max_chars:
            parts.append("<!-- truncated: context budget exhausted -->")
            break
        parts.append(chunk)
        used += len(chunk)
    return "\n".join(parts)


def render_related_knowledge(items: list[dict[str, Any]]) -> str:
    if not items:
        return "<!-- no related knowledge retrieved -->"
    lines = []
    for item in items:
        lines.append(
            f'<knowledge id="{item.get("id")}" status="{item.get("status")}" '
            f'type="{item.get("knowledge_type")}">\n'
            f'{item.get("title","")}: {item.get("summary","")}\n</knowledge>'
        )
    return "\n".join(lines)


def build_extractor_prompt(
    conversation: dict[str, Any],
    related_knowledge: list[dict[str, Any]],
    *,
    max_chars: int = 50_000,
) -> str:
    return _EXTRACTOR_TEMPLATE.format(
        provider=conversation.get("provider", ""),
        title=conversation.get("title", ""),
        conversation_id=conversation.get("provider_conversation_id", ""),
        messages=render_message_xml(conversation.get("messages", []), max_chars=max_chars),
        related_knowledge=render_related_knowledge(related_knowledge),
        taxonomy=TAXONOMY,
        taxonomy_inline=TAXONOMY.replace(", ", "|"),
    )


def build_merge_planner_prompt(existing: dict[str, Any], candidate: dict[str, Any]) -> str:
    return _MERGE_TEMPLATE.format(
        existing_title=existing.get("title", ""),
        existing_type=existing.get("knowledge_type", ""),
        existing_status=existing.get("status", ""),
        existing_body=existing.get("markdown") or existing.get("summary", ""),
        candidate_title=candidate.get("title", ""),
        candidate_type=candidate.get("type", ""),
        candidate_summary=candidate.get("summary", ""),
        candidate_body=candidate.get("body_markdown") or candidate.get("summary", ""),
    )
