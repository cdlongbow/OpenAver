"""Unit tests for core.enrich_contract — cover_uri_is_servable / compute_has_servable_cover.

Bug 1 (feature/105) 四組正交邊界：
1. DB 有 cover_path + 檔在磁碟 → True
2. DB 有 cover_path + 檔已刪 → False（Bug 1 核心）
3. 無 row / cover_path 空 → False（短路，不呼叫 os.path.exists）
4. path-mapping 解不到（uri_to_local_fs_path 回不存在路徑）→ False
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from core.enrich_contract import (
    apply_cover_preserve,
    compute_has_servable_cover,
    cover_uri_is_servable,
    effective_original_title,
    effective_title,
    enrich_success,
    should_preserve_cover,
)


# ── cover_uri_is_servable ────────────────────────────────────────────────────

class TestCoverUriIsServable:

    def test_cover_present_but_file_deleted_false(self, mocker):
        """Bug 1 核心：DB 有 cover_path 但實體檔已被刪 → False。"""
        mocker.patch("core.enrich_contract.os.path.exists", return_value=False)
        assert cover_uri_is_servable("file:///out/ABC-001/ABC-001.jpg", {}) is False


# ── compute_has_servable_cover ───────────────────────────────────────────────

class TestComputeHasServableCover:
    def _repo(self, cover_path):
        repo = MagicMock()
        repo.get_by_path.return_value = SimpleNamespace(cover_path=cover_path)
        return repo

    def test_db_has_cover_and_file_exists_true(self, mocker):
        mocker.patch("core.enrich_contract.os.path.exists", return_value=True)
        repo = self._repo("file:///out/ABC-001/ABC-001.jpg")
        assert compute_has_servable_cover(repo, "file:///src/ABC-001.mp4", {}) is True


# ── effective_original_title ─────────────────────────────────────────────────

class TestEffectiveOriginalTitle:
    """重刮回空原文標題時保留 DB 既有值（唯一 preserve 邏輯，方案 A）。3 邊界：
    1. meta 有非空值 → 用 meta（新值仍覆蓋既有）
    2. meta 空/缺 key + existing 有值 → 保留 existing（Bug 2 修正）
    3. meta 空/缺 key + existing=None → ''
    """


    def test_meta_empty_or_missing_falls_back_to_existing(self):
        """meta 空 '' 或缺 key + existing 有值 → 保留 existing（Bug 2 修正）。"""
        existing = SimpleNamespace(original_title='既存')
        assert effective_original_title({'original_title': ''}, existing) == '既存'
        assert effective_original_title({}, existing) == '既存'


    def test_existing_original_title_none_returns_empty_str_not_none(self):
        """meta 空 + existing.original_title 為 SQL NULL（Video.from_row → Python None）→ 回 ''
        而非 None（grok pre-merge P2 回歸修正）。DB `original_title TEXT` 可為 NULL、
        `from_row` 原樣傳 None；若回 None 會被注入 meta['original_title']，下游
        `generate_nfo` 的 `html.escape(None)` 拋 AttributeError。回傳恆為 str。"""
        assert effective_original_title({}, SimpleNamespace(original_title=None)) == ''
        assert effective_original_title({'original_title': ''}, SimpleNamespace(original_title=None)) == ''
        # 型別鎖：任何輸入組合回傳皆為 str（不得回 None）
        assert isinstance(effective_original_title({}, SimpleNamespace(original_title=None)), str)


# ── effective_title ──────────────────────────────────────────────────────────

class TestEffectiveTitle:
    """重刮且使用者勾選保留標題時，維持 DB 既有標題值（含 [番號] 前綴）。5 邊界：
    1. preserve=True + existing.title 非空且剝完非空 → existing.title 原值逐字
    2. preserve=True + existing is None → meta['title']
    3. preserve=True + existing.title 剝完為空 → meta['title']
    4. preserve=False → meta['title'] 恆等映射
    5. meta['title'] None/缺 key → ''（恆為 str）
    """

    def test_preserve_true_with_existing_title_returns_existing_verbatim(self):
        """preserve=True 且 existing.title 剝完非空 → 回傳 existing.title 原值逐字（含前綴）。"""
        existing = SimpleNamespace(title='[ABC-123]中文片名', number='ABC-123')
        meta = {'title': '日文片名'}
        assert effective_title(meta, existing, True, 'ABC-123') == '[ABC-123]中文片名'


    def test_preserve_true_with_existing_number_mismatch_falls_back_to_new_title(self):
        """preserve=True 但這次要寫入的番號（`number` 參數）與這部片既有的
        `existing.number` 不同（`allow_number_change=true` 把片改成另一個番號）
        → 不保留舊標題，回退新標題。刻意讓 meta['number'] 與目標 number 相等
        （來源忠實刮回使用者要求的新番號，這是允許改號時的常見情境）以證明
        比對必須落在 `existing.number` vs number，比對 meta['number'] 會誤放行。"""
        existing = SimpleNamespace(title='中文片名', number='ABC-123')
        meta = {'title': '刮到別部片的新標題', 'number': 'XYZ-999'}
        assert effective_title(meta, existing, True, 'XYZ-999') == '刮到別部片的新標題'


    def test_preserve_true_with_scraped_number_mismatch_existing_matches_number_falls_back(self):
        """existing.number == number（請求番號＝原片番號，前端 numberChanged 檢查會放行）
        但這次唯讀來源獨立重新搜尋回來的 meta['number'] 與兩者不同（刮到另一部片，
        不受前端檢查保護）→ 仍須回退新標題，不得只看 existing vs number 就放行。"""
        existing = SimpleNamespace(title='中文片名', number='TEST-001')
        meta = {'title': '刮到別部片的新標題', 'number': 'OTHER-777'}
        assert effective_title(meta, existing, True, 'TEST-001') == '刮到別部片的新標題'


    def test_preserve_true_with_override_returns_override_verbatim(self):
        """CD-154b-12：preserve=True 且 preserved_body_override 非 None → 回傳 override 逐字。"""
        existing = SimpleNamespace(title='ABC-123-片名-三上悠亜', number='ABC-123')
        meta = {'title': '新標題'}
        assert effective_title(
            meta, existing, True, 'ABC-123', preserved_body_override='片名',
        ) == '片名'


# ── should_preserve_cover ────────────────────────────────────────────────────

class TestShouldPreserveCover:
    """純政策 predicate：write_cover × overwrite_existing × cover_exists 三布林正交。
    mode 維度已移除（AC4 mode-agnostic）。4 組有效組合（write_cover=False 吸收
    overwrite/exists 兩維，故 4 組非 8 組）。"""

    def test_not_write_cover_always_preserves(self):
        """write_cover=False → 恆保留（吸收 overwrite/exists 兩維）。"""
        assert should_preserve_cover(False, False, False) is True
        assert should_preserve_cover(False, False, True) is True
        assert should_preserve_cover(False, True, False) is True
        assert should_preserve_cover(False, True, True) is True

    def test_write_cover_existing_no_overwrite_preserves(self):
        """有封面 + 不覆蓋 → 保留。"""
        assert should_preserve_cover(True, False, True) is True

    def test_write_cover_existing_overwrite_writes(self):
        """有封面 + 覆蓋 → 寫（不保留）。"""
        assert should_preserve_cover(True, True, True) is False


# ── enrich_success ───────────────────────────────────────────────────────────

class TestEnrichSuccess:
    """成功建構器（feature/105 T4，CD-105-7）：reason 派生單一住 builder 內。
    has_servable_cover（None/True/False）× reason（None/顯式）正交三態；
    has_servable_cover is not None 時派生值覆蓋 reason 參數（派生優先）。
    """

    def _base_kwargs(self):
        return dict(
            nfo_written=True,
            cover_written=False,
            extrafanart_written=3,
            fields_filled=['title', 'actors'],
            source_used='javdb',
        )


    def test_has_servable_cover_false_derives_no_cover(self):
        r = enrich_success(**self._base_kwargs(), has_servable_cover=False)
        assert r.reason == 'no_cover'


# ── apply_cover_preserve ─────────────────────────────────────────────────────

class TestApplyCoverPreserve:
    def test_preserve_returns_none_strategy(self):
        """命中保留 → ('none',)，覆蓋掉原 strategy。"""
        assert apply_cover_preserve(
            ("download", "http://x/new.jpg"), False, False, False
        ) == ("none",)
        assert apply_cover_preserve(
            ("download", "http://x/new.jpg"), True, False, True
        ) == ("none",)

