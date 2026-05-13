"""
Integration tests for GET /api/settings/favorite-scanner-link
使用 FastAPI TestClient，mock config 讀取。
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────
# App fixture
# ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from web.app import app
    return TestClient(app)


# ─────────────────────────────────────────────
# Case 1: empty favorite → linked=false immediately
# ─────────────────────────────────────────────

class TestEmptyFavoriteEndpoint:
    def test_empty_favorite_returns_not_linked(self, client):
        resp = client.get('/api/settings/favorite-scanner-link', params={'favorite': ''})
        assert resp.status_code == 200
        data = resp.json()
        assert data['linked'] is False
        assert data['matched_directory'] is None

    def test_missing_favorite_param(self, client):
        """favorite 未傳 → 等同空字串（或 422）"""
        resp = client.get('/api/settings/favorite-scanner-link')
        # 允許 200(不連動) 或 422(驗證錯誤)
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            assert resp.json()['linked'] is False


# ─────────────────────────────────────────────
# Case 2: favorite 在 directory 內 → linked=true
# ─────────────────────────────────────────────

MOCK_CONFIG = {
    'gallery': {
        'directories': ['/mnt/e/media', '/mnt/f/videos'],
        'path_mappings': {}
    }
}


class TestLinkedEndpoint:
    def test_exact_match_linked(self, client):
        with patch('web.routers.settings_link.load_config', return_value=MOCK_CONFIG), \
             patch('web.routers.settings_link.find_matched_directory',
                   return_value='/mnt/e/media') as mock_fmd:
            resp = client.get(
                '/api/settings/favorite-scanner-link',
                params={'favorite': '/mnt/e/media'}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data['linked'] is True
        assert data['matched_directory'] == '/mnt/e/media'

    def test_subdirectory_linked(self, client):
        with patch('web.routers.settings_link.load_config', return_value=MOCK_CONFIG), \
             patch('web.routers.settings_link.find_matched_directory',
                   return_value='/mnt/e/media'):
            resp = client.get(
                '/api/settings/favorite-scanner-link',
                params={'favorite': '/mnt/e/media/jav'}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data['linked'] is True
        assert data['matched_directory'] == '/mnt/e/media'


# ─────────────────────────────────────────────
# Case 3: favorite 不在任何 directory → linked=false
# ─────────────────────────────────────────────

class TestNotLinkedEndpoint:
    def test_not_in_any_directory(self, client):
        with patch('web.routers.settings_link.load_config', return_value=MOCK_CONFIG), \
             patch('web.routers.settings_link.find_matched_directory',
                   return_value=None):
            resp = client.get(
                '/api/settings/favorite-scanner-link',
                params={'favorite': '/mnt/g/other'}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data['linked'] is False
        assert data['matched_directory'] is None


# ─────────────────────────────────────────────
# Case 4: router 已 include（端點存在）
# ─────────────────────────────────────────────

class TestRouterIncluded:
    def test_route_exists_not_404(self, client):
        """驗證 router 已 include 到 app — 不應 404"""
        resp = client.get(
            '/api/settings/favorite-scanner-link',
            params={'favorite': ''}
        )
        assert resp.status_code != 404, \
            "Router 未 include：GET /api/settings/favorite-scanner-link 回 404"

    def test_response_shape(self, client):
        """回傳 shape 必須有 linked + matched_directory 兩個 key"""
        resp = client.get(
            '/api/settings/favorite-scanner-link',
            params={'favorite': ''}
        )
        if resp.status_code == 200:
            data = resp.json()
            assert 'linked' in data
            assert 'matched_directory' in data
