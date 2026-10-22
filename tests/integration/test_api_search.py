"""
test_api_search.py - 搜尋 API 整合測試

使用 mocker.patch Mock 爬蟲回應，驗證搜尋 API 行為。
"""

import logging
import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock, ANY

pytestmark = pytest.mark.usefixtures("empty_library_makers")


def load_fixture(filename: str) -> dict:
    """載入 Mock JSON fixture"""
    fixture_path = Path(__file__).parent.parent / 'fixtures' / filename
    with open(fixture_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ============ 番號搜尋 ============


class TestSearchSourceValidation:
    """測試 source 參數驗證（TASK-61a-4：改用 validate_source_id）"""

    def test_unknown_source_returns_400(self, client):
        """未知 source → 400，格式逐字 {success: False, error: '未知來源: nope'}"""
        response = client.get('/api/search', params={'q': 'SONE-103', 'source': 'nope'})
        assert response.status_code == 400
        data = response.json()
        assert data == {"success": False, "error": "未知來源: nope"}


class TestSearchSourceExactModeRequired:
    """測試 TASK-135-T7：指定 source 必須搭配 mode=exact（CD-135-9 / AC-13）"""

    def test_auto_mode_with_source_returns_400(self, client):
        """mode=auto ＋ source=dmm → 400（DoD-1）"""
        response = client.get('/api/search', params={'q': 'SONE-103', 'mode': 'auto', 'source': 'dmm'})
        assert response.status_code == 400
        assert response.json() == {
            "success": False,
            "error": "source 僅在 mode=exact 時生效，請改用 mode=exact 或移除 source",
        }


    def test_exact_mode_with_source_unaffected(self, client, mocker):
        """合法組合：mode=exact ＋ source=dmm → 照舊行為，不受本檢查影響（DoD-3）"""
        mock_data = load_fixture('responses/javbus/SONE-103.json')
        mocker.patch('core.scraper.search_jav_single_source', return_value=mock_data)

        response = client.get('/api/search', params={'q': 'SONE-103', 'mode': 'exact', 'source': 'dmm'})

        assert response.status_code != 400
        data = response.json()
        assert data['success'] is True
        assert data['data'][0]['number'] == 'SONE-103'


class TestSearchSources:
    """搜尋來源 API 測試"""

    def test_get_sources(self, client):
        """測試取得搜尋來源"""
        response = client.get("/api/search/sources")
        assert response.status_code == 200
        data = response.json()

        # 檢查 sources 存在且內容合理
        assert "sources" in data
        assert isinstance(data["sources"], list)
        assert len(data["sources"]) >= 2  # 至少有 auto 和特定爬蟲來源
        assert all(isinstance(s, dict) for s in data["sources"])
        assert all("id" in s and "name" in s for s in data["sources"])

        # 檢查 auto 選項存在
        source_ids = [s["id"] for s in data["sources"]]
        assert "auto" in source_ids


    def test_sources_order_no_manual_only(self, client):
        """測試 order 不含 manual_only（javlibrary）與 metatube provider（D7 守衛）

        ⟳ switch-source 只輪替 builtin non-manual 來源；javlibrary 是
        manual_only、metatube:* 是遠端 provider，皆不應出現在 order。
        """
        response = client.get("/api/search/sources")
        data = response.json()

        assert "javlibrary" not in data["order"]
        assert not any(s.startswith("metatube:") for s in data["order"])

    def test_sources_order_full_set_under_partial_config(self, client):
        """partial-builtin config（只含 3 row）下 order 仍回全 8 builtin（Codex P1 守衛）

        _is_valid_sources 把 partial sources 段視為合法 idempotent、不補齊；route
        不得因此縮小 ⟳ 可切換集合。order 應 backfill 至全 8 個 builtin 且 ⊆ sources。
        """
        from core.scrapers.utils import SOURCE_ORDER
        partial_config = {
            'sources': [
                {'id': 'javbus', 'type': 'builtin', 'enabled': True, 'order': 1},
                {'id': 'dmm', 'type': 'builtin', 'enabled': True, 'order': 0},
                {'id': 'javdb', 'type': 'builtin', 'enabled': True, 'order': 2},
            ]
        }
        with patch("core.source_settings.load_config", return_value=partial_config):
            response = client.get("/api/search/sources")
        data = response.json()

        assert set(data["order"]) == set(SOURCE_ORDER)
        # 前 3 依 config order
        assert data["order"][:3] == ['dmm', 'javbus', 'javdb']
        # order⊆sources 契約仍成立
        source_ids = {s["id"] for s in data["sources"] if s["id"] != "auto"}
        assert set(data["order"]).issubset(source_ids)


# ============ SSE Stream 協議測試 ============

class TestSearchStreamSSE:
    """測試 /api/search/stream SSE 協議行為"""

    def test_exact_mode_sends_result_event(self, client, parse_sse_events):
        """exact 番號搜尋應送傳統 result event，不受 seed/result-item 影響（C8）"""
        mock_result = {
            'number': 'SSIS-816',
            'title': 'Some Title',
            'actors': ['三上悠亜'],
            '_mode': 'exact'
        }

        def mock_smart_search(q, limit=20, offset=0, status_callback=None,
                              result_callback=None, **kwargs):
            # exact mode: status_callback only, no result_callback calls
            if status_callback:
                status_callback('javbus', 'searching')
                status_callback('done', 'found:1')
            return [mock_result]

        with patch('web.routers.search.smart_search', side_effect=mock_smart_search):
            response = client.get('/api/search/stream?q=SSIS-816')

        events = parse_sse_events(response.text)
        result_events = [e for e in events if e.get('type') == 'result']

        assert len(result_events) == 1, f"Exact mode should have exactly 1 result event, got {result_events}"
        result_event = result_events[0]
        assert result_event['success'] is True
        assert 'data' in result_event
        assert result_event['total'] == 1

        # Must NOT have seed or result-item or result-complete for exact mode
        assert not any(e.get('type') == 'seed' for e in events), \
            "Exact mode should not send seed event"
        assert not any(e.get('type') == 'result-item' for e in events), \
            "Exact mode should not send result-item event"
        assert not any(e.get('type') == 'result-complete' for e in events), \
            "Exact mode should not send result-complete event"


    @pytest.fixture
    def actress_mode_events(self, client, parse_sse_events, tmp_path):
        """共用 fixture：執行 actress 模式的 smart_search 並回傳解析後的 SSE events"""
        ids = ['SONE-100', 'SONE-101', 'SONE-102']
        items = {
            'SONE-100': {'number': 'SONE-100', 'title': 'Title 100', 'actors': ['三上悠亜']},
            'SONE-101': {'number': 'SONE-101', 'title': 'Title 101', 'actors': ['三上悠亜']},
            'SONE-102': {'number': 'SONE-102', 'title': 'Title 102', 'actors': ['三上悠亜']},
        }

        def mock_smart_search(q, limit=20, offset=0, status_callback=None,
                              result_callback=None, **kwargs):
            if status_callback:
                status_callback('javbus', 'searching')
                status_callback('javbus', f'found:{len(ids)}')
            if result_callback:
                result_callback(-1, ids)
            for idx, num in enumerate(ids):
                if result_callback:
                    result_callback(idx, items[num])
            if status_callback:
                status_callback('done', f'found:{len(ids)}')
            return list(items.values())

        # 3 筆同演員（100% consistency）觸發 _fetch_actress_profile_with_db，
        # 其 init_db() + AliasRepository().resolve()/ActressRepository().get_by_name()
        # 未 mock 前會連上 output/openaver.db（此 fixture 本身不驗 actress_profile
        # 內容，全數 mock 掉即可）。
        with patch('web.routers.search.smart_search', side_effect=mock_smart_search), \
             patch('core.database.ActressRepository.get_by_name', return_value=None), \
             patch('core.database.connection.get_db_path', return_value=tmp_path / "test.db"), \
             patch('web.routers.search._fetch_actress_profile_with_db', return_value=None):
            response = client.get('/api/search/stream?q=三上悠亜')

        events = parse_sse_events(response.text)
        return events, ids


    def test_actress_mode_sends_result_and_ordering(self, actress_mode_events):
        """actress 模式下 SSE 應送出 result event，且 result-complete 在 result 之前"""
        events, _ = actress_mode_events
        result_events = [e for e in events if e.get('type') == 'result']
        assert len(result_events) == 1
        result_event = result_events[0]
        assert result_event['success'] is True
        assert 'data' in result_event
        assert isinstance(result_event['data'], list)
        assert result_event['total'] == 3
        assert 'mode' in result_event

        complete_idx = next(i for i, e in enumerate(events) if e.get('type') == 'result-complete')
        result_idx = next(i for i, e in enumerate(events) if e.get('type') == 'result')
        assert complete_idx < result_idx, "result-complete must appear before result event in the stream"


    def test_double_seed_protection(self, client, parse_sse_events):
        """prefix→actress fallback 修正後：fallback 不傳 result_callback，只有一個 seed
        且最終 result event 包含正確資料"""
        ids1 = ['SONE-100', 'SONE-101']
        final_results = [{'number': 'SONE-100', 'title': 'T1'}, {'number': 'SONE-101', 'title': 'T2'}]

        def mock_smart_search(q, limit=20, offset=0, status_callback=None,
                              result_callback=None, **kwargs):
            # Real behavior after fix: prefix sends seed, fallback actress gets no callback
            if result_callback:
                result_callback(-1, ids1)  # only one seed (from prefix path)
                result_callback(0, final_results[0])
                result_callback(1, final_results[1])
            return final_results

        with patch('web.routers.search.smart_search', side_effect=mock_smart_search):
            response = client.get('/api/search/stream?q=SONE')

        events = parse_sse_events(response.text)

        # Exactly one seed event
        seed_events = [e for e in events if e.get('type') == 'seed']
        assert len(seed_events) == 1, \
            f"Only 1 seed should be sent after fix, got {len(seed_events)}"
        assert set(seed_events[0]['slots']) == set(ids1), \
            "Seed slots should be from prefix path"

        # MUST have traditional result event (always sent)
        result_events = [e for e in events if e.get('type') == 'result']
        assert len(result_events) == 1, \
            f"Must have exactly 1 result event, got {len(result_events)}"
        result_event = result_events[0]
        assert result_event['success'] is True
        assert result_event['total'] == 2

        # MUST have result-complete (since sent_seed=True)
        complete_events = [e for e in events if e.get('type') == 'result-complete']
        assert len(complete_events) == 1, \
            f"Must have result-complete when seed was sent, got {len(complete_events)}"


class TestFilterFiles:
    """Test /api/search/filter-files"""


    def test_strm_not_filtered_by_min_size(self, client, tmp_path, monkeypatch):
        """.strm file should NOT be filtered by min_size setting"""
        # Create a .strm file (100 bytes)
        strm_file = tmp_path / "test.strm"
        strm_file.write_bytes(b'http://example.com/video.mp4')

        # Create config with .strm in video_extensions and min_size_mb=1
        test_config = {
            "scraper": {"video_extensions": [".mp4", ".strm"]},
            "gallery": {"min_size_mb": 1},
        }

        def mock_load_config():
            return test_config
        monkeypatch.setattr("core.config.load_config", mock_load_config)

        response = client.post(
            "/api/search/filter-files",
            json={"paths": [str(strm_file)]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["files"]) == 1, \
            ".strm file should NOT be filtered by min_size (ZERO_SIZE_EXTENSIONS exemption)"
        assert data["rejected"]["size"] == 0

    def test_small_mp4_still_filtered_by_min_size(self, client, tmp_path, monkeypatch):
        """A small .mp4 file should still be filtered by min_size"""
        # Create a small .mp4 file (100 bytes)
        mp4_file = tmp_path / "small.mp4"
        mp4_file.write_bytes(b'\x00' * 100)

        test_config = {
            "scraper": {"video_extensions": [".mp4", ".strm"]},
            "gallery": {"min_size_mb": 1},
        }

        def mock_load_config():
            return test_config
        monkeypatch.setattr("core.config.load_config", mock_load_config)

        response = client.post(
            "/api/search/filter-files",
            json={"paths": [str(mp4_file)]}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["files"]) == 0, \
            "Small .mp4 file should be filtered by min_size"
        assert data["rejected"]["size"] == 1


class TestFavoriteFiles:
    """Test /api/search/favorite-files"""

    def test_favorite_files_unset_non_desktop_returns_error_without_scanning_cwd(
        self, client, monkeypatch, mocker
    ):
        from core import config as core_config

        monkeypatch.delenv("OPENAVER_STANDALONE", raising=False)
        core_config.mutate_config(
            lambda cfg: cfg.setdefault("search", {}).update({"favorite_folder": ""})
        )
        list_files = mocker.patch("core.favorite_scan.list_favorite_video_files", return_value=[])

        response = client.get("/api/search/favorite-files")

        assert response.status_code == 200
        assert response.json()["success"] is False
        assert response.json()["error"] == "favorite_folder_unset"
        list_files.assert_not_called()

    def test_get_favorite_files_success(self, client, tmp_path, monkeypatch):
        """測試取得我的最愛資料夾檔案成功"""
        fav_dir = tmp_path / "fav"
        fav_dir.mkdir()
        
        video_file = fav_dir / "test_fav.mp4"
        video_file.write_bytes(b'x' * (1 * 1024 * 1024 + 1))
        
        txt_file = fav_dir / "test.txt"
        txt_file.write_bytes(b'hello')
        
        test_config = {
            "scraper": {"video_extensions": [".mp4"]},
            "gallery": {"min_size_mb": 1},
            "search": {"favorite_folder": str(fav_dir)}
        }
        monkeypatch.setattr("core.config.load_config", lambda: test_config)
        
        response = client.get("/api/search/favorite-files")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["files"]) == 1
        assert "test_fav.mp4" in data["files"][0]


# ============ T5a — 新欄位透傳 + proxy-image Referer ============


class TestProxyImageReferer:
    """測試 /api/proxy-image DMM 樣品圖像 Referer 設定"""

    @pytest.fixture(autouse=True)
    def _public_dns(self, public_resolver):
        """167 公網規則會解析 host；預設回公網，個別格自己覆寫成私網。"""
        self.resolve = public_resolver()

    def _make_mock_response(self, content=b'\xff\xd8\xff', content_type='image/jpeg'):
        """建立 mock requests.Response"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = content
        mock_resp.headers = {'Content-Type': content_type}
        return mock_resp

    def test_proxy_image_dmm_sample_referer(self, client):
        """`awsimgsrc.dmm.co.jp` URL 發送請求時 Referer 應為 https://www.dmm.co.jp/"""
        url = 'https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/adult/sone103/sone103jp-1.jpg'

        with patch('web.routers.search.requests.get', return_value=self._make_mock_response()) as mock_get:
            response = client.get('/api/proxy-image', params={'url': url})

        assert response.status_code == 200
        mock_get.assert_called_once()
        _, call_kwargs = mock_get.call_args
        headers_sent = call_kwargs.get('headers', {})
        assert headers_sent.get('Referer') == 'https://www.dmm.co.jp/', \
            f"Expected Referer 'https://www.dmm.co.jp/', got '{headers_sent.get('Referer')}'"


    def test_proxy_image_javbus_referer(self, client):
        """`javbus.com` URL 發送請求時 Referer 應為 https://www.javbus.com/"""
        url = 'https://www.javbus.com/pics/cover/abc.jpg'

        with patch('web.routers.search.requests.get', return_value=self._make_mock_response()) as mock_get:
            response = client.get('/api/proxy-image', params={'url': url})

        assert response.status_code == 200
        mock_get.assert_called_once()
        _, call_kwargs = mock_get.call_args
        headers_sent = call_kwargs.get('headers', {})
        assert headers_sent.get('Referer') == 'https://www.javbus.com/'

    def test_proxy_image_unlisted_public_domain_allowed(self, client):
        """名單外的公網 domain 照常代理（167 公網規則）→ 200，請求恰發出一次"""
        url = 'https://cdn.example.com/image.jpg'

        with patch('web.routers.search.requests.get', return_value=self._make_mock_response()) as mock_get:
            response = client.get('/api/proxy-image', params={'url': url})

        assert response.status_code == 200
        mock_get.assert_called_once()
        assert 'cdn.example.com' in self.resolve.calls


class TestProxyImageSSRF:
    """SSRF allowlist guard for /api/proxy-image"""

    @pytest.fixture(autouse=True)
    def _public_dns(self, public_resolver):
        """167 公網規則會解析 host；預設回公網，個別格自己覆寫成私網。"""
        self.resolve = public_resolver()

    def _make_mock_response(self, content=b'\xff\xd8\xff\xe0fake', content_type='image/jpeg'):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = content
        mock_resp.headers = {'Content-Type': content_type}
        return mock_resp

    # ---- SSRF block cases (5) ----

    def test_ssrf_internal_ip_blocked(self, client):
        """內網 IP 應被攔截 → 403，不發出 HTTP 請求"""
        url = 'http://192.168.1.1/admin'
        with patch('web.routers.search.requests.get') as mock_get:
            response = client.get('/api/proxy-image', params={'url': url})
        assert response.status_code == 403
        mock_get.assert_not_called()

    def test_ssrf_localhost_blocked(self, client):
        """localhost 應被攔截 → 403，不發出 HTTP 請求"""
        url = 'http://127.0.0.1/'
        with patch('web.routers.search.requests.get') as mock_get:
            response = client.get('/api/proxy-image', params={'url': url})
        assert response.status_code == 403
        mock_get.assert_not_called()

    def test_ssrf_cloud_metadata_blocked(self, client):
        """cloud metadata endpoint 應被攔截 → 403，不發出 HTTP 請求"""
        url = 'http://169.254.169.254/latest/meta-data/'
        with patch('web.routers.search.requests.get') as mock_get:
            response = client.get('/api/proxy-image', params={'url': url})
        assert response.status_code == 403
        mock_get.assert_not_called()


    # ---- Scraper real-host allow cases (2) ----


    # ---- Actress cascade host allow cases (4) ----


    # ---- 無碼來源圖床 allow cases (FC2 / AVSOX，實機驗證真實 host) ----


    # ---- Exact-host subdomain blocked (1) ----


    # ---- TASK-113c-T2: redirect 不跟隨 ＋ 403 log ----

    def test_ssrf_redirect_not_followed(self, client, caplog):
        """白名單內 host 回 302 指向內網 → 不跟隨、回非 200，且 get 帶 allow_redirects=False"""
        url = 'https://pics.dmm.co.jp/mono/movie/adult/sone103/sone103pl.jpg'
        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_resp.content = b''
        mock_resp.headers = {'Location': 'http://127.0.0.1/evil', 'Content-Type': 'text/html'}

        with caplog.at_level(logging.WARNING, logger='OpenAver.web.routers.search'):
            with patch(
                'web.routers.search.requests.get', return_value=mock_resp
            ) as mock_get:
                response = client.get('/api/proxy-image', params={'url': url})

        assert response.status_code != 200
        mock_get.assert_called_once_with(
            url, headers=ANY, timeout=10, allow_redirects=False
        )
        # 3xx 分支獨立 log：原始 host、status、Location host-only
        assert any(
            'pics.dmm.co.jp' in r.getMessage()
            and '302' in r.getMessage()
            and '127.0.0.1' in r.getMessage()
            for r in caplog.records
        ), f"expected 3xx warning with host/status/Location host, got: {caplog.text!r}"
        # MUST NOT：完整 Location URL（含 path）
        assert 'http://127.0.0.1/evil' not in caplog.text

    def test_ssrf_403_logs_host_without_query(self, client, caplog, public_resolver):
        """403 拒絕路徑記 host/scheme/原因，且不洩漏 query 中的 token"""
        url = 'https://evil.com/image.jpg?token=secret123'
        # 167：拒絕原因改為「解析成私網」；resolver 把 evil.com 指到 10.0.0.5
        resolve = public_resolver({'evil.com': ['10.0.0.5']})

        with caplog.at_level(logging.WARNING, logger='OpenAver.web.routers.search'):
            with patch('web.routers.search.requests.get') as mock_get:
                response = client.get('/api/proxy-image', params={'url': url})

        assert response.status_code == 403
        mock_get.assert_not_called()
        assert any(
            'evil.com' in r.getMessage()
            and '非公網目標' in r.getMessage()
            for r in caplog.records
        ), f"expected 403 warning with host + reason, got: {caplog.text!r}"
        assert 'evil.com' in resolve.calls
        assert 'secret123' not in caplog.text

    # ---- 167-T3 I1b: 使用者設了外部 proxy，公網檢查仍照做 ----

    _PROXY = {"proxies": {"http": "http://p:1", "https": "http://p:1"}}

    def test_proxy_configured_private_resolution_still_denied(self, client, public_resolver):
        """設了 proxy 後，站方把圖片 host 指到內網仍 403，且不發請求"""
        resolve = public_resolver({'cdn.example.com': ['10.0.0.5']})
        with patch('web.routers.search.proxy_kwargs', return_value=self._PROXY):
            with patch('web.routers.search.requests.get') as mock_get:
                response = client.get(
                    '/api/proxy-image', params={'url': 'https://cdn.example.com/c.jpg'})
        assert response.status_code == 403
        mock_get.assert_not_called()
        assert 'cdn.example.com' in resolve.calls

    def test_proxy_configured_public_resolution_allowed(self, client, public_resolver):
        """對照格：設了 proxy 且解析成公網 → 200，requests.get 收到 proxies"""
        public_resolver({'cdn.example.com': ['8.8.8.8']})
        with patch('web.routers.search.proxy_kwargs', return_value=self._PROXY):
            with patch('web.routers.search.requests.get',
                       return_value=self._make_mock_response()) as mock_get:
                response = client.get(
                    '/api/proxy-image', params={'url': 'https://cdn.example.com/c.jpg'})
        assert response.status_code == 200
        assert mock_get.call_args.kwargs['proxies'] == self._PROXY['proxies']

    # ---- TASK-113c-T3a: metatube dynamic + path/dot-segment + cf.javfree.me ----


    def test_metatube_dot_segment_literal_dotdot_rejected(self, client):
        """§1.7(a) row1: /v1/images/../db → 403, no request."""
        from core.metatube.state import metatube_state
        metatube_state.connect('http://127.0.0.1:8900', '', [])
        try:
            url = 'http://127.0.0.1:8900/v1/images/../db'
            with patch('web.routers.search.requests.get') as mock_get:
                response = client.get('/api/proxy-image', params={'url': url})
            assert response.status_code == 403
            mock_get.assert_not_called()
        finally:
            metatube_state.disconnect()


    def test_metatube_non_images_path_rejected(self, client):
        """AC5b: connected metatube /v1/db/version → 403 (path_prefix)."""
        from core.metatube.state import metatube_state
        metatube_state.connect('http://127.0.0.1:8900', '', [])
        try:
            url = 'http://127.0.0.1:8900/v1/db/version'
            with patch('web.routers.search.requests.get') as mock_get:
                response = client.get('/api/proxy-image', params={'url': url})
            assert response.status_code == 403
            mock_get.assert_not_called()
        finally:
            metatube_state.disconnect()

    def test_metatube_same_host_different_port_rejected(self, client):
        """裁決 1: connected :8900, request :6379/v1/images/... → 403."""
        from core.metatube.state import metatube_state
        metatube_state.connect('http://127.0.0.1:8900', '', [])
        try:
            url = 'http://127.0.0.1:6379/v1/images/primary/x/y'
            with patch('web.routers.search.requests.get') as mock_get:
                response = client.get('/api/proxy-image', params={'url': url})
            assert response.status_code == 403
            mock_get.assert_not_called()
        finally:
            metatube_state.disconnect()

    def test_proxy_image_exception_log_does_not_leak_query_or_userinfo(self, client, caplog):
        """例外路徑的 log 不得記完整 URL（Codex PR review P1 的相鄰洩漏點）。

        CD-113c-8 的理由是「圖片 URL 常帶簽名／token」，T2 據此讓 403 與 3xx 兩條
        路徑只記 host。但同一個函式的 `except` 分支原本是
        `logger.exception("proxy_image failed: %s", url)`——記的是**完整 url**，
        含 query 的 token；T3b 之後 metatube base_url 的 userinfo 也會流經這裡。
        現在改記 host + path。
        """
        url = 'https://pics.dmm.co.jp/mono/movie/x/xpl.jpg?token=secret123&sig=abc'
        with caplog.at_level(logging.ERROR, logger='OpenAver.web.routers.search'):
            with patch('web.routers.search.requests.get',
                       side_effect=RuntimeError('boom')):
                response = client.get('/api/proxy-image', params={'url': url})

        assert response.status_code == 404
        assert 'secret123' not in caplog.text
        assert 'sig=abc' not in caplog.text
        # 仍保留診斷價值：host 與 path 要記得到
        assert 'pics.dmm.co.jp' in caplog.text
        assert '/mono/movie/x/xpl.jpg' in caplog.text

    @pytest.mark.parametrize("evil_path", [
        '/v1/images/%252e%252e/db',       # 雙重百分比編碼
        '/v1/images/..;/db',              # matrix parameter（Tomcat 類）
        '/v1/images//x',                  # 空段
    ])
    def test_metatube_path_allowlist_blocks_exotic_encodings(self, client, evil_path):
        """path 閘門是**正向字元允許清單**，不是列舉違規編碼。

        來歷：T3a review 對「列舉 `%2e`/`%2f` 解碼後比對 `.`／`..`」那一版打穿
        五種（雙重編碼 / overlong UTF-8 ×2 / matrix parameter / NUL），每種都
        route-level 實測回 200 並把 payload 原樣送上 wire。改成 `[A-Za-z0-9._~-]+`
        正向清單後，`%` 根本不在字元集裡——所有百分比編碼把戲在解碼前就出局，
        不必猜對面伺服器怎麼正規化（CD-113c-11「無法判定一律 fail-closed」）。
        """
        from core.metatube.state import metatube_state
        metatube_state.connect('http://127.0.0.1:8900', '', [])
        try:
            url = f'http://127.0.0.1:8900{evil_path}'
            with patch('web.routers.search.requests.get') as mock_get:
                response = client.get('/api/proxy-image', params={'url': url})
            assert response.status_code == 403
            mock_get.assert_not_called()
        finally:
            metatube_state.disconnect()

    # ---- Codex PR#128 round-2 P3：巢狀抓取目標 ----

    @pytest.mark.parametrize("nested", [
        'http://127.0.0.1:6379/',                       # 同機 Redis
        'http://nas/photo.jpg',                         # 裸內網名
    ])
    def test_metatube_nested_url_to_private_target_is_rejected(self, client, nested):
        """path 過關的 metatube URL，若 `?url=` 指向非公開位址 → 403，且不發請求。

        metatube 的 `/v1/images/` 端點會**自己去抓** `?url=` 那個目標，外層白名單
        看不到那一層——與 T2 修 redirect 的理由同一條。被橋接的具體情境是
        「metatube 綁 loopback ＋ OpenAver 開區網」：此時區網客戶端能透過我們
        構到只有本機構得到的服務。

        `mock_get.assert_not_called()` 是重點：必須在**發出請求之前**就拒絕。
        """
        from urllib.parse import quote
        from core.metatube.state import metatube_state
        metatube_state.connect('http://127.0.0.1:8900', '', [])
        try:
            url = (f'http://127.0.0.1:8900/v1/images/primary/FANZA/ssis-001'
                   f'?url={quote(nested, safe="")}&ratio=0&quality=100')
            with patch('web.routers.search.requests.get') as mock_get:
                response = client.get('/api/proxy-image', params={'url': url})
            assert response.status_code == 403
            mock_get.assert_not_called()
        finally:
            metatube_state.disconnect()

    def test_metatube_nested_url_to_public_cdn_is_permitted(self, client):
        """正向對照：巢狀目標是公開圖床時必須放行——否則破圖修復本身就失效了。

        沒有這一格，上面那組「全部 403」用一個 `return False` 就能造假。
        用的是實跑 metatube 產出的真實 provider 圖床 URL。
        """
        from urllib.parse import quote
        from core.metatube.state import metatube_state
        metatube_state.connect('http://127.0.0.1:8900', '', [])
        try:
            nested = 'https://my.cdn.tokyo-hot.com/media/n1749/jacket/n1749.jpg'
            url = (f'http://127.0.0.1:8900/v1/images/primary/TOKYO-HOT/n1749'
                   f'?url={quote(nested, safe="")}&ratio=0&quality=100')
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'\xff\xd8\xffx'
            mock_resp.headers = {'Content-Type': 'image/jpeg'}
            with patch('web.routers.search.requests.get', return_value=mock_resp):
                response = client.get('/api/proxy-image', params={'url': url})
            assert response.status_code == 200
        finally:
            metatube_state.disconnect()

    @pytest.mark.parametrize("good_path", [
        '/v1/images/backdrop/P_v2/abc_123.jpg',
    ])
    def test_metatube_path_allowlist_permits_real_image_paths(self, client, good_path):
        """正向對照：允許清單不能嚴到把真實的 metatube 圖片路徑也擋掉。

        沒有這一組，上面那組「全部 403」用一個 `return False` 就能造假。
        """
        from core.metatube.state import metatube_state
        metatube_state.connect('http://127.0.0.1:8900', '', [])
        try:
            url = f'http://127.0.0.1:8900{good_path}'
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'\xff\xd8\xffx'
            mock_resp.headers = {'Content-Type': 'image/jpeg'}
            with patch('web.routers.search.requests.get', return_value=mock_resp):
                response = client.get('/api/proxy-image', params={'url': url})
            assert response.status_code == 200
        finally:
            metatube_state.disconnect()


    def test_metatube_images_path_allowed(self, client):
        """Connected metatube /v1/images/... matching host+port+scheme → 200."""
        from core.metatube.state import metatube_state
        metatube_state.connect('http://127.0.0.1:8900', '', [])
        try:
            url = 'http://127.0.0.1:8900/v1/images/primary/x/y'
            with patch(
                'web.routers.search.requests.get',
                return_value=self._make_mock_response(),
            ) as mock_get:
                response = client.get('/api/proxy-image', params={'url': url})
            assert response.status_code == 200
            mock_get.assert_called_once()
        finally:
            metatube_state.disconnect()


# ============ since 日期過濾 ============

class TestSearchSince:
    """測試 GET /api/search?since=YYYY-MM-DD 日期後過濾"""


    def test_since_filters_old_results(self, client, mocker):
        """since=2026-01-01 應過濾 date < 2026-01-01 的結果"""
        mock_results = [
            {'number': 'SONE-100', 'title': 'Old', 'date': '2025-12-31'},
            {'number': 'SONE-101', 'title': 'New', 'date': '2026-01-15'},
        ]
        mocker.patch('web.routers.search.smart_search', return_value=mock_results)

        response = client.get('/api/search', params={'q': 'SONE', 'since': '2026-01-01'})
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        numbers = [r['number'] for r in data['data']]
        assert 'SONE-101' in numbers
        assert 'SONE-100' not in numbers


# ============ discovery 參數 ============

class TestSearchDiscovery:
    """測試 GET /api/search?discovery=true"""

    def test_discovery_true_sets_flag_in_response(self, client, mocker):
        """discovery=true 時回傳包含 discovery: true"""
        mocker.patch('web.routers.search.search_actress', return_value=[
            {'number': 'SONE-100', 'title': ''}
        ])
        response = client.get('/api/search', params={'q': '三上悠亜', 'mode': 'actress', 'discovery': 'true'})
        assert response.status_code == 200
        data = response.json()
        assert data.get('discovery') is True


# ============ POST /api/batch-search ============

class TestBatchSearch:
    """測試 POST /api/batch-search"""


    def test_batch_search_found_and_not_found(self, client, mocker):
        """1 found + 1 not found → results + summary 正確"""
        def mock_smart_search(q, limit=1, **kwargs):
            if q == 'SONE-205':
                return [{'number': 'SONE-205', 'title': 'Found Title', 'cover_url': 'http://example.com/cover.jpg'}]
            return []

        mocker.patch('web.routers.search.smart_search', side_effect=mock_smart_search)

        response = client.post('/api/batch-search', json={'numbers': ['SONE-205', 'FAKE-999']})
        assert response.status_code == 200
        data = response.json()

        assert 'results' in data
        assert 'summary' in data
        assert data['results']['SONE-205']['found'] is True
        assert 'title' in data['results']['SONE-205']
        assert data['results']['FAKE-999']['found'] is False
        assert data['summary']['total'] == 2
        assert data['summary']['found'] == 1
        assert data['summary']['not_found'] == 1

    def test_batch_search_include_covers_false_removes_cover_url(self, client, mocker):
        """include_covers=false 從結果刪除 cover_url"""
        def mock_smart_search(q, limit=1, **kwargs):
            return [{'number': q, 'title': 'Title', 'cover_url': 'http://example.com/cover.jpg'}]

        mocker.patch('web.routers.search.smart_search', side_effect=mock_smart_search)

        response = client.post('/api/batch-search', json={
            'numbers': ['SONE-100'],
            'include_covers': False
        })
        assert response.status_code == 200
        data = response.json()
        assert 'cover_url' not in data['results']['SONE-100']

    def test_batch_search_include_covers_true_keeps_cover_url(self, client, mocker):
        """include_covers=true（預設）保留 cover_url"""
        def mock_smart_search(q, limit=1, **kwargs):
            return [{'number': q, 'title': 'Title', 'cover_url': 'http://example.com/cover.jpg'}]

        mocker.patch('web.routers.search.smart_search', side_effect=mock_smart_search)

        response = client.post('/api/batch-search', json={'numbers': ['SONE-100']})
        assert response.status_code == 200
        data = response.json()
        assert 'cover_url' in data['results']['SONE-100']


class TestAutoOrganizeHooks:
    """DoD-6: 驗證三個掛載點對 auto_organize_state 的分工與呼叫。"""

    def test_favorite_files_marks_activity_and_requests_abort(self, client, mocker):
        """GET /api/search/favorite-files 兩支都打：mark_manual_activity 與 request_abort。"""
        from web.routers import search as search_module
        spy_mark = mocker.spy(search_module, "mark_manual_activity")
        spy_abort = mocker.spy(search_module, "request_abort")

        client.get("/api/search/favorite-files")

        assert spy_mark.call_count == 1
        assert spy_abort.call_count == 1

    def test_search_stream_only_marks_activity(self, client, mocker):
        """GET /api/search/stream 只打 mark_manual_activity，絕不呼叫 request_abort。"""
        from web.routers import search as search_module
        spy_mark = mocker.spy(search_module, "mark_manual_activity")
        spy_abort = mocker.spy(search_module, "request_abort")
        mocker.patch.object(search_module, "smart_search", return_value=[])

        client.get("/api/search/stream?q=AB")

        assert spy_mark.call_count == 1
        assert spy_abort.call_count == 0

    def test_scrape_single_only_marks_activity(self, client, mocker):
        """POST /api/scrape-single 只打 mark_manual_activity，絕不呼叫 request_abort。"""
        from web.routers import scraper as scraper_module
        spy_mark = mocker.spy(scraper_module.auto_organize_state, "mark_manual_activity")
        spy_abort = mocker.spy(scraper_module.auto_organize_state, "request_abort")
        mocker.patch.object(scraper_module, "smart_search", return_value=[])

        client.post(
            "/api/scrape-single",
            json={"file_path": "/nonexistent/test.mp4", "number": "ABC-123"},
        )

        assert spy_mark.call_count == 1
        assert spy_abort.call_count == 0


# ============ TASK-144-T5：auto-organize 三端點 ＋ lifespan ============

class TestAutoOrganizeEndpoints:
    """TASK-144-T5：config / use-resolved-folder / run-now 與 lifespan 接線。"""

    @pytest.fixture(autouse=True)
    def _reset_auto_organize_state(self):
        """每支測試前後把 module-level 狀態清乾淨。

        本檔前面的測試會打 `/api/search/*` 端點，而那些端點（T4a）會呼叫
        `mark_manual_activity()` 把 `_last_manual_at` 設成「剛剛」——
        `enter_cron('schedule')` 因此會正確地讓路而回 `False`。
        那是產品**正確**的行為，不該讓它污染本 class 的前置條件。
        """
        from core import auto_organize_state
        auto_organize_state.exit_cron()
        auto_organize_state._last_manual_at = float("-inf")
        yield
        auto_organize_state.exit_cron()
        auto_organize_state._last_manual_at = float("-inf")

    def test_auto_organize_config_requires_favorite_folder(self, client):
        """DoD-12：favorite_folder 空時只允許寫 False。"""
        from core import config as core_config
        core_config.mutate_config(
            lambda cfg: cfg.setdefault("search", {}).update({"favorite_folder": ""})
        )

        resp = client.post("/api/search/auto-organize/config", json={"enabled": True})
        assert resp.status_code == 200
        assert resp.json() == {"success": False, "error": "favorite_folder_unset"}

        resp_off = client.post("/api/search/auto-organize/config", json={"enabled": False})
        assert resp_off.status_code == 200
        assert resp_off.json() == {"success": True}


    def test_disabling_toggle_aborts_running_round(self, client):
        """Codex PR#181 之後的最壞情況盤點 R1：撥掉開關＝叫停正在跑的那一輪。

        使用者流程：打開「定時整理」面板 → 看到「目前正在執行一輪」、覺得不對勁把開關
        撥掉 → 修正前那一輪**繼續搬檔改名到跑完為止**（最愛資料夾 1965 個檔的第一輪是
        數小時等級）。面板上沒有停止鈕，`request_abort()` 全庫唯一的呼叫點是「我的最愛」
        按鈕，所以使用者唯一的脫身方式是關掉整個 App。
        """
        from core import auto_organize_state
        from core import config as core_config

        core_config.mutate_config(
            lambda cfg: cfg.setdefault("search", {}).update(
                {"favorite_folder": "/tmp/fav-for-ao"}
            )
        )

        assert auto_organize_state.enter_cron("run_now") is True
        try:
            assert auto_organize_state.should_abort() is False

            resp = client.post("/api/search/auto-organize/config", json={"enabled": False})
            assert resp.status_code == 200
            assert resp.json() == {"success": True}
            assert auto_organize_state.should_abort() is True, (
                "撥掉開關之後那一輪還在搬檔改名，而畫面上沒有任何其他停止入口"
            )
        finally:
            auto_organize_state.exit_cron()

    def test_enabling_toggle_does_not_abort(self, client):
        """反向鎖：撥「開」不得設中止旗標（否則剛開的排程立刻自廢）。"""
        from core import auto_organize_state
        from core import config as core_config

        core_config.mutate_config(
            lambda cfg: cfg.setdefault("search", {}).update(
                {"favorite_folder": "/tmp/fav-for-ao"}
            )
        )

        assert auto_organize_state.enter_cron("run_now") is True
        try:
            resp = client.post("/api/search/auto-organize/config", json={"enabled": True})
            assert resp.status_code == 200
            assert auto_organize_state.should_abort() is False
        finally:
            auto_organize_state.exit_cron()


    # [lint-guard: pytest-justified] 模板 x-show 與 autoOrganizePanel() 欄位名的跨檔 Alpine state 契約＋i18n 文字

    def test_use_resolved_folder_unset_non_desktop_returns_error_and_does_not_write_config(
        self, client, monkeypatch
    ):
        from core import config as core_config

        monkeypatch.delenv("OPENAVER_STANDALONE", raising=False)
        core_config.mutate_config(
            lambda cfg: cfg.setdefault("search", {}).update({"favorite_folder": ""})
        )
        before = core_config.CONFIG_PATH.read_bytes()

        response = client.post("/api/search/auto-organize/use-resolved-folder")

        assert response.status_code == 200
        assert response.json() == {"success": False, "error": "favorite_folder_unset"}
        assert core_config.CONFIG_PATH.read_bytes() == before
        assert core_config.load_config()["search"]["favorite_folder"] == ""

    def test_run_now_returns_immediately_even_when_round_is_slow(
        self, client, mocker, tmp_path
    ):
        """DoD-2 / M4：run-now 毫秒返回，絕不 await 整輪。"""
        import time
        from core import config as core_config
        from core import auto_organize_state

        fav = tmp_path / "ao-fav"
        fav.mkdir()
        core_config.mutate_config(
            lambda cfg: cfg.setdefault("search", {}).update(
                {"favorite_folder": str(fav)}
            )
        )

        def slow_round(*_a, **_k):
            time.sleep(2.0)
            return {
                "added": [],
                "cover_missing": [],
                "failed": [],
                "skipped": {"has_nfo": 0, "memory_hit": 0, "duplicate": []},
                "newly_recorded": 0,
                "wishlist_removed": [],
                "aborted_after": None,
            }

        mocker.patch("web.auto_organize_scheduler.run_one_round", side_effect=slow_round)
        mocker.patch("web.auto_organize_scheduler.emit_notification")

        # 清掉可能殘留的 running
        auto_organize_state.exit_cron()

        t0 = time.perf_counter()
        resp = client.post("/api/search/auto-organize/run-now")
        elapsed = time.perf_counter() - t0

        assert resp.status_code == 200
        assert resp.json() == {"success": True, "reason": None}
        assert elapsed < 0.5, f"run-now took {elapsed:.3f}s — must not await the round"

        # 等背景輪結束，避免污染後續測試
        from web import auto_organize_scheduler as aos
        if aos._round_task is not None:
            # 🔴 不可用 `aos._round_task.result(timeout=5)`：`asyncio.Task.result()`
            # **不接受 timeout 參數**（那是 `concurrent.futures.Future` 的簽名），
            # 會立刻拋 TypeError 並被 `except` 吞掉 ⇒ 這段「等背景輪結束」完全沒有生效
            # （PR review 實測指出）。直接取消即可：這裡要的只是不要把背景輪留給下一支測試。
            aos._round_task.cancel()
            auto_organize_state.exit_cron()

    def test_run_now_already_running_reason(self, client):
        """DoD-2：另一輪在跑 → already_running。"""
        from core import auto_organize_state

        # 用 run_now 佔住「正在跑」這個位子：它不讀 _last_manual_at，
        # 不會因為同檔前面的測試打過端點而被讓路擋掉。
        assert auto_organize_state.enter_cron("run_now") is True
        try:
            resp = client.post("/api/search/auto-organize/run-now")
            assert resp.status_code == 200
            assert resp.json() == {"success": False, "reason": "already_running"}
        finally:
            auto_organize_state.exit_cron()

    def test_lifespan_starts_auto_organize_task(self, tmp_path, monkeypatch):
        """DoD-13 / M8：lifespan 掛 auto_organize_task 強引用。"""
        import asyncio
        from fastapi.testclient import TestClient
        from web.app import app

        monkeypatch.setattr(
            "core.database.connection.get_db_path", lambda: tmp_path / "app.db"
        )
        monkeypatch.setattr(
            "core.access_auth.get_db_path", lambda: tmp_path / "access.db"
        )

        async def hang_forever():
            await asyncio.Event().wait()

        with patch("web.app.auto_organize_loop", hang_forever), \
             patch("web.app.backfill_readonly_nfo_mtime_once", return_value=None), \
             patch("web.app.startup_reconnect", return_value=None), \
             patch("web.app.source_reachability") as mock_sr:
            mock_sr.schedule_reprobe_if_stale = AsyncMock(return_value=None)
            with TestClient(app) as _client:
                task = getattr(app.state, "auto_organize_task", None)
                assert task is not None, "lifespan must create auto_organize_task"
                assert not task.done()
