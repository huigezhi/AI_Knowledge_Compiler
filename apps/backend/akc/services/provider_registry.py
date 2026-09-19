"""Provider 注册表。

**adapter_version 必须与扩展侧保持一致**（``apps/extension/src/adapters/<id>.ts``），
两侧都记录下来，页面结构变化时可精确定位问题。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    display_name: str
    adapter_version: str
    origins: tuple[str, ...]
    capabilities: tuple[str, ...] = ("current", "history", "batch")


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="chatgpt",
        display_name="ChatGPT",
        adapter_version="0.1.0",
        origins=("chatgpt.com", "chat.openai.com"),
    ),
    ProviderSpec(
        id="claude",
        display_name="Claude",
        adapter_version="0.1.0",
        origins=("claude.ai",),
    ),
    ProviderSpec(
        id="deepseek",
        display_name="DeepSeek",
        adapter_version="0.1.0",
        origins=("chat.deepseek.com",),
    ),
    ProviderSpec(
        id="doubao",
        display_name="豆包",
        adapter_version="0.2.0",
        origins=("doubao.com",),
    ),
    ProviderSpec(
        id="zhipu",
        display_name="智谱清言",
        adapter_version="0.1.0",
        origins=("chatglm.cn", "bigmodel.cn"),
    ),
)

_BY_ID = {spec.id: spec for spec in PROVIDERS}


def get_spec(provider_id: str) -> ProviderSpec | None:
    return _BY_ID.get(provider_id)


def all_specs() -> tuple[ProviderSpec, ...]:
    return PROVIDERS


def match_origin(host: str) -> ProviderSpec | None:
    host = host.lower()
    for spec in PROVIDERS:
        for origin in spec.origins:
            if host == origin or host.endswith(f".{origin}"):
                return spec
    return None


def to_dict(spec: ProviderSpec, *, enabled: bool = True) -> dict[str, object]:
    return {
        "id": spec.id,
        "display_name": spec.display_name,
        "adapter_version": spec.adapter_version,
        "origins": list(spec.origins),
        "capabilities": list(spec.capabilities),
        "enabled": enabled,
    }
