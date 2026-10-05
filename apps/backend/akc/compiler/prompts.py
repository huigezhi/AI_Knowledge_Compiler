"""Prompt 模板 —— 全部版本化。

规则：
* 每个模板都有 ``*_VERSION`` 常量，写入 compile_runs 与 knowledge frontmatter；
* **不得把模型名硬编码在这里**，模型由配置注入；
* 修改 Prompt = 升级版本号，保证历史结果可复现。
"""

from __future__ import annotations

import textwrap
from typing import Any

EXTRACTOR_PROMPT_VERSION = "extractor-v3"
MERGE_PLANNER_PROMPT_VERSION = "merge-planner-v1"

# 为什么升到 v3：v2 把「一个会话只出一条」写成软规则（"通常 1 条，最多 N 条"），
# 而模型的天然倾向是"把每个细节拆成一条知识"——软规则挡不住，结果一个对话被拆成
# 好几条知识点。v3 改成硬约束，并在代码里再加一道兜底（见 extractor._enforce_single_item），
# 不再依赖模型自觉。

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

# 「属于同一知识点」的判定依据。
#
# 这份文本同时是给模型看的规则，也是代码里 merge_planner 的判定口径，
# 两处必须保持一致 —— 所以常量放在这里，由 Prompt 与单测共同引用，避免漂移。
SAME_KNOWLEDGE_CRITERIA = textwrap.dedent(
    """
    1. 同一主题域（domain）：两条内容的 domain 必须相同。
       不同域一律不算同一知识点（例如「旅游出行」与「编程技术」不合并）。
    2. 核心命题同一：标题与摘要讲的是同一件事，而不是"碰巧提到同一个词"。
       代码口径 = 标题/摘要的字符 bigram Jaccard 相似度：
       >= 0.72 判为同一；0.45 ~ 0.72 判为相关但未定（作为补充或转人工）；< 0.45 判为不同。
    3. 核心实体有交集：两条内容涉及的主要对象/概念有重叠。
       完全没有共同实体、仅标题勉强相似的，不算同一知识点。
    4. 证据可并存：来自不同消息、不同会话的同类内容，视为同一知识点的**补充证据**，
       应合并进已有条目（merge_action=merge/update），而不是新建一条。
    5. 例外（不合并）：
       - type 为 opinion / question 的内容不进入合并链路；
       - 与已 verified 内容冲突的，只能 review，绝不静默覆盖。
    """
).strip()

_EXTRACTION_INSTRUCTIONS = textwrap.dedent(
    """
    Consolidate the conversation above into durable knowledge.

    ## 硬约束：一个对话 = 一条知识点
    - **整场对话必须且只能输出 1 条 item**，`items` 数组的长度恒为 1。
      这不是"建议"，违反即视为输出不合格。
    - 对话里出现的多个要点，一律用正文的**小节（##）**组织进这一条，
      绝不拆成多条 item，哪怕它们看起来像不同的小话题。
    - 如果对话确实横跨多个主题域：选**对话最终落脚的那个主题**作为这一条的 domain，
      其余主题作为正文里的次要小节带过。
    - 标题要能概括整场对话（而不是其中某一个小点）。

    ## 与已有知识的关系
    - 先看 <related_knowledge>：已有条目里只要符合下面的「同一知识点判定依据」，
      就必须并入它（merge_action=merge 或 update），并把它的 id 填进
      `candidate_existing_knowledge_ids`，**不要新建**。
    - 判定依据见 <same_knowledge_criteria>。
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

    <same_knowledge_criteria>
    {criteria}
    </same_knowledge_criteria>

    <output_budget>
    - **items 数组必须且只能有 1 条**（一个对话 = 一条知识点）。输出 0 条或 2 条以上均为不合格。
    - 该条的 summary 不超过 60 字；body_markdown 不超过 {max_body_chars} 字。
      内容多就用小节压缩，不要靠增加条数来容纳。
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
    max_body_chars: int = 900,
) -> str:
    """``max_body_chars`` 是**输出预算**；条数不再是预算项。

    一个对话恒等于一条知识点（见 ``_EXTRACTION_INSTRUCTIONS`` 的硬约束），
    所以这里没有 ``max_items`` 参数——留着它等于给模型"可以拆多条"的暗示。

    ``max_body_chars`` 仍需收紧：DeepSeek 的单次输出上限是硬性的 8192 token，
    被截断的 JSON 必然解析失败。条数固定为 1 之后，能调的就只剩正文长度。
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
        criteria=SAME_KNOWLEDGE_CRITERIA,
        instructions=_EXTRACTION_INSTRUCTIONS,
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
