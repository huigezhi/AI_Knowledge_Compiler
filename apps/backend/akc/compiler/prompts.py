"""Prompt 模板 —— 全部版本化。

规则：
* 每个模板都有 ``*_VERSION`` 常量，写入 compile_runs 与 knowledge frontmatter；
* **不得把模型名硬编码在这里**，模型由配置注入；
* 修改 Prompt = 升级版本号，保证历史结果可复现。
"""

from __future__ import annotations

import textwrap
from typing import Any

EXTRACTOR_PROMPT_VERSION = "extractor-v2"
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

# 主题域（需求：知识库要按 编程 / 金融 / 旅游 / 工作 等主题分类落盘）。
# extractor 每条 item 必须从中选一个；同时是 merge 目录划分与 schema 枚举的唯一来源。
KNOWLEDGE_DOMAINS = [
    "编程技术",
    "金融投资",
    "休闲旅游",
    "工作职场",
    "学习成长",
    "生活健康",
    "其他",
]

_EXTRACTION_INSTRUCTIONS = textwrap.dedent(
    """
    Consolidate the conversation above into durable knowledge.

    核心原则：**汇聚，而不是罗列**。
    - 通常整场对话只输出 1 条知识点：把同类、同主题的要点合并成一条结构化笔记
      （用小节组织正文），绝不把每个细节拆成独立 item。
    - 仅当对话确实横跨多个不同 <domains> 主题时才拆分，且最多 {max_items} 条。
    - 与 <related_knowledge> 中已有知识相同的要点，直接并入对应条目
      （merge_action=update/merge），不要重复创建。
    """
).strip()

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

    <domains>{domains}</domains>

    <output_budget>
    - 最多 {max_items} 条 items；宁可把相近内容合并成一条，也不要逐条罗列。
    - 每条 summary 不超过 60 字；body_markdown 不超过 {max_body_chars} 字。
    - entities 最多 8 个，relations 最多 5 条，contradictions 最多 3 条，notes 最多 3 条。
    - 总输出必须能一次性写完，绝不能因为长度被截断：宁少勿多。
    </output_budget>

    {instructions}

    Output a single JSON object with this shape:
    {{
      "items": [
        {{
          "title": "string",
          "type": "{taxonomy_inline}",
          "domain": "{domains_inline}",
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
    max_items: int = 3,
    max_body_chars: int = 600,
) -> str:
    """``max_items`` / ``max_body_chars`` 是**输出预算**。

    DeepSeek / Claude 的单次输出上限是硬性的（DeepSeek 为 8192 token），
    而模型的默认倾向是"把每个细节都拆成一条知识"——实测一轮就写满 8192 token
    被截断，截断的 JSON 必然解析失败，任务永远失败。
    汇聚式抽取（见 ``_EXTRACTION_INSTRUCTIONS``）之后 1-3 条是常态，预算更宽裕。
    """
    return _EXTRACTOR_TEMPLATE.format(
        provider=conversation.get("provider", ""),
        title=conversation.get("title", ""),
        conversation_id=conversation.get("provider_conversation_id", ""),
        messages=render_message_xml(conversation.get("messages", []), max_chars=max_chars),
        related_knowledge=render_related_knowledge(related_knowledge),
        taxonomy=TAXONOMY,
        taxonomy_inline=TAXONOMY.replace(", ", "|"),
        domains="、".join(KNOWLEDGE_DOMAINS),
        domains_inline="|".join(KNOWLEDGE_DOMAINS),
        instructions=_EXTRACTION_INSTRUCTIONS.format(max_items=max_items),
        max_items=max_items,
        max_body_chars=max_body_chars,
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
