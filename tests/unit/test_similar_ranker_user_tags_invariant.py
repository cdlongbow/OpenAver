"""B2：SimilarRanker 內部狀態與排序不受 user_tags 影響。

被鎖行為現已正確；本檔以行為測試鎖住，不以原始碼字面守衛。
fixture 刻意讓 df 比例落在 hot 門檻之下，rank(top_k=12) 在 Tier 1 填滿——
不得用 random.seed() 掩蓋 fallback 非決定性。
"""

from core.database import Video
from core.similar.ranker import SimilarRanker

_TIER1_CANARY_MSG = (
    "Tier 1 已不再填滿 → 排序斷言不再具決定性 → "
    "請重新設計 fixture 的 df 比例，不要用 random seed 掩蓋"
)

_SHARED_TAGS = ["痴女", "中出"]
_N_CORE = 13  # target + 12 候選
_N_PAD = 47
_TOP_K = 12


def _build_corpus(with_user_tags: bool) -> list[Video]:
    """N=60：前 13 部共享兩個 tag（13/60=21.7% ≤ 0.25），後 47 部壓 df。"""
    videos: list[Video] = []
    for i in range(_N_CORE):
        user_tags = ["中字", f"手動{i}"] if with_user_tags else []
        videos.append(
            Video(
                number=f"CORE-{i:03d}",
                tags=_SHARED_TAGS + [f"獨有{i}"],
                user_tags=user_tags,
            )
        )
    for i in range(_N_PAD):
        user_tags = ["中字", f"手動P{i}"] if with_user_tags else []
        videos.append(
            Video(
                number=f"PAD-{i:03d}",
                tags=[f"雜訊{i}"],
                user_tags=user_tags,
            )
        )
    return videos


def test_internal_state_equal_with_and_without_user_tags():
    """_canon_tags / _idf_table / _inverted_index 在 clean/dirty corpus 下逐項相等。"""
    clean = SimilarRanker(_build_corpus(False))
    dirty = SimilarRanker(_build_corpus(True))
    assert clean._canon_tags == dirty._canon_tags
    assert clean._idf_table == dirty._idf_table
    assert clean._inverted_index == dirty._inverted_index


def test_rank_order_and_scores_equal_with_and_without_user_tags():
    """rank() 的 number 序列相等，且逐項 _score() 相等。"""
    clean_corpus = _build_corpus(False)
    dirty_corpus = _build_corpus(True)
    clean = SimilarRanker(clean_corpus)
    dirty = SimilarRanker(dirty_corpus)
    clean_target = clean_corpus[0]
    dirty_target = dirty_corpus[0]

    clean_out = clean.rank(clean_target, top_k=_TOP_K)
    dirty_out = dirty.rank(dirty_target, top_k=_TOP_K)

    assert [v.number for v in clean_out] == [v.number for v in dirty_out]
    for c_cand, d_cand in zip(clean_out, dirty_out):
        assert clean._score(clean_target, c_cand) == dirty._score(dirty_target, d_cand)


def test_tier1_canary_fills_top_k():
    """rank() 回傳 12 筆，且每筆與 target 共享 ≥2 個 useful tag。"""
    for with_user_tags in (False, True):
        corpus = _build_corpus(with_user_tags)
        ranker = SimilarRanker(corpus)
        target = corpus[0]
        ranked = ranker.rank(target, top_k=_TOP_K)
        assert len(ranked) == _TOP_K, _TIER1_CANARY_MSG
        target_useful = ranker._useful_set(target)
        for cand in ranked:
            shared = target_useful & ranker._useful_set(cand)
            assert len(shared) >= 2, _TIER1_CANARY_MSG
