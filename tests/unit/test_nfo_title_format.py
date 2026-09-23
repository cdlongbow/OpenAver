"""
tests/unit/test_nfo_title_format.py

TASK-154b-T1: format_nfo_title / validate_nfo_title_format / resolve_title_body
純函式契約測試。
"""

from types import SimpleNamespace

from core.nfo_title_format import (
    format_nfo_title,
    resolve_preserved_title_for_write,
    resolve_title_body,
    validate_nfo_title_format,
)


# ── format_nfo_title ─────────────────────────────────────────────────────

class TestFormatNfoTitle:
    def test_default_format_matches_legacy_with_title(self):
        """AC-b1：預設格式與今天 f"[{number}]{_t}" 逐位元組相同。"""
        data = {
            'number': 'ABC-123',
            'title': '片名',
            'actors': ['三上悠亜'],
            'maker': 'Maker',
            'date': '2024-01-15',
        }
        assert format_nfo_title('[{num}]{title}', data) == '[ABC-123]片名'

    def test_default_format_matches_legacy_empty_title(self):
        """AC-b1：title 為空時與 f"[{number}]" 逐位元組相同。"""
        data = {
            'number': 'ABC-123',
            'title': '',
            'actors': [],
            'maker': '',
            'date': '',
        }
        assert format_nfo_title('[{num}]{title}', data) == '[ABC-123]'

    def test_trailing_dash_kept_when_actor_empty(self):
        """AC-b3：空欄位代換成空字串，結尾 `-` 不清。"""
        data = {
            'number': 'ABC-123',
            'title': '片名',
            'actors': [],
            'maker': '',
            'date': '',
        }
        assert format_nfo_title('{num}-{title}-{actor}', data) == 'ABC-123-片名-'

    def test_title_containing_literal_placeholder_not_double_substituted(self):
        """片名本身含 `{actor}` 字面，不可被後續變數代換二次改寫。

        單趟 regex 代換前，逐變數 `.replace()` 鏈式代換會把已插入的片名內容
        當成下一輪代換來源，等同二次改寫使用者資料（片名原字元保留違例）。
        """
        data = {
            'number': 'ABC-123',
            'title': '片名 {actor}',
            'actors': ['三上悠亜'],
            'maker': '',
            'date': '',
        }
        assert format_nfo_title('[{num}]{title}', data) == '[ABC-123]片名 {actor}'

    def test_title_containing_literal_num_placeholder_not_double_substituted(self):
        """片名含 `{num}` 字面，同理不可被二次改寫。"""
        data = {
            'number': 'ABC-123',
            'title': '片名{num}',
            'actors': [],
            'maker': '',
            'date': '',
        }
        assert format_nfo_title('{title}-{num}', data) == '片名{num}-ABC-123'


# ── validate_nfo_title_format ────────────────────────────────────────────

class TestValidateNfoTitleFormat:
    def test_rejects_missing_num(self):
        err = validate_nfo_title_format('{title}-{actor}')
        assert err is not None
        assert '{num}' in err

    def test_rejects_missing_title(self):
        err = validate_nfo_title_format('{num}-{actor}')
        assert err is not None
        assert '{title}' in err

    def test_rejects_duplicate_num(self):
        err = validate_nfo_title_format('{num}-{num}-{title}')
        assert err is not None
        assert '{num}' in err

    def test_validate_nfo_title_format_rejects_duplicate_title(self):
        err = validate_nfo_title_format('{num}-{title}{title}')
        assert err is not None
        assert '{title}' in err

    def test_accepts_swapped_order_and_other_vars(self):
        assert validate_nfo_title_format('{title}-{num}-{actor}-{maker}-{date}') is None
        assert validate_nfo_title_format('[{num}]{title}') is None
        assert validate_nfo_title_format('{num}-{title}-{actor}') is None


# ── resolve_title_body ───────────────────────────────────────────────────

