"""test_dmm_resolve.py — DMM 名稱→實體 resolve（TASK-175c-T7，plan CD-175c-6 (B)／CD-175c-9／CD-175c-12 I-D1）。

傳輸邊界只有兩個方法名：`DMMScraper.list_contents`（Probe stage 1）與 `DMMScraper.fetch_facts`（stage 2）；
替身依 word／id 回不同資料並記錄呼叫參數（BE-TEST-23），計數看 `call_count` 級的記錄（BE-TEST-46）。
合成資料全為檔內字面（形狀依 plan 活站 #2–#30 的紀錄），不收站方 JSON；零活站請求。
Probe 快取清除靠 tests/conftest.py 的 autouse fixture（CD-175c-11），本檔不另設。

G7 結果（2026-10-22，2 次直連）：`Actress` 只有 `nameRuby`（假名讀音）、`ContentSearchActress`（列表）一個
拉丁／讀音欄位都沒有 ⇒ 分支 (b)：不做轉寫，羅馬字輸入而 rows 無對得上的值 ⇒ None（見 test_actor_latin_input_*）。
"""
import concurrent.futures as cf
from unittest.mock import patch

import pytest
import requests

import core.search_providers.dmm as dmm_mod
from core.scrapers.dmm import DMMScraper, Facts, ListResult, Named
from core.scrapers.errors import SourceBlocked, SourceUnreachable
from core.scrapers.models import Video
from core.search_providers import relay
from core.search_providers.dmm import DMMProvider
from core.search_providers.types import EntityRef, Kind, Window


# ---------------------------------------------------------------- 合成資料
def _act(aid, name):
    return {"id": str(aid), "name": name}


def _maker(mid, name):
    return {"id": str(mid), "name": name}


def _row(cid, actresses=(), maker=None):
    """actresses＝None 代表站方給 null；maker＝None 同。"""
    return {
        "id": cid,
        "title": "t",
        "actresses": None if actresses is None else list(actresses),
        "maker": maker,
    }


MIKAMI = _act(1030262, "三上悠亜")
AKANE = _act(1093154, "あかね麗（二階堂麗）")
S1 = _maker(3152, "エスワン ナンバーワンスタイル")
MOODYZ = _maker(1509, "ムーディーズ")

WINDOW = Window(0, 20)


def _mikami_rows():
    """三上悠亜出現 40 列、其中 36 列各帶一位 id 互異的雜牌共演者；另有 actresses 為 null、缺 name／缺 id 的列。"""
    rows = []
    for i in range(40):
        costars = [_act(2000 + i, f"共演者{i:02d}")] if i < 36 else []
        rows.append(_row(f"mikami{i:03d}", [MIKAMI, *costars], S1))
    rows.append(_row("nulls", None, None))
    rows.append(_row("malformed", [{"id": "9"}, {"id": "10", "name": ""}, {"name": "無id的三上悠亜"}], None))
    return rows


def _world_rows():
    """通用世界：三上悠亜、あかね麗（二階堂麗）、S1 片商、三筆 content id（facts 用）。"""
    return [
        _row("w1", [MIKAMI, AKANE], S1),
        _row("w2", [MIKAMI], S1),
        _row("w3", [AKANE], MOODYZ),
    ]


def _world_facts():
    named_dir = [Named("999", "OTHER DIRECTOR"), Named("101211", "TAKE-D")]
    return {
        "w1": Facts("W-001", Named("233224", "PLATINUM SOAP"), Named("4325", "MOODYZ DIVA"), named_dir),
        "w2": Facts("W-002", Named("233224", "PLATINUM SOAP"), None, []),
        "w3": Facts("W-003", None, Named("4325", "MOODYZ DIVA"), []),
    }


