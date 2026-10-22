"""
測試女優資料卡功能（Graphis + JavBus 雙來源）

包含：
- get_actress_profile 合併邏輯 mock 測試
- Cache 機制測試（全 mock，不打外部）
- Consistency check 單元測試（純邏輯，不需 mock）
- API 整合測試（mock search 結果 + mock actress profile）
"""

import json

import pytest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Datetime freeze (for TD-1: current_age computed from birth via datetime.now)
# ---------------------------------------------------------------------------
from datetime import datetime as _real_datetime

# Frozen instant for age computation: 2026-04-11 (current project date)
_FROZEN_NOW = _real_datetime(2026, 4, 11, 0, 0, 0)


class _FrozenDatetime(_real_datetime):
    """datetime subclass with now() overridden to a frozen instant.
    strptime/other methods inherited from real datetime."""
    @classmethod
    def now(cls, tz=None):
        return _FROZEN_NOW


@pytest.fixture(autouse=True)
def _freeze_orchestrator_datetime(monkeypatch):
    """Autouse: freeze datetime.now() as seen by
    core.scrapers.actress.orchestrator._compute_age_from_birth."""
    monkeypatch.setattr(
        "core.scrapers.actress.orchestrator.datetime",
        _FrozenDatetime,
    )


@pytest.fixture(autouse=True)
def clear_actress_cache():
    from core.scrapers.actress.orchestrator import _cache
    _cache.clear()
    yield
    _cache.clear()


# ============================================================================
# get_actress_profile 測試（Mock）
# ============================================================================

def test_get_actress_profile_both_sources():
    """測試雙來源合併邏輯（Mock）"""
    from core.scrapers.actress.orchestrator import get_actress_profile, _cache

    # Mock Graphis 回傳照片（含 birth/height/cup 供 TD-1 + text cascade 測試）
    def mock_graphis(name):
        return {
            'name': name,
            'prof_url': 'https://graphis.ne.jp/prof.jpg',
            'backdrop_url': 'https://graphis.ne.jp/model.jpg',
            'birth': '1997-12-03',
            'height': '160cm',
            'cup': 'G',
        }

    with patch('core.scrapers.actress.xcity.scrape_xcity', return_value=None), \
         patch('core.scrapers.actress.wiki_ja.scrape_wiki_ja', return_value=None), \
         patch('core.scrapers.actress.graphis.scrape_graphis_photo', side_effect=mock_graphis), \
         patch('core.scrapers.actress.gfriends.lookup_gfriends', return_value=None):

        result = get_actress_profile("桜空もも")

        assert result.data is not None
        # Graphis 照片優先（gfriends 回傳 None）
        assert result.data['img'] == 'https://graphis.ne.jp/prof.jpg'
        assert result.data['backdrop'] == 'https://graphis.ne.jp/model.jpg'

        # Graphis supplies text when xcity and wiki return nothing.
        assert result.data['birth'] == '1997-12-03'   # from graphis (via text cascade)
        assert result.data['age'] == 28                # TD-1: from birth 1997-12-03 + frozen 2026-04-11
        assert result.data['height'] == '160cm'
        assert result.data['cup'] == 'G'
        assert result.timed_out is False


# ============================================================================
# Cache 機制測試（全 mock）
# ============================================================================

def test_get_actress_profile_cache_hit():
    """測試 cache 命中（Mock）"""
    from core.scrapers.actress.orchestrator import get_actress_profile, _cache

    def mock_graphis(name):
        return {
            'name': name,
            'prof_url': 'https://graphis.ne.jp/prof.jpg',
            'backdrop_url': 'https://graphis.ne.jp/model.jpg'
        }

    with patch('core.scrapers.actress.xcity.scrape_xcity', return_value=None), \
         patch('core.scrapers.actress.wiki_ja.scrape_wiki_ja', return_value=None) as wiki_mock, \
         patch('core.scrapers.actress.graphis.scrape_graphis_photo', side_effect=mock_graphis) as graphis_mock, \
         patch('core.scrapers.actress.gfriends.lookup_gfriends', return_value=None):

        # 第一次呼叫
        result1 = get_actress_profile("桜空もも")
        assert result1.data is not None
        assert graphis_mock.call_count == 1

        # 第二次呼叫（應從 cache 取得）
        result2 = get_actress_profile("桜空もも")
        assert result2.data is not None
        assert result1.data == result2.data
        # Mock 不應被再次呼叫
        assert graphis_mock.call_count == 1


# ============================================================================
# Consistency Check 單元測試（純邏輯，不需 mock）
# ============================================================================