class TestResolveTitleBody:
    def test_step1_record_matches_returns_body(self):
        """步驟 1：記錄存在且 <title> 未變 → 採記錄 body。"""
        result = resolve_title_body(
            raw_title='ABC-123-片名-三上悠亜',
            number='ABC-123',
            actors=['三上悠亜'],
            maker='',
            date='',
            nfo_title_format='{num}-{title}-{actor}',
            record=('ABC-123-片名-三上悠亜', '片名'),
        )
        assert result == '片名'

    def test_step2_record_stale_falls_through(self):
        """步驟 2：記錄存在但 <title> 被改過 → 落到 3/4/5（此例落步驟 3）。"""
        result = resolve_title_body(
            raw_title='[ABC-123]外部改過的片名',
            number='ABC-123',
            actors=['三上悠亜'],
            maker='',
            date='',
            nfo_title_format='{num}-{title}-{actor}',
            record=('ABC-123-片名-三上悠亜', '片名'),
        )
        assert result == '外部改過的片名'

    def test_step3_bracket_prefix_stripped(self):
        """步驟 3：無記錄、符合 [番號] 方括號前綴 → 剝方括號。"""
        result = resolve_title_body(
            raw_title='[ABC-123]片名',
            number='ABC-123',
            actors=[],
            maker='',
            date='',
            nfo_title_format='[{num}]{title}',
            record=None,
        )
        assert result == '片名'

    def test_step3_bracket_prefix_with_leftover_bare_number_stripped(self):
        """步驟 3：舊版疊層寫法 `[番號]番號 片名` → 剝完方括號後再剝殘留裸番號。"""
        result = resolve_title_body(
            raw_title='[ABC-123]ABC-123 片名',
            number='ABC-123',
            actors=[],
            maker='',
            date='',
            nfo_title_format='[{num}]{title}',
            record=None,
        )
        assert result == '片名'

    def test_resolve_title_body_step3_bracket_only_not_bare_number(self):
        """步驟 3 只認方括號；裸番號格式交給步驟 4 反推（AC-b7 oracle）。"""
        result = resolve_title_body(
            raw_title='ABC-123-片名-三上悠亜',
            number='ABC-123',
            actors=['三上悠亜'],
            maker='',
            date='',
            nfo_title_format='{num}-{title}-{actor}',
            record=None,
        )
        assert result == '片名'

    def test_step4_custom_format_reverse(self):
        """步驟 4：無記錄、完全吻合目前格式前後段 → 依格式反推。"""
        result = resolve_title_body(
            raw_title='ABC-123-片名-三上悠亜',
            number='ABC-123',
            actors=['三上悠亜'],
            maker='',
            date='',
            nfo_title_format='{num}-{title}-{actor}',
            record=None,
        )
        assert result == '片名'

    def test_step5_fallback_strips_bare_number(self):
        """步驟 5：都不符合 → 原樣保留只剝開頭番號（含裸番號）。"""
        result = resolve_title_body(
            raw_title='ABC-123 完全不像格式的片名',
            number='ABC-123',
            actors=['別人'],
            maker='',
            date='',
            nfo_title_format='{num}-{title}-{actor}',
            record=None,
        )
        assert result == '完全不像格式的片名'


# ── resolve_preserved_title_for_write ────────────────────────────────────

class TestResolvePreservedTitleForWrite:
    """TASK-154b-T6 / CD-154b-12：保留分支「原樣掃入」vs「刮削本體」判準。"""

    def test_resolve_preserved_title_oracle_a_override_when_scanned_body_shorter_than_stripped(self):
        """oracle (a)：原樣掃入的自訂格式 → body 短於 _strip_num_prefixes → 回傳 body。"""
        existing = SimpleNamespace(
            title='ABC-123-片名-三上悠亜',
            number='ABC-123',
            actresses=['三上悠亜'],
            maker='',
            release_date='',
        )
        result = resolve_preserved_title_for_write(
            disk_title='ABC-123-片名-三上悠亜',
            existing=existing,
            nfo_title_format='{num}-{title}-{actor}',
            record=None,
        )
        assert result == '片名'

    def test_resolve_preserved_title_oracle_b_disk_mismatch_keeps_existing_verbatim(self):
        """oracle (b)：DB 已是使用者自訂標題、磁碟 NFO 仍是舊自訂格式 → 不相等，回傳 None。

        資料刻意讓「若拿掉 disk_title != existing.title 判斷」時，磁碟反推 body='片名'
        會 ≠ _strip_num_prefixes(existing.title)——少了這道判斷就會覆寫使用者自訂標題。
        """
        existing = SimpleNamespace(
            title='我的自訂標題',
            number='ABC-123',
            actresses=['三上悠亜'],
            maker='',
            release_date='',
        )
        result = resolve_preserved_title_for_write(
            disk_title='ABC-123-片名-三上悠亜',
            existing=existing,
            nfo_title_format='{num}-{title}-{actor}',
            record=None,
        )
        assert result is None

    def test_resolve_preserved_title_oracle_c_no_override_when_body_equals_stripped(self):
        """oracle (c)：預設格式、body 與剝法一致 → 不觸發 override，回傳 None。"""
        existing = SimpleNamespace(
            title='[ABC-123]中文片名',
            number='ABC-123',
            actresses=[],
            maker='',
            release_date='',
        )
        result = resolve_preserved_title_for_write(
            disk_title='[ABC-123]中文片名',
            existing=existing,
            nfo_title_format='[{num}]{title}',
            record=None,
        )
        assert result is None
