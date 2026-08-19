"""檔名後綴 → 屬性 tag 的單一資料來源，加上合併／去重純函式。

表是 5 個 id，`-UC` 不是獨立列：id 為 subtitle / cracked / leaked / 4k / vr，
`-UC` / `-CU` 是 subtitle 與 cracked 共用的 token。
「無碼」（片商本身無碼）不在本表。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

_BARE_LEFT = r"(?<![0-9A-Za-z一-鿿])"
_BARE_RIGHT = r"(?![0-9A-Za-z一-鿿])"
_PREFIXED_RIGHT = r"(?=[-_.\s]|$)"


@dataclass(frozen=True)
class AttributeRule:
    id: str
    canonical_tag: str
    short_name: str
    display_order: int
    i18n_key: str
    source: str
    tokens: tuple[str, ...] = ()


ATTRIBUTE_TABLE: tuple[AttributeRule, ...] = (
    AttributeRule(
        id="subtitle",
        canonical_tag="中文字幕",
        short_name="中字",
        display_order=1,
        i18n_key="settings.gallery.cover_badge.subtitle",
        source="filename_token",
        tokens=("-C", "_C", "-ch", "-UC", "-CU"),
    ),
    AttributeRule(
        id="cracked",
        canonical_tag="無碼破解",
        short_name="破解",
        display_order=2,
        i18n_key="settings.gallery.cover_badge.cracked",
        source="filename_token",
        tokens=("-U", "_U", "umr", "破解", "克破", "-UC", "-CU"),
    ),
    AttributeRule(
        id="leaked",
        canonical_tag="無碼流出",
        short_name="流出",
        display_order=2,
        i18n_key="settings.gallery.cover_badge.leaked",
        source="filename_token",
        tokens=("-leak", "-uncensored", "leaked", "流出"),
    ),
    AttributeRule(
        id="4k",
        canonical_tag="4K",
        short_name="4K",
        display_order=4,
        i18n_key="settings.gallery.cover_badge.4k",
        source="filename_token",
        tokens=("-4K", "-uhd", "-8k"),
    ),
    AttributeRule(
        id="vr",
        canonical_tag="VR",
        short_name="VR",
        display_order=3,
        i18n_key="settings.gallery.cover_badge.vr",
        source="filename_token",
        tokens=("-VR",),
    ),
)


def _compile_token(token: str) -> re.Pattern[str]:
    escaped = re.escape(token.lower())
    if token[:1] in "-_":
        return re.compile(escaped + _PREFIXED_RIGHT)
    return re.compile(_BARE_LEFT + escaped + _BARE_RIGHT)


_RULE_PATTERNS: tuple[tuple[AttributeRule, tuple[re.Pattern[str], ...]], ...] = tuple(
    (rule, tuple(_compile_token(token) for token in rule.tokens))
    for rule in ATTRIBUTE_TABLE
)

_TAG_4K = next(rule.canonical_tag for rule in ATTRIBUTE_TABLE if rule.id == "4k")

_MANIFEST_KEYS = ("id", "canonical_tag", "short_name", "display_order", "i18n_key")


def _dedup_keep_first(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def effective_tags(filename: str, existing_tags: Iterable[str] | None) -> list[str]:
    if existing_tags is None:
        base: list[str] = []
    else:
        base = [t for t in existing_tags if t]

    lowered_name = filename.lower()
    candidates: list[str] = []
    for rule, patterns in _RULE_PATTERNS:
        if any(pattern.search(lowered_name) for pattern in patterns):
            candidates.append(rule.canonical_tag)

    for item in base:
        lowered = item.strip().lower()
        if "4k" == lowered or "uhd" == lowered or "8k" == lowered:
            candidates.append(_TAG_4K)
            break

    return _dedup_keep_first(base + candidates)


def manifest_payload() -> list[dict]:
    return [{key: getattr(rule, key) for key in _MANIFEST_KEYS} for rule in ATTRIBUTE_TABLE]