# ---------------------------------------------------------------- 傳輸替身（只 patch 兩個既有方法名）
class Transport:
    def __init__(self):
        self.rows = {}  # query_word -> rows；沒登記的 word＝站上 0 筆
        self.facts = {}  # content_id -> Facts；沒登記的 id＝alias 缺漏
        self.list_calls = []  # (query_word, limit, offset, filter)
        self.facts_calls = []  # tuple(content_ids)
        self.fail_list = None
        self.fail_facts = None

    @property
    def words(self):
        return [c[0] for c in self.list_calls]

    @property
    def total(self):
        return len(self.list_calls) + len(self.facts_calls)

    def world(self, *words):
        """把通用世界登記到這些 word（每個 word 一份獨立的 rows 清單）。"""
        for w in words:
            self.rows[w] = _world_rows()
        self.facts.update(_world_facts())


@pytest.fixture
def transport():
    t = Transport()

    def _list(self, query_word=None, filter=None, *, limit, offset):
        t.list_calls.append((query_word, limit, offset, filter))
        if t.fail_list is not None:
            raise t.fail_list
        return ListResult(list(t.rows.get(query_word, [])), None, False)

    def _facts(self, content_ids):
        t.facts_calls.append(tuple(content_ids))
        if t.fail_facts is not None:
            raise t.fail_facts
        return {cid: t.facts[cid] for cid in content_ids if cid in t.facts}

    with patch.object(DMMScraper, "list_contents", _list), patch.object(DMMScraper, "fetch_facts", _facts):
        yield t


@pytest.fixture
def provider():
    return DMMProvider(DMMScraper())


@pytest.fixture
def spellings(monkeypatch):
    """patch 使用端 binding（core.search_providers.dmm.maker_names）餵拼法集合，不依賴真對照表。"""
    table = {}
    monkeypatch.setattr(dmm_mod, "maker_names", lambda q: list(table[q]))
    return table


# ================================================================ 1. ACTOR
def test_actor_exact_name_picks_the_actress_not_her_costars(transport, provider):
    transport.rows["三上悠亜"] = _mikami_rows()
    ref = provider.resolve(Kind.ACTOR, "三上悠亜")
    assert ref == EntityRef(Kind.ACTOR, "1030262", "三上悠亜")
    assert transport.list_calls == [("三上悠亜", 40, 0, None)]  # name 原樣送、limit 40、第一頁
    assert transport.facts_calls == []  # ACTOR 只要 stage 1


def test_actor_substring_candidate_rejected(transport, provider):
    # 使用者在 DMM 排第一打「三上」想搜標題含「三上」的片 → DMM 結果裡的 三上悠亜 若被當同名女優，
    # 只看到一位的作品、關鍵字結果被吃掉，畫面看起來完全正常
    transport.rows["三上"] = _mikami_rows()  # rows 內確有 fold 後「包含」輸入的名字
    assert provider.resolve(Kind.ACTOR, "三上") is None
    assert len(transport.list_calls) == 1  # 真的問過、不是沒問


def test_actor_whitespace_variants_resolve_to_same_ref_and_share_one_cell(transport, provider):
    transport.rows["三上 悠亜"] = _mikami_rows()
    transport.rows["三上悠亜"] = _mikami_rows()
    transport.rows["三上　悠亜"] = _mikami_rows()
    a = provider.resolve(Kind.ACTOR, "三上 悠亜")
    b = provider.resolve(Kind.ACTOR, "三上悠亜")
    c = provider.resolve(Kind.ACTOR, "三上　悠亜")
    assert a == b == c == EntityRef(Kind.ACTOR, "1030262", "三上悠亜")
    assert transport.words == ["三上 悠亜"]  # 同一格（D1）；送出的是第一次的原字


def test_actor_matches_old_name_in_parentheses(transport, provider):
    # 使用者在 DMM 排第一打舊藝名「二階堂麗」→ DMM 已併成 あかね麗（二階堂麗）；括號舊名若不比對就認不出她，
    # 改走標題關鍵字，只看到標題含舊名的片，錯過她現名的作品，畫面看起來正常
    only_paren_form = [_row("a1", [AKANE]), _row("a2", [AKANE, _act(7, "共演者")])]  # 不另放純「二階堂麗」
    transport.rows["二階堂麗"] = list(only_paren_form)
    transport.rows["あかね麗"] = list(only_paren_form)
    old = provider.resolve(Kind.ACTOR, "二階堂麗")
    new = provider.resolve(Kind.ACTOR, "あかね麗")
    assert old == new == EntityRef(Kind.ACTOR, "1093154", "あかね麗")  # 同一個 id、label 是主名


