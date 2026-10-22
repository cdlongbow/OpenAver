import math

from core.similar.idf import build_idf, idf_jaccard


def test_build_idf_uneven_dictionary_rare_higher_than_common():
    corpus: list[list[str]] = []
    # 100 docs: "common" in 10, "rare" in 1
    for _ in range(10):
        corpus.append(["common"])
    corpus.append(["rare"])
    for _ in range(89):
        corpus.append([])
    result = build_idf(corpus)
    assert result["common"] > 0
    assert result["rare"] > 0
    assert result["rare"] > result["common"]


def test_build_idf_hot_strict_greater_than_25_percent_above_is_hot():
    # 100 docs, df=26 -> df/N = 0.26 > 0.25 -> hot
    corpus: list[list[str]] = [["y"]] * 26 + [[]] * 74
    result = build_idf(corpus)
    assert result["y"] == 0.0


def test_idf_jaccard_double_empty():
    assert idf_jaccard(set(), set(), {}) == 0.0


def test_idf_jaccard_partial_overlap_uneven_weights():
    result = idf_jaccard({"a", "b"}, {"b", "c"}, {"a": 1.0, "b": 2.0, "c": 3.0})
    assert math.isclose(result, 2.0 / 6.0)


def test_idf_jaccard_hot_tag_does_not_contribute():
    table = {"hot": 0.0, "rare": 5.0}
    assert idf_jaccard({"hot", "rare"}, {"hot"}, table) == 0.0


