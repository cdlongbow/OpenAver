"""
tests/unit/test_nfo_title_format.py

TASK-154b-T1: format_nfo_title / validate_nfo_title_format / resolve_title_body
純函式契約測試。
"""

from core.nfo_title_format import (
    format_nfo_title,
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
