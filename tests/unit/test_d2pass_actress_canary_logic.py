"""Deterministic unit tests for the d2pass three-site actress canary decision logic
(TASK-155c-T2). Zero network, duck-typed fake video — mirrors
`tests/unit/test_source_canary_logic.py::_video`.
"""
import types
from unittest.mock import MagicMock

import requests

from tests.smoke.test_source_canary import _classify_d2pass_one, _probe_d2pass_site


def _video(number="051515-877", title="Some Title", cover_url="http://x/c.jpg",
           actresses=("波多野結衣",)):
    """Duck-typed fake video: .number/.title/.cover_url/.actresses (list of objects with .name)."""
    return types.SimpleNamespace(
        number=number,
        title=title,
        cover_url=cover_url,
        actresses=[types.SimpleNamespace(name=n) for n in actresses],
    )


class TestClassifyD2passOne:
    def test_all_four_pass(self):
        v = _video()
        assert _classify_d2pass_one(v, None, "051515-877", "波多野結衣") == "pass"

    def test_number_mismatch_is_fail(self):
        v = _video(number="999999-999")
        assert _classify_d2pass_one(v, None, "051515-877", "波多野結衣") == "fail"

    def test_empty_title_is_fail(self):
        v = _video(title="")
        assert _classify_d2pass_one(v, None, "051515-877", "波多野結衣") == "fail"

    def test_empty_cover_is_fail(self):
        v = _video(cover_url="")
        assert _classify_d2pass_one(v, None, "051515-877", "波多野結衣") == "fail"

    def test_classify_missing_actress_is_fail(self):
        # 番號／標題／封面都對，唯獨預期女優不在列——CD-155c-9 的第四項判準。
        v = _video(actresses=("別人",))
        assert _classify_d2pass_one(v, None, "051515-877", "波多野結衣") == "fail"

    def test_none_probe_true_is_fail(self):
        assert _classify_d2pass_one(None, True, "051515-877", "波多野結衣") == "fail"

    def test_none_probe_false_is_skip(self):
        assert _classify_d2pass_one(None, False, "051515-877", "波多野結衣") == "skip"

    def test_none_probe_none_is_skip(self):
        assert _classify_d2pass_one(None, None, "051515-877", "波多野結衣") == "skip"


class TestProbeD2passSite:
    def test_probe_connection_error_returns_false(self):
        scraper = MagicMock()
        scraper.normalize_number.return_value = "051515-877"
        scraper.SITE_DETAIL_URL = {"caribbeancom": "https://example.invalid/{id}"}
        scraper._session.get.side_effect = requests.ConnectionError("refused")
        assert _probe_d2pass_site("caribbeancom", "051515-877", scraper) is False
