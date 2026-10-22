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
        cursor.Token("dmm", "entity", (("label", "L-1", 0),)),
        cursor.Token("javdb", "keyword", ()),
        cursor.Token("javbus", "maker", ()),
    ],
)
def test_round_trip(token):
    s = cursor.encode(token)
    assert isinstance(s, str) and len(s) <= cursor.MAX_LEN
    assert cursor.decode(s) == token


def test_token_is_urlsafe_text_without_provider_internals_leaking_structure():
    s = cursor.encode(cursor.Token("javbus", "entity", VALID_REFS))
    assert all(ch.isalnum() or ch in "-_=" for ch in s)  # 可原樣放進 query string


def test_four_refs_is_the_maximum_and_round_trips():
    refs = tuple(("actor", f"r{k}", k) for k in range(4))
    t = cursor.Token("javbus", "entity", refs)
    assert cursor.decode(cursor.encode(t)) == t
    five = _raw({"p": "javbus", "k": "entity", "r": [list(r) for r in refs] + [["actor", "r4", 4]]})
    assert cursor.decode(five) is None


# ---------------------------------------------------------------- 壞 token
BAD_TOKENS = {
    "none": None,
    "empty": "",
    "not_str": 12345,
    "garbage": "!!!not-a-token!!!",
    "contains_space": "eyJw IjoiZG1tIn0=",
    "contains_bang": "eyJwIjoiZG1tIn0!",
    "non_ascii": "eyJwIjoi日本語In0=",
    "valid_b64_not_json": base64.urlsafe_b64encode(b"hello world").decode(),
    "valid_json_not_object": _raw([1, 2, 3]),
    "json_string": _raw("dmm"),
    "json_null": _raw(None),
    "invalid_utf8": base64.urlsafe_b64encode(b"\xff\xfe\xfa").decode(),
    "deeply_nested": base64.urlsafe_b64encode(b"[" * 300).decode(),
    "too_long": "A" * (cursor.MAX_LEN + 1),
    "p_unregistered": _raw(_obj(p="nosuchsite")),
    "p_missing": _raw(_obj(p=cursor_missing)),
    "p_not_str": _raw(_obj(p=7)),
    "k_unknown": _raw(_obj(k="weird")),
    "k_missing": _raw(_obj(k=cursor_missing)),
    "k_not_str": _raw(_obj(k=["entity"])),
    "extra_key": _raw({**_obj(), "x": 1}),
    "kind_maker": _raw(_obj(r=[["maker", "r1", 0]])),
    "kind_code": _raw(_obj(r=[["code", "r1", 0]])),
    "kind_keyword": _raw(_obj(r=[["keyword", "r1", 0]])),
    "kind_unknown": _raw(_obj(r=[["movie", "r1", 0]])),
    "kind_not_str": _raw(_obj(r=[[1, "r1", 0]])),
    "id_empty": _raw(_obj(r=[["actor", "", 0]])),
    "id_space": _raw(_obj(r=[["actor", "a b", 0]])),
    "id_newline": _raw(_obj(r=[["actor", "ab\n", 0]])),
    "id_query_chars": _raw(_obj(r=[["actor", "a?b=c", 0]])),
    "id_dotdot": _raw(_obj(r=[["actor", "a..b", 0]])),
    "id_non_ascii": _raw(_obj(r=[["actor", "女優", 0]])),
    "id_49_chars": _raw(_obj(r=[["actor", "a" * 49, 0]])),
    "id_not_str": _raw(_obj(r=[["actor", 5, 0]])),
    "pos_minus_two": _raw(_obj(r=[["actor", "r1", -2]])),
    "pos_true": _raw(_obj(r=[["actor", "r1", True]])),
    "pos_false": _raw(_obj(r=[["actor", "r1", False]])),
    "pos_float": _raw(_obj(r=[["actor", "r1", 1.0]])),
    "pos_str": _raw(_obj(r=[["actor", "r1", "3"]])),
    "pos_null": _raw(_obj(r=[["actor", "r1", None]])),
    "triple_two_items": _raw(_obj(r=[["actor", "r1"]])),
    "triple_four_items": _raw(_obj(r=[["actor", "r1", 0, 9]])),
    "triple_is_dict": _raw(_obj(r=[{"kind": "actor", "id": "r1", "pos": 0}])),
    "triple_is_string": _raw(_obj(r=["actor"])),
    "r_not_list": _raw(_obj(r="actor")),
    "r_is_dict": _raw(_obj(r={"actor": 1})),
    "entity_r_missing": _raw(_obj(r=cursor_missing)),
    "entity_r_empty": _raw(_obj(r=[])),
    "entity_r_five": _raw(_obj(r=[["actor", f"r{k}", k] for k in range(5)])),
    "entity_r_null": _raw(_obj(r=None)),
    "keyword_r_null": _raw(_obj(k="keyword", r=None)),
    "maker_r_null": _raw(_obj(k="maker", r=None)),
    "keyword_with_refs": _raw(_obj(k="keyword", r=[["actor", "r1", 0]])),
    "maker_with_refs": _raw(_obj(k="maker", r=[["actor", "r1", 0]])),
}


@pytest.mark.parametrize("name", sorted(BAD_TOKENS))
def test_decode_rejects_invalid_tokens(name):
    assert cursor.decode(BAD_TOKENS[name]) is None


def test_keyword_and_maker_accept_omitted_or_empty_r():
    for k in ("keyword", "maker"):
        for r in (cursor_missing, []):
            got = cursor.decode(_raw(_obj(k=k, r=r)))
            assert got == cursor.Token("dmm", k, ())


def test_id_accepts_slash_and_dash_and_exactly_48_chars():
    for rid in ("uncensored/star/23f", "a-b_c", "a" * 48, "x"):
        got = cursor.decode(_raw(_obj(r=[["actor", rid, 0]])))
        assert got is not None and got.refs[0][1] == rid