def test_actor_latin_input_without_matching_value_is_none(transport, provider):
    # G7 分支 (b)：沒有拉丁欄位可比；不取「出現最多者」硬湊
    transport.rows["Yua Mikami"] = _mikami_rows()
    transport.rows["mikamiyua"] = _mikami_rows()
    assert provider.resolve(Kind.ACTOR, "Yua Mikami") is None
    assert provider.resolve(Kind.ACTOR, "mikamiyua") is None
    assert len(transport.list_calls) == 2


def test_actor_same_name_two_ids_takes_the_more_frequent(transport, provider):
    rows = [_row("r1", [_act(1, "同名")]), _row("r2", [_act(2, "同名")]),
            _row("r3", [_act(2, "同名")]), _row("r4", [_act(2, "同名")])]
    transport.rows["同名"] = rows
    assert provider.resolve(Kind.ACTOR, "同名") == EntityRef(Kind.ACTOR, "2", "同名")  # 後出現但次數多


def test_actor_same_name_tie_takes_first_seen(transport, provider):
    transport.rows["同名"] = [_row("r1", [_act(5, "同名")]), _row("r2", [_act(3, "同名")]),
                             _row("r3", [_act(3, "同名")]), _row("r4", [_act(5, "同名")])]
    assert provider.resolve(Kind.ACTOR, "同名") == EntityRef(Kind.ACTOR, "5", "同名")  # 2:2 平手→先出現


def test_actor_tolerates_null_and_malformed_rows(transport, provider):
    # D3：actresses／maker 為 null、項目缺 id 或 name 者略過，不整批丟
    transport.rows["三上悠亜"] = [
        _row("n1", None, None),
        _row("n2", [{"id": "9"}, {"name": "三上悠亜"}, {"id": "", "name": "三上悠亜"}]),  # 缺 name／缺 id／空 id
        _row("n3", [MIKAMI]),
    ]
    assert provider.resolve(Kind.ACTOR, "三上悠亜") == EntityRef(Kind.ACTOR, "1030262", "三上悠亜")


def test_actor_not_found_when_rows_empty(transport, provider):
    assert provider.resolve(Kind.ACTOR, "查無此人") is None
    assert transport.list_calls == [("查無此人", 40, 0, None)]


# ================================================================ 2. MAKER（經公開 resolve）
def test_maker_first_spelling_hits_with_one_request(transport, provider, spellings):
    # 使用者在 DMM 排第一或只開 DMM 打片商簡稱 S1 → 命中 エスワン ナンバーワンスタイル 而片商清單有東西
    spellings["S1"] = ["S1", "エスワン ナンバーワンスタイル"]
    transport.rows["S1"] = [_row("m1", [], S1)] * 3 + [_row("m2", [], MOODYZ)]
    assert provider.resolve(Kind.MAKER, "S1") == EntityRef(Kind.MAKER, "3152", "エスワン ナンバーワンスタイル")
    assert transport.words == ["S1"]
    assert transport.facts_calls == []


def test_maker_first_spelling_empty_second_hits(transport, provider, spellings):
    # 第一個拼法查無（0 筆）時若不接著試別名拼法就直接判查無，打 Attackers 這類名字的片商清單會是空的
    spellings["Attackers"] = ["Attackers", "アタッカーズ"]
    transport.rows["Attackers"] = []
    transport.rows["アタッカーズ"] = [_row("m1", [], _maker(1227, "アタッカーズ"))]
    assert provider.resolve(Kind.MAKER, "Attackers") == EntityRef(Kind.MAKER, "1227", "アタッカーズ")
    assert transport.words == ["Attackers", "アタッカーズ"]