def test_analyze_top_actor_single_actress():
    """測試單一女優佔比 100%"""
    from web.routers.search import _analyze_top_actor

    results = [
        {'actors': ['桜空もも']},
        {'actors': ['桜空もも']},
        {'actors': ['桜空もも']},
    ]

    top_actor = _analyze_top_actor(results, threshold=0.8, min_samples=3)
    assert top_actor == '桜空もも'


def test_analyze_top_actor_mixed_below_threshold():
    """測試混合結果（佔比 < 80%）"""
    from web.routers.search import _analyze_top_actor

    results = [
        {'actors': ['古川いおり']},
        {'actors': ['古川いおり']},
        {'actors': ['古川いおり']},
        {'actors': ['古川祐子']},
        {'actors': ['古川ななせ']},
    ]

    top_actor = _analyze_top_actor(results, threshold=0.8, min_samples=3)
    assert top_actor is None  # 3/5 = 60% < 80%


# ============================================================================
# API 整合測試（Mock search 結果 + mock actress profile）
# ============================================================================

@pytest.fixture
def mock_search_actress():
    """Mock 女優搜尋結果"""
    def mock_fn(q, **kwargs):
        return [
            {'number': 'SONE-205', 'actors': ['桜空もも']},
            {'number': 'SONE-180', 'actors': ['桜空もも']},
            {'number': 'SONE-162', 'actors': ['桜空もも']},
        ]
    return mock_fn


@pytest.fixture
def mock_actress_profile():
    """Mock 女優資料（回傳 ProfileResult namedtuple，T3 後的型別）"""
    from core.scrapers.actress.orchestrator import ProfileResult

    def mock_fn(name, **kwargs):
        if name == '桜空もも':
            data = {
                'name': '桜空もも',
                'img': 'https://graphis.ne.jp/prof.jpg',
                'backdrop': 'https://graphis.ne.jp/model.jpg',
                'birth': '1996-12-03',
                'age': 29
            }
            return ProfileResult(data=data, timed_out=False)
        return ProfileResult(data=None, timed_out=False)
    return mock_fn


def test_search_api_actress_with_profile(
    client, mock_search_actress, mock_actress_profile, tmp_path
):
    """測試女優搜尋 API（有 actress_profile）"""
    # web/routers/search.py:_fetch_actress_profile_with_db 無條件呼叫 init_db() +
    # AliasRepository().resolve(top_actor)，未 mock 前兩者都連上 output/openaver.db。
    with patch('web.routers.search.search_actress', side_effect=mock_search_actress), \
         patch('core.scrapers.actress.orchestrator.get_actress_profile', side_effect=mock_actress_profile), \
         patch('core.database.ActressRepository.get_by_name', return_value=None), \
         patch('core.database.connection.get_db_path', return_value=tmp_path / "test.db"):

        resp = client.get("/api/search?q=桜空もも&mode=actress")
        data = resp.json()

        assert data['success'] is True
        assert data['mode'] == 'actress'
        assert 'actress_profile' in data
        assert data['actress_profile'] is not None
        assert data['actress_profile']['name'] == '桜空もも'
        assert 'graphis.ne.jp' in data['actress_profile']['img']


def test_sse_includes_actress_profile(
    client, mock_search_actress, mock_actress_profile, tmp_path
):
    """SSE result event 應包含 actress_profile"""
    # AliasRepository.resolve 已 mock，但 _fetch_actress_profile_with_db 開頭的
    # init_db() 無條件執行，未 mock 前仍連上 output/openaver.db。
    with patch('web.routers.search.smart_search', side_effect=mock_search_actress), \
         patch('core.scrapers.actress.orchestrator.get_actress_profile', side_effect=mock_actress_profile), \
         patch('core.database.ActressRepository.get_by_name', return_value=None), \
         patch('core.database.AliasRepository.resolve', side_effect=lambda n: {n}), \
         patch('core.database.connection.get_db_path', return_value=tmp_path / "test.db"):

        response = client.get('/api/search/stream?q=桜空もも')

        # Parse SSE events
        events = []
        for line in response.text.strip().split('\n'):
            if line.startswith('data: '):
                event_data = json.loads(line[6:])  # Remove 'data: ' prefix
                events.append(event_data)

        # Find result event
        result_events = [e for e in events if e.get('type') == 'result']
        assert len(result_events) == 1

        result_event = result_events[0]
        assert result_event['success'] is True
        assert 'actress_profile' in result_event
        assert result_event['actress_profile'] is not None
        assert result_event['actress_profile']['name'] == '桜空もも'
        assert 'graphis.ne.jp' in result_event['actress_profile']['img']


# ============================================================================
# get_actress_profile 合併邏輯測試（T2/T3 新增）
# ============================================================================

