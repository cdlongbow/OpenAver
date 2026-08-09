"""Unit tests for core.secret_fields (TASK-114c-T1).

Covers mask_secret truth table, resolve_secret three-states, read_secret,
render_config_secrets deep-copy, and SECRET_FIELDS inventory (B1–B12, B14).
"""

import copy

import pytest

from core.secret_fields import (
    SECRET_FIELDS,
    mask_secret,
    read_secret,
    render_config_secrets,
    resolve_secret,
)

BULLET = "\u2022"
MASK4 = BULLET * 4


# ============ B1–B5: mask_secret truth table ============

class TestMaskSecret:
    def test_empty_string_unmasked(self):
        """B1: empty string is not masked — UI must distinguish unset vs set."""
        assert mask_secret("") == ""

    def test_len_le_4_fully_masked(self):
        """B2: length ≤ 4 → fully masked, no length leak."""
        assert mask_secret("ab") == MASK4
        assert mask_secret("abcd") == MASK4

    def test_len_exactly_4_fully_masked(self):
        """B2 boundary: len == 4 is fully masked, not MASK4 + value."""
        assert mask_secret("abcd") == MASK4
        assert mask_secret("abcd") != MASK4 + "abcd"

    def test_len_5_keeps_last_four(self):
        """B3: len 5 → MASK4 + last 4 chars."""
        assert mask_secret("abcde") == MASK4 + "bcde"

    def test_canonical_roundtrip_example(self):
        """B4: product canonical example."""
        assert mask_secret("sk-test-roundtrip") == MASK4 + "trip"

    def test_mask_chars_are_u2022_bullet(self):
        """B5: mask characters must be U+2022, not ASCII * or U+25CF."""
        out = mask_secret("ab")
        assert len(out) == 4
        assert all(c == BULLET for c in out)
        assert "*" not in out
        assert "\u25cf" not in out

        out_long = mask_secret("sk-test-roundtrip")
        assert all(c == BULLET for c in out_long[:4])


# ============ B6–B9: resolve_secret three-states ============

class TestResolveSecret:
    def test_unchanged_sentinel_keeps_stored(self):
        """B6: incoming == mask(stored) → keep stored (user didn't touch)."""
        stored = "sk-test-roundtrip"
        incoming = mask_secret(stored)
        assert resolve_secret(incoming, stored) == stored

    def test_new_value_adopted(self):
        """B7: new plaintext → adopt incoming."""
        stored = "sk-test-roundtrip"
        assert resolve_secret("sk-new-key-9999", stored) == "sk-new-key-9999"

    def test_clear_field(self):
        """B8: empty incoming with non-empty stored → clear."""
        assert resolve_secret("", "sk-test-roundtrip") == ""

    def test_empty_plus_empty(self):
        """B9: both empty → empty (mask("") == "" so sentinel matches)."""
        assert resolve_secret("", "") == ""


# ============ B10: read_secret ============

class TestReadSecret:
    def test_missing_path_returns_empty(self):
        """B10: missing terminal key → \"\"."""
        assert read_secret({}, "translate.openai.api_key") == ""

    def test_missing_intermediate_returns_empty(self):
        """B10: missing intermediate node → \"\"."""
        assert read_secret({"translate": {}}, "translate.openai.api_key") == ""

    def test_reads_existing_value(self):
        cfg = {
            "translate": {
                "openai": {"api_key": "sk-test-roundtrip"},
            }
        }
        assert read_secret(cfg, "translate.openai.api_key") == "sk-test-roundtrip"

    def test_non_str_returns_empty(self):
        """Non-str terminal value is treated as no secret → \"\"."""
        cfg = {"metatube": {"token": 12345}}
        assert read_secret(cfg, "metatube.token") == ""

    def test_none_terminal_returns_empty(self):
        cfg = {"metatube": {"token": None}}
        assert read_secret(cfg, "metatube.token") == ""


# ============ B11–B12: render_config_secrets ============

def _sample_cfg() -> dict:
    return {
        "translate": {
            "enabled": True,
            "provider": "openai",
            "gemini": {"api_key": "sk-test-roundtrip", "model": "gemini-flash-lite-latest"},
            "openai": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test-roundtrip",
                "model": "gpt-4o",
            },
        },
        "metatube": {
            "enabled": True,
            "url": "http://user:pass@192.168.1.177:8080",
            "token": "mt-secret-token-xyz",
            "allow_lan": False,
        },
        "search": {
            "proxy_url": "http://proxy-user:proxy-pass@proxy.example:8080",
        },
        "general": {"theme": "dark"},
        "gallery": {"directories": []},
    }


class TestRenderConfigSecrets:
    def test_does_not_mutate_input(self):
        """B11: deep-copy — original dict remains plaintext after call."""
        cfg = _sample_cfg()
        original_openai = cfg["translate"]["openai"]["api_key"]
        original_gemini = cfg["translate"]["gemini"]["api_key"]
        original_token = cfg["metatube"]["token"]
        cfg_id = id(cfg)

        rendered = render_config_secrets(cfg)

        assert id(rendered) != cfg_id
        assert cfg["translate"]["openai"]["api_key"] == original_openai
        assert cfg["translate"]["gemini"]["api_key"] == original_gemini
        assert cfg["metatube"]["token"] == original_token
        assert cfg["translate"]["openai"]["api_key"] == "sk-test-roundtrip"

    def test_masks_three_secret_paths_rest_deep_equal(self):
        """B12: three SECRET_FIELDS paths masked; everything else deep-equal."""
        cfg = _sample_cfg()
        baseline = copy.deepcopy(cfg)
        rendered = render_config_secrets(cfg)

        assert rendered["translate"]["openai"]["api_key"] == mask_secret(
            "sk-test-roundtrip"
        )
        assert rendered["translate"]["gemini"]["api_key"] == mask_secret(
            "sk-test-roundtrip"
        )
        assert rendered["metatube"]["token"] == mask_secret("mt-secret-token-xyz")

        # Restore masked paths and compare deep equality for the rest.
        restored = copy.deepcopy(rendered)
        restored["translate"]["openai"]["api_key"] = baseline["translate"]["openai"]["api_key"]
        restored["translate"]["gemini"]["api_key"] = baseline["translate"]["gemini"]["api_key"]
        restored["metatube"]["token"] = baseline["metatube"]["token"]
        assert restored == baseline

    def test_missing_path_skipped_no_empty_nest(self):
        """Missing path is skipped; no empty nests created."""
        cfg = {"general": {"theme": "light"}}
        rendered = render_config_secrets(cfg)
        assert rendered == {"general": {"theme": "light"}}
        assert "translate" not in rendered
        assert "metatube" not in rendered

    def test_empty_secret_stays_empty(self):
        cfg = {
            "translate": {
                "gemini": {"api_key": ""},
                "openai": {"api_key": ""},
            },
            "metatube": {"token": ""},
        }
        rendered = render_config_secrets(cfg)
        assert rendered["translate"]["gemini"]["api_key"] == ""
        assert rendered["translate"]["openai"]["api_key"] == ""
        assert rendered["metatube"]["token"] == ""


# ============ B14: SECRET_FIELDS inventory ============

class TestSecretFieldsInventory:
    def test_exactly_three_paths_pinned(self):
        """B14: SECRET_FIELDS is exactly the three opaque credential paths."""
        assert SECRET_FIELDS == (
            "translate.gemini.api_key",
            "translate.openai.api_key",
            "metatube.token",
        )
        assert isinstance(SECRET_FIELDS, tuple)
        assert len(SECRET_FIELDS) == 3
