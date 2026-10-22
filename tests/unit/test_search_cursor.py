"""175d-T5：續頁 token 的編解碼（CD-175d-8）。

純函式、零 I/O；「p 已註冊」在 decode 呼叫當下讀 registry（測試用 monkeypatch.setitem 臨時註冊）。
壞 token 一律回 None，decode 不得拋例外。
"""

import base64
import json

import pytest

from core.search_providers import cursor

VALID_REFS = (("actor", "star/okq", 3), ("series", "ab_12", -1))


def _raw(obj) -> str:
    """把任意 JSON 物件編成 token 字串（繞過 encode，專門造壞 token）。"""
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode()


def _obj(**over):
    base = {"p": "dmm", "k": "entity", "r": [["actor", "r1", 0]]}
    base.update(over)
    return {k: v for k, v in base.items() if v is not cursor_missing}


cursor_missing = object()


# ---------------------------------------------------------------- 往返
@pytest.mark.parametrize(
    "token",
    [
        cursor.Token("javbus", "entity", VALID_REFS),
    ],
)
def test_round_trip(token):
    s = cursor.encode(token)
    assert isinstance(s, str) and len(s) <= cursor.MAX_LEN
    assert cursor.decode(s) == token


# ---------------------------------------------------------------- 壞 token
BAD_TOKENS = {
    "garbage": "!!!not-a-token!!!",
    "valid_b64_not_json": base64.urlsafe_b64encode(b"hello world").decode(),
    "valid_json_not_object": _raw([1, 2, 3]),
    "too_long": "A" * (cursor.MAX_LEN + 1),
    "p_unregistered": _raw(_obj(p="nosuchsite")),
    "k_unknown": _raw(_obj(k="weird")),
    "extra_key": _raw({**_obj(), "x": 1}),
    "kind_maker": _raw(_obj(r=[["maker", "r1", 0]])),
    "id_query_chars": _raw(_obj(r=[["actor", "a?b=c", 0]])),
    "id_49_chars": _raw(_obj(r=[["actor", "a" * 49, 0]])),
    "pos_minus_two": _raw(_obj(r=[["actor", "r1", -2]])),
    "pos_true": _raw(_obj(r=[["actor", "r1", True]])),
    "triple_two_items": _raw(_obj(r=[["actor", "r1"]])),
    "r_not_list": _raw(_obj(r="actor")),
    "entity_r_empty": _raw(_obj(r=[])),
    "entity_r_five": _raw(_obj(r=[["actor", f"r{k}", k] for k in range(5)])),
    "keyword_with_refs": _raw(_obj(k="keyword", r=[["actor", "r1", 0]])),
}


@pytest.mark.parametrize("name", sorted(BAD_TOKENS))
def test_decode_rejects_invalid_tokens(name):
    assert cursor.decode(BAD_TOKENS[name]) is None


def test_id_accepts_slash_and_dash_and_exactly_48_chars():
    for rid in ("uncensored/star/23f", "a-b_c", "a" * 48, "x"):
        got = cursor.decode(_raw(_obj(r=[["actor", rid, 0]])))
        assert got is not None and got.refs[0][1] == rid