def test_maker_all_miss_probes_exactly_three_and_never_asks_the_fourth(transport, provider, spellings):
    names = ["Prestige", "プレステージ", "Prestige Inc", "ＰＲＥＳＴＩＧＥ株式会社"]
    spellings["Prestige"] = names
    for n in names:  # 每個拼法都有 rows，但片商都不是集合內的名字（DMM 沒有名叫 Prestige 的片商）
        transport.rows[n] = [_row("x", [], _maker(1, "DOC")), _row("y", [], _maker(2, "ZETTON"))]
    assert provider.resolve(Kind.MAKER, "Prestige") is None
    assert transport.words == names[:3]  # 恰 3 次，第 4 個從未被問


def test_maker_hit_set_is_all_names_even_beyond_the_first_three(transport, provider, spellings):
    names = ["A", "B", "C", "第四拼法"]
    spellings["A"] = names
    transport.rows["A"] = [_row("x", [], _maker(77, "第四拼法"))]  # 命中集合＝傳入的全部 names
    assert provider.resolve(Kind.MAKER, "A") == EntityRef(Kind.MAKER, "77", "第四拼法")
    assert transport.words == ["A"]


def test_maker_sod_does_not_expand_to_sod_create(transport, provider, spellings):
    # BE-DATA-21：SOD 不併入 SODクリエイト；集合僅 ['SOD']，DMM 的片商叫 SODクリエイト ⇒ 不命中
    spellings["SOD"] = ["SOD"]
    transport.rows["SOD"] = [_row("x", [], _maker(45276, "SODクリエイト"))] * 3
    assert provider.resolve(Kind.MAKER, "SOD") is None
    assert transport.words == ["SOD"]


def test_maker_matches_by_maker_key_not_raw_string(transport, provider, spellings):
    spellings["Moodyz"] = ["Moodyz", "ＭＯＯＤＹＺ"]
    transport.rows["Moodyz"] = [_row("x", [], _maker(1509, "moodyz"))]  # NFKC＋小寫後相等
    assert provider.resolve(Kind.MAKER, "Moodyz") == EntityRef(Kind.MAKER, "1509", "moodyz")


def test_maker_multiple_ids_take_the_most_frequent_then_first_seen(transport, provider, spellings):
    spellings["M"] = ["M"]
    transport.rows["M"] = [_row("a", [], _maker(1, "M")), _row("b", [], _maker(2, "M")),
                           _row("c", [], _maker(2, "M")), _row("d", [], _maker(1, "M")), _row("e", [], None)]
    # 1:2 平手 → 先出現的 1；再加一列 2 → 2 勝
    assert provider.resolve(Kind.MAKER, "M") == EntityRef(Kind.MAKER, "1", "M")
    dmm_mod.clear_probe_cache()
    transport.rows["M"].append(_row("f", [], _maker(2, "M")))
    assert provider.resolve(Kind.MAKER, "M") == EntityRef(Kind.MAKER, "2", "M")


def test_maker_blank_input_is_none_without_request(transport, provider, spellings):
    # spellings 沒有登記任何鍵：若 resolve 還去展開拼法會 KeyError
    assert provider.resolve(Kind.MAKER, "  ") is None
    assert provider.resolve(Kind.MAKER, "\u3000・") is None
    assert transport.total == 0


# ================================================================ 3. SERIES／DIRECTOR／LABEL
@pytest.mark.parametrize("kind, name, expected", [
    (Kind.SERIES, "PLATINUM SOAP", EntityRef(Kind.SERIES, "233224", "PLATINUM SOAP")),
    (Kind.DIRECTOR, "TAKE-D", EntityRef(Kind.DIRECTOR, "101211", "TAKE-D")),  # directors 是 list，每個都比
    (Kind.LABEL, "MOODYZ DIVA", EntityRef(Kind.LABEL, "4325", "MOODYZ DIVA")),
])
def test_named_kinds_exact_hit(transport, provider, kind, name, expected):
    transport.world(name)
    assert provider.resolve(kind, name) == expected
    assert len(transport.list_calls) == 1 and len(transport.facts_calls) == 1


