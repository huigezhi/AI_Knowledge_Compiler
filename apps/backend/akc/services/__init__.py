"""Business logic layer.

本包**刻意不在 ``__init__`` 中导入子模块**：仓储层会被部分服务依赖，
提前导入会造成 ``repositories -> services -> repositories`` 的循环导入。
请始终按模块路径导入，例如 ``from akc.services import obsidian``。
"""
