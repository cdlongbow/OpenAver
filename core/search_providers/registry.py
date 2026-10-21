"""Provider 註冊表（顯式表，非掃描）。

175a-T3 起為空；T4／T5 註冊 javbus／dmm。值是無參數工廠，惰性建構（import 時不 new session、
也不 import 任何 provider 模組）。providers_for（順序∩註冊∩開關∩能力）屬 T7，不在此檔。
"""

from __future__ import annotations

from collections.abc import Callable

from core.search_providers.types import Provider

_REGISTRY: dict[str, Callable[[], Provider]] = {}
_INSTANCES: dict[str, Provider] = {}


def registered_ids() -> frozenset[str]:
    return frozenset(_REGISTRY)


def get_provider(provider_id: str) -> Provider:
    """依 id 取 provider；第一次取用才建構。未註冊 ⇒ KeyError。"""
    if provider_id not in _INSTANCES:
        _INSTANCES[provider_id] = _REGISTRY[provider_id]()
    return _INSTANCES[provider_id]
