"""接力（relay）：依鏈順序逐家詢問 provider，第一家非空即回（CD-175a-3）。

- 鏈由 registry.providers_for 決定；每次搜尋新建 provider。
- 例外（Exception）或空結果 ⇒ log 後換下一家；全無 ⇒ []。175a 中「查無」與「連不上」對使用者都是 []。
- 實體梯子（actress）：外圈 provider、內圈 ACTOR→SERIES→DIRECTOR→LABEL；任一 ref 命中走
  list_entity＋run_window(guard=True)，該家不再問 KEYWORD；梯子全空才 run(KEYWORD)（175a 對 JavBus／DMM 是空操作）。
- seed 規則（CD-175a-4 I-S3）：第一個發動的 provider 一律拿得到 callback（同今天 first_dispatched）；之後的 provider
  只有「尚未真的送出 seed（slot == -1 被轉送）且 fallback_streaming」才拿得到，否則 None（避免後備改變最終順序）。
- relay 自己不送 status 事件、不補 `_source`、不排序。
頂層只准 stdlib、core.logger、core.scrapers.errors、core.search_providers.*（BE-PY-08）。
"""

from __future__ import annotations

from core.logger import get_logger
from core.scrapers.errors import SourceBlocked
from core.search_providers import registry
from core.search_providers.pipeline import run_window
from core.search_providers.types import EntityRef, Kind, Window

logger = get_logger(__name__)

_ENTITY_KINDS = (Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL)
_MODE_KIND = {"partial": Kind.PARTIAL, "prefix": Kind.CODE}


class _SeedGate:
    """包住呼叫端的 result_callback，只在 slot == -1 真的被轉送之後才記 seeded。"""

    def __init__(self, result_callback):
        self._cb = result_callback
        self.seeded = False
        self.callback = self._forward if result_callback is not None else None

    def _forward(self, slot, payload):
        self._cb(slot, payload)
        if slot == -1:
            self.seeded = True


def _streams_as_fallback(provider) -> bool:
    """後備（非第一個發動者）能否拿 callback：只有「串流順序＝最終順序」的 provider（fallback_streaming）。"""
    return bool(getattr(provider, "fallback_streaming", False))


def _resolve_refs(provider, kind: Kind, name: str) -> list[EntityRef]:
    """名字 → 實體參照清單（目前 0 或 1 個；175b 接多候選的上接點）。"""
    ref = provider.resolve(kind, name)
    return [ref] if ref is not None else []


def _entity_ladder(provider, name: str, w: Window, cb) -> list[dict] | None:
    """None＝梯子沒有任何 ref 命中（呼叫端改問 KEYWORD）；list＝命中了（可為空；該家不再問 KEYWORD）。"""
    for kind in _ENTITY_KINDS:
        if kind not in provider.capabilities:
            continue
        try:
            refs = _resolve_refs(provider, kind, name)
            for ref in refs:
                page = provider.list_entity(ref, w)
                res = run_window(
                    provider,
                    page.items,
                    ref,
                    result_callback=cb,
                    guard=True,
                )
                if res.cards:
                    return res.cards
        except Exception as err:
            logger.warning("entity ladder failed: %s/%s (%s)", provider.id, kind.value, type(err).__name__)
            return []
        if refs:
            return []
    return None


def _ask(provider, mode, q, w, status_callback, cb, discovery_only) -> list[dict]:
    if mode == "actress":
        if not discovery_only:
            cards = _entity_ladder(provider, q, w, cb)
            if cards is not None:
                return cards
        kind = Kind.KEYWORD
    else:
        kind = _MODE_KIND[mode]
    return provider.run(
        kind, q, w, status_callback=status_callback, result_callback=cb, discovery_only=discovery_only
    )


def search_by_intent(mode, q, w, *, status_callback=None, result_callback=None, discovery_only=False) -> list[dict]:
    """mode ∈ partial／prefix／actress；其他 ⇒ ValueError。"""
    if mode == "actress":
        kinds = {Kind.KEYWORD, *_ENTITY_KINDS}
    elif mode in _MODE_KIND:
        kinds = {_MODE_KIND[mode]}
    else:
        raise ValueError(f"unknown search mode: {mode!r}")
    providers = registry.providers_for(kinds, discovery_only=discovery_only)
    chain_ids = [p.id for p in providers]
    gate = _SeedGate(result_callback)
    for index, provider in enumerate(providers):
        provider_id = provider.id
        if not callable(getattr(provider, "run", None)):
            raise TypeError(f"provider {provider_id!r} has no run()")
        cb = None if gate.seeded or (index and not _streams_as_fallback(provider)) else gate.callback
        try:
            cards = _ask(provider, mode, q, w, status_callback, cb, discovery_only)
        except Exception as exc:
            logger.warning(
                "relay: %s failed (%s%s), trying next of %s",
                provider_id, type(exc).__name__, "/blocked" if isinstance(exc, SourceBlocked) else "", chain_ids,
            )
            continue
        if cards:
            return cards
    return []