@pytest.mark.parametrize("kind, name", [
    (Kind.SERIES, "PLATINUM SOAP 2"),  # 輸入比站上多一截
    (Kind.SERIES, "PLATINUM"),  # 輸入是站上名稱的前綴
    (Kind.DIRECTOR, "TAKE-DX"),
    (Kind.DIRECTOR, "TAKE"),
    (Kind.LABEL, "MOODYZ DIV"),
    (Kind.LABEL, "MOODYZ DIVA PLUS"),
])
def test_named_kinds_non_equal_names_are_none(transport, provider, kind, name):
    # 使用者打系列名 → 若最新命中的片屬另一個名稱含該字的系列卻照收，清單端出別的系列的片
    transport.world(name)
    assert provider.resolve(kind, name) is None
    assert len(transport.facts_calls) == 1  # 真的比對過 facts，不是沒問


def test_named_kinds_longer_site_name_does_not_match_shorter_input(transport, provider):
    transport.rows["TAKE-D"] = [_row("w1")]
    transport.facts["w1"] = Facts("W-1", None, None, [Named("5", "TAKE-DX")])
    assert provider.resolve(Kind.DIRECTOR, "TAKE-D") is None  # 站上叫 TAKE-DX，輸入 TAKE-D：不是子字串關係就能算同名


def test_named_kinds_skip_missing_alias_and_keep_going(transport, provider):
    transport.world("PLATINUM SOAP")
    del transport.facts["w1"]  # alias 缺漏
    ref = provider.resolve(Kind.SERIES, "PLATINUM SOAP")
    assert ref == EntityRef(Kind.SERIES, "233224", "PLATINUM SOAP")  # w2 仍有
    assert transport.facts_calls == [("w1", "w2", "w3")]


def test_named_kinds_empty_rows_send_no_facts_request(transport, provider):
    assert provider.resolve(Kind.SERIES, "PLATINUM SOAP") is None
    assert transport.facts_calls == []


def test_named_kinds_rows_without_ids_send_no_facts_request(transport, provider):
    transport.rows["PLATINUM SOAP"] = [{"title": "t", "actresses": None, "maker": None}, {"id": ""}]
    assert provider.resolve(Kind.SERIES, "PLATINUM SOAP") is None
    assert transport.facts_calls == []


def test_named_kinds_most_frequent_id_wins_and_ids_are_deduped(transport, provider):
    transport.rows["S"] = [_row("w1"), _row("w2"), _row("w2"), _row("w3")]
    transport.facts.update({
        "w1": Facts(None, Named("1", "S"), None, []),
        "w2": Facts(None, Named("2", "S"), None, []),
        "w3": Facts(None, Named("2", "S"), None, []),
    })
    assert provider.resolve(Kind.SERIES, "S") == EntityRef(Kind.SERIES, "2", "S")
    assert transport.facts_calls == [("w1", "w2", "w3")]  # 依 rows 出現順序、去重


def test_four_kinds_one_name_share_one_list_and_one_facts(transport, provider):
    # 使用者在 DMM 長清單連按「載入更多」→ 梯子每頁重新 resolve；同名連問 ACTOR→SERIES→DIRECTOR→LABEL 只付一次
    transport.world("共用名")
    for kind in (Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL):
        provider.resolve(kind, "共用名")
    assert len(transport.list_calls) == 1
    assert len(transport.facts_calls) == 1


def test_unhandled_kinds_and_blank_input_send_nothing(transport, provider):
    transport.world("x")
    for kind in (Kind.CODE, Kind.PARTIAL, Kind.KEYWORD):
        assert provider.resolve(kind, "x") is None
    for kind in (Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL):
        assert provider.resolve(kind, "") is None
        assert provider.resolve(kind, " 　 ") is None
        assert provider.resolve(kind, "・-_") is None  # fold 後為空
    assert transport.total == 0


