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
    EnrichResult,
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
    def test_cover_present_and_file_exists_true(self, mocker):
        mocker.patch("core.enrich_contract.os.path.exists", return_value=True)
        assert cover_uri_is_servable("file:///out/ABC-001/ABC-001.jpg", {}) is True

    def test_cover_present_but_file_deleted_false(self, mocker):
        """Bug 1 核心：DB 有 cover_path 但實體檔已被刪 → False。"""
        mocker.patch("core.enrich_contract.os.path.exists", return_value=False)
        assert cover_uri_is_servable("file:///out/ABC-001/ABC-001.jpg", {}) is False

    def test_empty_cover_short_circuits_without_disk_check(self, mocker):
        """cover_uri 空 → 短路 False，os.path.exists 不得被呼叫。"""
        m_exists = mocker.patch("core.enrich_contract.os.path.exists", return_value=True)
        assert cover_uri_is_servable("", {}) is False
        m_exists.assert_not_called()

    def test_path_mapping_unresolvable_false(self, mocker):
        """path-mapping 解不到 → uri_to_local_fs_path 回不存在路徑 → os.path.exists False。"""
        # 不 mock os.path.exists；用一個保證不存在的路徑，讓真實磁碟檢查回 False。
        assert cover_uri_is_servable(
            "file:///nonexistent-drive/definitely/not/here-xyz.jpg", {}
        ) is False


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

    def test_db_has_cover_but_file_deleted_false(self, mocker):
        """Bug 1 核心：DB row 殘留 cover_path、磁碟檔已刪 → False。"""
        mocker.patch("core.enrich_contract.os.path.exists", return_value=False)
        repo = self._repo("file:///out/ABC-001/ABC-001.jpg")
        assert compute_has_servable_cover(repo, "file:///src/ABC-001.mp4", {}) is False

    def test_no_row_false_short_circuits(self, mocker):
        """無 row → cover_path '' → False，os.path.exists 不得被呼叫。"""
        m_exists = mocker.patch("core.enrich_contract.os.path.exists", return_value=True)
        repo = MagicMock()
        repo.get_by_path.return_value = None
        assert compute_has_servable_cover(repo, "file:///src/ABC-001.mp4", {}) is False
        m_exists.assert_not_called()

    def test_empty_cover_path_false_short_circuits(self, mocker):
        m_exists = mocker.patch("core.enrich_contract.os.path.exists", return_value=True)
        repo = self._repo("")
        assert compute_has_servable_cover(repo, "file:///src/ABC-001.mp4", {}) is False
        m_exists.assert_not_called()

    def test_path_mapping_unresolvable_false(self):
        """path-mapping 解不到 → 真實磁碟檢查回 False（不 mock os.path.exists）。"""
        repo = self._repo("file:///nonexistent-drive/definitely/not/here-xyz.jpg")
        assert compute_has_servable_cover(repo, "file:///src/ABC-001.mp4", {}) is False

    def test_uses_given_path_uri_key(self, mocker):
        """compute 必須用傳入的 path_uri 當 get_by_path 的 key（upsert 寫入同 key）。"""
        mocker.patch("core.enrich_contract.os.path.exists", return_value=True)
        repo = self._repo("file:///out/x.jpg")
        compute_has_servable_cover(repo, "file:///the/canonical/key.mp4", {})
        repo.get_by_path.assert_called_once_with("file:///the/canonical/key.mp4")


# ── effective_original_title ─────────────────────────────────────────────────

