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


# ─────────────────────────────────────────────
# Case 3: favorite 不在任何 directory → linked=false
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# Case 4: router 已 include（端點存在）
# ─────────────────────────────────────────────