# ================================================================ 4. 快取與例外
CACHE_CASES = [
    ("actor-hit", Kind.ACTOR, "三上悠亜", True),
    ("actor-miss", Kind.ACTOR, "不存在的女優", False),
    ("series-hit", Kind.SERIES, "PLATINUM SOAP", True),
    ("series-miss", Kind.SERIES, "NO SUCH SERIES", False),
    ("director-hit", Kind.DIRECTOR, "TAKE-D", True),
    ("director-miss", Kind.DIRECTOR, "NO SUCH DIRECTOR", False),
    ("label-hit", Kind.LABEL, "MOODYZ DIVA", True),
    ("label-miss", Kind.LABEL, "NO SUCH LABEL", False),
    ("maker-hit", Kind.MAKER, "S1", True),
    ("maker-miss", Kind.MAKER, "Prestige", False),
]


@pytest.mark.parametrize("kind, name, hit", [c[1:] for c in CACHE_CASES], ids=[c[0] for c in CACHE_CASES])
def test_second_resolve_of_same_name_sends_no_request(transport, provider, spellings, kind, name, hit):
    # 使用者把 DMM 排第一、看女優／系列清單連按「載入更多」→ 每頁梯子都重新解析名稱；沒快取就每頁多打 1–2 個
    # DMM 請求、多等約 1 秒，翻越多頁越慢
    spellings["S1"] = ["S1", "エスワン ナンバーワンスタイル"]
    spellings["Prestige"] = ["Prestige", "プレステージ", "Prestige Inc", "第四"]
    transport.world(name)  # 登記該名稱自己的 rows＋facts（maker-miss 另補：每個拼法都有 rows 但片商不在集合內）
    if kind is Kind.MAKER:
        for n in spellings[name]:
            transport.rows.setdefault(n, [_row("x", [], MOODYZ)])
    first = provider.resolve(kind, name)
    assert (first is not None) is hit
    assert transport.total > 0  # 第一次真的發了請求，下面的 0 才有意義
    before = (len(transport.list_calls), len(transport.facts_calls))
    second = provider.resolve(kind, name)
    assert second == first
    assert (len(transport.list_calls), len(transport.facts_calls)) == before  # 第二次傳輸呼叫數 0（list 與 facts 都是）


def test_empty_rows_result_is_cached_as_definite_miss(transport, provider):
    assert provider.resolve(Kind.ACTOR, "查無此人") is None
    assert provider.resolve(Kind.SERIES, "查無此人") is None
    assert provider.resolve(Kind.ACTOR, "查無此人") is None
    assert len(transport.list_calls) == 1 and transport.facts_calls == []


EXCEPTIONS = [
    SourceBlocked("blocked"),
    SourceUnreachable("unreachable"),
    requests.Timeout("timeout"),
    requests.ConnectionError("conn"),
]
EXC_IDS = ["SourceBlocked", "SourceUnreachable", "Timeout", "ConnectionError"]


def _expected_hit(kind):
    return {
        Kind.ACTOR: EntityRef(Kind.ACTOR, "1030262", "三上悠亜"),
        Kind.SERIES: EntityRef(Kind.SERIES, "233224", "PLATINUM SOAP"),
        Kind.DIRECTOR: EntityRef(Kind.DIRECTOR, "101211", "TAKE-D"),
        Kind.LABEL: EntityRef(Kind.LABEL, "4325", "MOODYZ DIVA"),
        Kind.MAKER: EntityRef(Kind.MAKER, "3152", "エスワン ナンバーワンスタイル"),
    }[kind]


_NAME = {Kind.ACTOR: "三上悠亜", Kind.SERIES: "PLATINUM SOAP", Kind.DIRECTOR: "TAKE-D",
         Kind.LABEL: "MOODYZ DIVA", Kind.MAKER: "S1"}