class TestEffectiveOriginalTitle:
    """重刮回空原文標題時保留 DB 既有值（唯一 preserve 邏輯，方案 A）。3 邊界：
    1. meta 有非空值 → 用 meta（新值仍覆蓋既有）
    2. meta 空/缺 key + existing 有值 → 保留 existing（Bug 2 修正）
    3. meta 空/缺 key + existing=None → ''
    """

    def test_meta_has_value_uses_meta(self):
        """meta 有非空 original_title → 用之（即使 existing 也有值仍覆蓋）。"""
        existing = SimpleNamespace(original_title='既存')
        assert effective_original_title({'original_title': '新原題'}, existing) == '新原題'
        assert effective_original_title({'original_title': '新原題'}, None) == '新原題'

    def test_meta_empty_or_missing_falls_back_to_existing(self):
        """meta 空 '' 或缺 key + existing 有值 → 保留 existing（Bug 2 修正）。"""
        existing = SimpleNamespace(original_title='既存')
        assert effective_original_title({'original_title': ''}, existing) == '既存'
        assert effective_original_title({}, existing) == '既存'

    def test_both_empty_or_no_existing_returns_empty(self):
        """meta 空/缺 + existing=None（或 existing 也空）→ ''。"""
        assert effective_original_title({'original_title': ''}, None) == ''
        assert effective_original_title({}, None) == ''
        assert effective_original_title({'original_title': ''}, SimpleNamespace(original_title='')) == ''

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

    def test_preserve_true_with_none_existing_falls_back_to_meta_title(self):
        """preserve=True 且 existing is None → 回退 meta.get('title') or ''。"""
        meta = {'title': '新片名'}
        assert effective_title(meta, None, True, 'ABC-123') == '新片名'
        assert effective_title({}, None, True, 'ABC-123') == ''

    def test_preserve_true_with_stripped_empty_falls_back_to_meta_title(self):
        """preserve=True 且 existing.title 剝完前綴為空字串（如 '[ABC-123]'）→ 回退 meta.get('title') or ''。"""
        existing = SimpleNamespace(title='[ABC-123]', number='ABC-123')
        meta = {'title': '新刮到的標題'}
        assert effective_title(meta, existing, True, 'ABC-123') == '新刮到的標題'

    def test_preserve_false_or_default_returns_meta_title(self):
        """preserve=False → 恆回傳 meta.get('title') or ''，不保留 existing。"""
        existing = SimpleNamespace(title='[ABC-123]中文片名', number='ABC-123')
        meta = {'title': '日文新片名'}
        assert effective_title(meta, existing, False, 'ABC-123') == '日文新片名'

    def test_title_none_or_missing_normalized_to_empty_str(self):
        """meta['title'] 為 None 或缺 key → 回傳 ''（恆為 str）。"""
        assert effective_title({'title': None}, None, False, 'ABC-123') == ''
        assert effective_title({}, None, False, 'ABC-123') == ''
        assert isinstance(effective_title({'title': None}, None, False, 'ABC-123'), str)

    def test_preserve_true_with_existing_number_mismatch_falls_back_to_new_title(self):
        """preserve=True 但這次要寫入的番號（`number` 參數）與這部片既有的
        `existing.number` 不同（`allow_number_change=true` 把片改成另一個番號）
        → 不保留舊標題，回退新標題。刻意讓 meta['number'] 與目標 number 相等
        （來源忠實刮回使用者要求的新番號，這是允許改號時的常見情境）以證明
        比對必須落在 `existing.number` vs number，比對 meta['number'] 會誤放行。"""
        existing = SimpleNamespace(title='中文片名', number='ABC-123')
        meta = {'title': '刮到別部片的新標題', 'number': 'XYZ-999'}
        assert effective_title(meta, existing, True, 'XYZ-999') == '刮到別部片的新標題'

    def test_preserve_true_with_existing_number_case_insensitive_match_preserves(self):
        """existing.number 與要寫入的 number 僅大小寫不同（視為同一部片）→ 仍保留舊標題。"""
        existing = SimpleNamespace(title='中文片名', number='abc-123')
        meta = {'title': '新刮到的標題', 'number': 'ABC-123'}
        assert effective_title(meta, existing, True, 'ABC-123') == '中文片名'

    def test_preserve_true_without_meta_number_key_still_gated_by_existing_number(self):
        """非唯讀 enrich_single 的 meta 從不帶 'number' key（_scraper_to_meta 無此欄位）——
        閘門不看 meta['number']，改比對 existing.number vs number：番號不變則保留。"""
        existing = SimpleNamespace(title='中文片名', number='ABC-123')
        meta = {'title': '新刮到的標題'}
        assert effective_title(meta, existing, True, 'ABC-123') == '中文片名'

    def test_preserve_true_with_scraped_number_mismatch_existing_matches_number_falls_back(self):
        """existing.number == number（請求番號＝原片番號，前端 numberChanged 檢查會放行）
        但這次唯讀來源獨立重新搜尋回來的 meta['number'] 與兩者不同（刮到另一部片，
        不受前端檢查保護）→ 仍須回退新標題，不得只看 existing vs number 就放行。"""
        existing = SimpleNamespace(title='中文片名', number='TEST-001')
        meta = {'title': '刮到別部片的新標題', 'number': 'OTHER-777'}
        assert effective_title(meta, existing, True, 'TEST-001') == '刮到別部片的新標題'

    def test_preserve_true_with_all_three_numbers_agreeing_preserves(self):
        """existing.number、number、meta['number'] 三者一致（大小寫不敏感）→ 保留舊標題。"""
        existing = SimpleNamespace(title='中文片名', number='abc-123')
        meta = {'title': '新刮到的標題', 'number': 'Abc-123'}
        assert effective_title(meta, existing, True, 'ABC-123') == '中文片名'

    def test_preserve_true_without_meta_number_key_but_existing_number_changed_falls_back(self):
        """同上情境（meta 無 'number' key）但 existing.number 與要寫入的 number 不同
        （allow_number_change=true）→ 舊版比對只看 meta['number']（缺 key）恆短路為
        False、永遠保留舊標題（即 Codex 指出的非唯讀路徑必然失效）；新版比對
        existing.number 正確回退新標題。"""
        existing = SimpleNamespace(title='中文片名', number='ABC-123')
        meta = {'title': '刮到新片的標題'}
        assert effective_title(meta, existing, True, 'XYZ-999') == '刮到新片的標題'

    def test_preserve_true_with_override_returns_override_verbatim(self):
        """CD-154b-12：preserve=True 且 preserved_body_override 非 None → 回傳 override 逐字。"""
        existing = SimpleNamespace(title='ABC-123-片名-三上悠亜', number='ABC-123')
        meta = {'title': '新標題'}
        assert effective_title(
            meta, existing, True, 'ABC-123', preserved_body_override='片名',
        ) == '片名'

    def test_preserve_true_without_override_falls_back_to_existing_branch(self):
        """CD-154b-12：preserve=True 且 override 為 None／未傳 → 既有 existing.title 分支零回歸。"""
        existing = SimpleNamespace(title='ABC-123-片名-三上悠亜', number='ABC-123')
        meta = {'title': '新標題'}
        assert effective_title(meta, existing, True, 'ABC-123') == 'ABC-123-片名-三上悠亜'
        assert effective_title(
            meta, existing, True, 'ABC-123', preserved_body_override=None,
        ) == 'ABC-123-片名-三上悠亜'


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

    def test_write_cover_no_existing_writes(self):
        """無封面 → 寫（不保留，不論 overwrite）。"""
        assert should_preserve_cover(True, False, False) is False
        assert should_preserve_cover(True, True, False) is False


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

    def test_has_servable_cover_true_derives_hit(self):
        r = enrich_success(**self._base_kwargs(), has_servable_cover=True)
        assert r.reason == 'hit'

    def test_has_servable_cover_false_derives_no_cover(self):
        r = enrich_success(**self._base_kwargs(), has_servable_cover=False)
        assert r.reason == 'no_cover'

    def test_no_cover_arg_and_reason_none_stays_none(self):
        """samples 站：不傳 has_servable_cover + reason=None（顯式）→ None。"""
        r = enrich_success(**self._base_kwargs(), reason=None)
        assert r.reason is None

    def test_no_cover_arg_reason_passthrough(self):
        """has_servable_cover=None + 顯式 reason → 原樣穿透（走 else 分支）。"""
        r = enrich_success(**self._base_kwargs(), reason='foo')
        assert r.reason == 'foo'

    def test_derivation_overrides_reason_param(self):
        """衝突優先：has_servable_cover=True + reason='no_cover' → 'hit'（派生覆蓋參數）。"""
        r = enrich_success(**self._base_kwargs(), has_servable_cover=True, reason='no_cover')
        assert r.reason == 'hit'

    def test_eight_fields_correct(self):
        """success/error 恆定，其餘 6 欄位原樣塞入（含 fields_filled 原樣）。"""
        fields = ['title', 'actors']
        r = enrich_success(
            nfo_written=False,
            cover_written=True,
            extrafanart_written=5,
            fields_filled=fields,
            source_used='avsox',
            has_servable_cover=None,
            reason=None,
        )
        assert isinstance(r, EnrichResult)
        assert r.success is True
        assert r.error is None
        assert r.nfo_written is False
        assert r.cover_written is True
        assert r.extrafanart_written == 5
        assert r.fields_filled == fields
        assert r.source_used == 'avsox'
        assert r.reason is None


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

    def test_not_preserve_passes_strategy_through(self):
        """不保留 → 原 strategy 原樣穿透。"""
        assert apply_cover_preserve(
            ("download", "http://x/new.jpg"), True, True, True
        ) == ("download", "http://x/new.jpg")
        assert apply_cover_preserve(
            ("download", "http://x/new.jpg"), True, False, False
        ) == ("download", "http://x/new.jpg")