def _make_graphis_result(name="桜空もも", **overrides):
    """Helper: 建立完整的 graphis mock 回傳值（含所有欄位）"""
    base = {
        'name': name,
        'prof_url': 'https://graphis.ne.jp/prof.jpg',
        'backdrop_url': 'https://graphis.ne.jp/model.jpg',
        'name_en': 'Momo Sakurazora',
        'birth': '1997-12-03',  # TD-1: birth 1997-12-03 + frozen 2026-04-11 → age 28
        'age': 28,
        'height': '160cm',
        'cup': 'G',
        'bust': '90cm',
        'waist': '55cm',
        'hip': '86cm',
        'hobby': 'ゲーム',
    }
    base.update(overrides)
    return base


def test_get_actress_profile_gfriends_wins():
    """gfriends 圖片勝出：graphis 無 prof_url 時，gfriends 應成為 photo cascade 的 winner。
    T4.3 note: orchestrator photo cascade = graphis prof_url → gfriends → wiki → xcity.
    To let gfriends win, graphis must have prof_url=None."""
    from core.scrapers.actress.orchestrator import get_actress_profile, _cache

    gfriends_url = 'https://cdn.jsdelivr.net/gh/gfriends/gfriends@master/Content/7-S1/桜空もも.jpg'

    with patch('core.scrapers.actress.xcity.scrape_xcity', return_value=None), \
         patch('core.scrapers.actress.wiki_ja.scrape_wiki_ja', return_value=None), \
         patch('core.scrapers.actress.graphis.scrape_graphis_photo', return_value=_make_graphis_result(prof_url=None)), \
         patch('core.scrapers.actress.gfriends.lookup_gfriends', return_value=gfriends_url):

        result = get_actress_profile("桜空もも", makers=['S1'])

        assert result.data is not None
        # gfriends wins photo cascade (graphis has no prof_url, javbus is ignored)
        assert result.data['img'] == gfriends_url
        # Backdrop still comes from graphis
        assert result.data['backdrop'] == 'https://graphis.ne.jp/model.jpg'
        assert result.timed_out is False


def test_get_actress_profile_gfriends_only():
    """gfriends 有圖但 javbus/graphis 都沒資料 → 仍回傳 minimal profile"""
    from core.scrapers.actress.orchestrator import get_actress_profile, _cache

    gfriends_url = 'https://cdn.jsdelivr.net/gh/gfriends/gfriends@master/Content/7-S1/桜空もも.jpg'

    with patch('core.scrapers.actress.xcity.scrape_xcity', return_value=None), \
         patch('core.scrapers.actress.wiki_ja.scrape_wiki_ja', return_value=None), \
         patch('core.scrapers.actress.graphis.scrape_graphis_photo', return_value=None), \
         patch('core.scrapers.actress.gfriends.lookup_gfriends', return_value=gfriends_url):

        result = get_actress_profile("桜空もも", makers=['S1'])

        assert result.data is not None
        # Bug 2 fix: name falls back to queried name arg when all text sources are None
        assert result.data['name'] == '桜空もも'
        assert result.data['img'] == gfriends_url
        assert result.timed_out is False


# ============================================================================
# Router makers 傳遞測試
# ============================================================================


def test_sse_passes_makers_to_profile(client, tmp_path):
    """SSE /api/search/stream 路徑：_extract_top_makers 的結果應傳給 get_actress_profile"""
    from core.scrapers.actress.orchestrator import ProfileResult

    def mock_smart_search(q, **kwargs):
        return [
            {'number': 'SONE-205', 'actors': ['桜空もも']},
            {'number': 'SONE-180', 'actors': ['桜空もも']},
            {'number': 'SONE-162', 'actors': ['桜空もも']},
        ]

    mock_profile = MagicMock(return_value=ProfileResult(data={
        'name': '桜空もも',
        'img': 'https://graphis.ne.jp/prof.jpg',
        'backdrop': 'https://graphis.ne.jp/model.jpg',
    }, timed_out=False))

    # init_db()/AliasRepository().resolve() 未 mock 前連上 output/openaver.db。
    with patch('web.routers.search.smart_search', side_effect=mock_smart_search), \
         patch('core.scrapers.actress.orchestrator.get_actress_profile', mock_profile), \
         patch('core.database.ActressRepository.get_by_name', return_value=None), \
         patch('core.database.connection.get_db_path', return_value=tmp_path / "test.db"):

        response = client.get('/api/search/stream?q=桜空もも')

        # SSE should have triggered get_actress_profile
        assert mock_profile.called
        call_kwargs = mock_profile.call_args
        # Should have been called with makers=['S1']
        # (SONE prefix maps to 'S1' in maker_mapping.json)
        makers_arg = call_kwargs.kwargs.get('makers')
        assert makers_arg is not None
        assert isinstance(makers_arg, list)
        assert 'S1' in makers_arg