@pytest.mark.parametrize("exc", EXCEPTIONS, ids=EXC_IDS)
@pytest.mark.parametrize("kind", list(_NAME), ids=lambda k: k.value)
def test_stage1_failure_propagates_untouched_and_is_not_cached(transport, provider, spellings, kind, exc):
    # DMM 暫擋若被當 None，使用者以為站上沒有這個人（BE-PY-03）
    spellings["S1"] = ["S1", "エスワン ナンバーワンスタイル"]
    name = _NAME[kind]
    transport.world(name)
    transport.fail_list = exc
    with pytest.raises(Exception) as ei:
        provider.resolve(kind, name)
    assert ei.value is exc  # 原樣往外丟：不吞、不轉型
    with pytest.raises(Exception) as ei2:
        provider.resolve(kind, name)  # 再問一次仍發請求（沒有把失敗記成「查無」）
    assert ei2.value is exc
    assert len(transport.list_calls) == 2
    transport.fail_list = None
    assert provider.resolve(kind, name) == _expected_hit(kind)  # 恢復後拿得到真答案，不是殘留的空 Probe
    assert len(transport.list_calls) == 3


@pytest.mark.parametrize("exc", EXCEPTIONS, ids=EXC_IDS)
@pytest.mark.parametrize("kind", [Kind.SERIES, Kind.DIRECTOR, Kind.LABEL], ids=lambda k: k.value)
def test_stage2_failure_propagates_keeps_stage1_and_retries_only_stage2(transport, provider, kind, exc):
    name = _NAME[kind]
    transport.world(name)
    transport.fail_facts = exc
    with pytest.raises(Exception) as ei:
        provider.resolve(kind, name)
    assert ei.value is exc
    assert (len(transport.list_calls), len(transport.facts_calls)) == (1, 1)
    with pytest.raises(Exception) as ei2:
        provider.resolve(kind, name)
    assert ei2.value is exc
    assert (len(transport.list_calls), len(transport.facts_calls)) == (1, 2)  # stage 1 保留、stage 2 重試
    transport.fail_facts = None
    assert provider.resolve(kind, name) == _expected_hit(kind)
    assert (len(transport.list_calls), len(transport.facts_calls)) == (1, 3)
    provider.resolve(kind, name)
    assert (len(transport.list_calls), len(transport.facts_calls)) == (1, 3)  # 成功之後才進快取


def test_maker_failure_on_later_spelling_propagates_and_keeps_earlier_probe(transport, provider, spellings):
    spellings["P"] = ["P", "P2"]
    transport.rows["P"] = [_row("x", [], MOODYZ)]  # 第一個拼法落空（成功的 Probe）
    exc = SourceBlocked("blocked")

    def boom_on_second(self, query_word=None, filter=None, *, limit, offset):
        transport.list_calls.append((query_word, limit, offset, filter))
        if query_word == "P2":
            raise exc
        return ListResult(list(transport.rows.get(query_word, [])), None, False)

    with patch.object(DMMScraper, "list_contents", boom_on_second):
        with pytest.raises(SourceBlocked) as ei:
            provider.resolve(Kind.MAKER, "P")
        assert ei.value is exc
        assert transport.words == ["P", "P2"]
        with pytest.raises(SourceBlocked):
            provider.resolve(Kind.MAKER, "P")
    assert transport.words == ["P", "P2", "P2"]  # 落空的第一格是成功結果＝進快取；失敗的第二格不進


def test_probe_cache_is_cleared_wholesale_past_its_cap(transport, provider, monkeypatch):
    monkeypatch.setattr(dmm_mod, "_PROBE_CACHE_MAX", 3)
    for w in ("a", "b", "c"):
        provider.resolve(Kind.ACTOR, w)
    provider.resolve(Kind.ACTOR, "a")
    assert transport.words == ["a", "b", "c"]  # 未超過上限前都在快取內
    provider.resolve(Kind.ACTOR, "d")  # 第 4 格：整張清空後再放
    assert len(dmm_mod._PROBE_CACHE) == 1
    provider.resolve(Kind.ACTOR, "a")
    assert transport.words == ["a", "b", "c", "d", "a"]


def test_clear_probe_cache_forces_a_new_request(transport, provider):
    provider.resolve(Kind.ACTOR, "x")
    dmm_mod.clear_probe_cache()
    provider.resolve(Kind.ACTOR, "x")
    assert transport.words == ["x", "x"]


