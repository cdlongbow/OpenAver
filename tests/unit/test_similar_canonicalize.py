import pytest
from unittest.mock import patch, MagicMock
from core.similar.canonicalize import (
    canonicalize,
    _invalidate_cache,
)


@pytest.fixture(autouse=True)
def isolate_canonicalize_cache():
    """每 test 前後清 cache + mock TagAliasRepository 為空，避免讀真實 dev DB"""
    _invalidate_cache()
    mock_repo = MagicMock()
    mock_repo.get_all.return_value = []
    with patch('core.database.TagAliasRepository', return_value=mock_repo):
        yield
    _invalidate_cache()


def test_alias_hit_one_way():
    assert canonicalize(["中出"]) == ["中出し"]


def test_stopword_filter():
    assert canonicalize(["高畫質"]) == []


