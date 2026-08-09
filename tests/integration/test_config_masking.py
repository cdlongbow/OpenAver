"""Integration tests for GET /api/config secret masking (TASK-114c-T1).

AC7 full-body leak check, AC8 field parity, and url/proxy_url passthrough
(B15–B17). Permission tests (B19/B20) live in tests/unit/test_core_config.py
per owner correction (function-layer chmod; same fixture style as
test_copies_default_when_default_exists).
"""

import copy
import json

from core.config import load_config, save_config
from core.secret_fields import mask_secret


SECRET_PLAIN = "sk-test-roundtrip"
TOKEN_PLAIN = "mt-token-secret-xyz9"
METATUBE_URL_WITH_USERINFO = "http://user:pass@192.168.1.177:8080"
PROXY_URL_WITH_USERINFO = "http://proxy-user:proxy-pass@proxy.example:8080"


def _seed_secrets(client) -> dict:
    """Write non-empty secrets (+ userinfo urls) via load/save, return baseline."""
    cfg = load_config()
    cfg.setdefault("translate", {}).setdefault("openai", {})["api_key"] = SECRET_PLAIN
    cfg.setdefault("translate", {}).setdefault("gemini", {})["api_key"] = SECRET_PLAIN
    cfg.setdefault("metatube", {})["token"] = TOKEN_PLAIN
    cfg.setdefault("metatube", {})["url"] = METATUBE_URL_WITH_USERINFO
    cfg.setdefault("search", {})["proxy_url"] = PROXY_URL_WITH_USERINFO
    save_config(cfg)
    return load_config()


class TestAC7FullBodyMasking:
    """B15: plaintext secrets must not appear anywhere in GET /api/config body."""

    def test_plaintext_not_in_serialized_body(self, client, temp_config_path):
        _seed_secrets(client)

        response = client.get("/api/config")
        assert response.status_code == 200
        body = response.text
        # Full-body serialization check (not path-based).
        assert SECRET_PLAIN not in body
        assert TOKEN_PLAIN not in body

        # Also check json.dumps form (ensure_ascii=False) matches spirit of AC7.
        dumped = json.dumps(response.json(), ensure_ascii=False)
        assert SECRET_PLAIN not in dumped
        assert TOKEN_PLAIN not in dumped

        data = response.json()["data"]
        assert data["translate"]["openai"]["api_key"] == mask_secret(SECRET_PLAIN)
        assert data["translate"]["gemini"]["api_key"] == mask_secret(SECRET_PLAIN)
        assert data["metatube"]["token"] == mask_secret(TOKEN_PLAIN)


class TestAC8FieldParity:
    """B16: every field except the three SECRET_FIELDS paths equals baseline."""

    def test_non_secret_fields_match_baseline(self, client, temp_config_path):
        baseline = _seed_secrets(client)

        response = client.get("/api/config")
        assert response.status_code == 200
        masked = response.json()["data"]

        restored = copy.deepcopy(masked)
        restored["translate"]["openai"]["api_key"] = baseline["translate"]["openai"]["api_key"]
        restored["translate"]["gemini"]["api_key"] = baseline["translate"]["gemini"]["api_key"]
        restored["metatube"]["token"] = baseline["metatube"]["token"]
        assert restored == baseline

        # Positive shape checks for the three secret paths.
        assert masked["translate"]["openai"]["api_key"] == mask_secret(SECRET_PLAIN)
        assert masked["translate"]["gemini"]["api_key"] == mask_secret(SECRET_PLAIN)
        assert masked["metatube"]["token"] == mask_secret(TOKEN_PLAIN)


class TestUrlProxyPassthrough:
    """B17: metatube.url / search.proxy_url with userinfo pass through byte-identical."""

    def test_url_and_proxy_url_unmasked(self, client, temp_config_path):
        baseline = _seed_secrets(client)

        response = client.get("/api/config")
        assert response.status_code == 200
        masked = response.json()["data"]

        assert masked["metatube"]["url"] == baseline["metatube"]["url"]
        assert masked["metatube"]["url"] == METATUBE_URL_WITH_USERINFO
        assert masked["search"]["proxy_url"] == baseline["search"]["proxy_url"]
        assert masked["search"]["proxy_url"] == PROXY_URL_WITH_USERINFO