# ================================================================ 5. I-D1 完整路徑＋capabilities（T8 起宣告四種實體＋KEYWORD，T9 起再加 MAKER）
def test_capabilities_declare_five_entities_plus_keyword_since_t9():
    assert DMMProvider.capabilities == frozenset(
        {Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL, Kind.MAKER, Kind.KEYWORD})


def test_no_entity_lookup_fixture_covers_dmm(transport, provider, no_entity_lookup):
    assert provider.resolve(Kind.ACTOR, "三上悠亜") is None
    assert transport.total == 0


class _SyncExecutor:
    def __init__(self, max_workers=None, **_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args, **kwargs):
        fut = cf.Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut


@pytest.fixture
def ladder(monkeypatch, transport):
    """DMM 經真 registry 進鏈、用產品碼實際宣告的能力（T8 起）；傳輸替身＋_fetch_by_id 替身。"""
    monkeypatch.setattr(cf, "ThreadPoolExecutor", _SyncExecutor)
    monkeypatch.setattr(cf, "as_completed", lambda fs, timeout=None: list(fs))
    monkeypatch.setattr("core.scrapers.dmm.rate_limit", lambda *a, **kw: None)
    monkeypatch.setattr("core.scraper.get_all_source_ids_ordered", lambda: ["dmm"])
    monkeypatch.setattr("core.scraper.is_source_enabled", lambda pid: pid == "dmm")
    transport.fetched = []

    def fetch_by_id(cid):
        transport.fetched.append(cid)
        return Video(number="SONE-001", title="full", source="dmm", date="2024-01-01")

    with patch.object(DMMScraper, "_fetch_by_id", side_effect=fetch_by_id):
        yield transport


def test_ladder_cold_nonentity_word_costs_at_most_four_requests_second_time_at_most_two(ladder):
    # 使用者在 DMM 排第一打一個既非實體的詞 → 若 Probe 沒共用／沒快取，每次搜尋白多打好幾個請求、結果出得更慢，
    # 畫面看起來只是變慢
    t = ladder
    keyword_rows = [_row("sone00001", [_act(1, "誰か")], MOODYZ)]
    t.rows["温泉"] = keyword_rows
    t.facts["sone00001"] = Facts("SONE-001", None, None, [])

    cards = relay.search_by_intent("actress", "温泉", WINDOW)
    assert cards and t.fetched == ["sone00001"]  # KEYWORD 的 run 真的跑了（上界恆真的防線之一）
    cold_list, cold_facts = len(t.list_calls), len(t.facts_calls)
    assert cold_list >= 2 and cold_facts >= 1  # 下界：梯子真的問了 DMM（ACTOR 的 stage 1＋KEYWORD；SERIES 的 stage 2）
    assert cold_list + cold_facts <= 4  # I-D1 plan 值
    assert (cold_list, cold_facts) == (2, 2)  # T8 實況：ACTOR 的 stage 1＋KEYWORD 列表；SERIES 的 stage 2＋KEYWORD 的官方番號 facts

    cards2 = relay.search_by_intent("actress", "温泉", WINDOW)
    assert cards2
    second = (len(t.list_calls) - cold_list, len(t.facts_calls) - cold_facts)
    assert second[0] >= 1  # KEYWORD 仍然問了列表
    assert sum(second) <= 2  # I-D1 plan 值
    assert second == (1, 1)  # T8 實況（Probe 命中快取；KEYWORD 列表 1＋官方番號 facts 1）


def test_ladder_probe_is_shared_across_kinds_for_the_same_word(ladder):
    t = ladder
    t.rows["温泉"] = [_row("sone00001", [], MOODYZ)]
    relay.search_by_intent("actress", "温泉", WINDOW)
    assert t.words.count("温泉") == 2  # 一次 Probe（ACTOR/SERIES/DIRECTOR/LABEL 共用）＋一次 KEYWORD
    assert len(t.facts_calls) == 2  # SERIES 的 stage 2（DIRECTOR／LABEL 命中快取）＋KEYWORD 的官方番號 facts（T8）
