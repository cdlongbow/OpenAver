"""TASK-121a-T1: core.cover_attributes 邊界斷言。

對應卡片「本 task 特有邊界」16 條，每條至少一條斷言，不抽樣。
"""

from core.cover_attributes import ATTRIBUTE_TABLE, effective_tags, manifest_payload

_CANONICAL_TAGS = frozenset(
    {"中文字幕", "無碼破解", "無碼流出", "4K", "VR"}
)
_MANIFEST_KEYS = frozenset(
    {"id", "canonical_tag", "short_name", "display_order", "i18n_key"}
)


def _has_canonical(tags: list[str]) -> set[str]:
    return set(tags) & _CANONICAL_TAGS


def _hits_4k(tags: list[str]) -> bool:
    return any(t.strip().lower() == "4k" for t in tags)


# ── 邊界 1 ──────────────────────────────────────────────────────────────────

def test_b01_uc_hits_cracked_and_subtitle():
    """ABP-999-UC.mp4 → 結果含 無碼破解 與 中文字幕（A1 核心）。"""
    result = effective_tags("ABP-999-UC.mp4", [])
    assert "無碼破解" in result
    assert "中文字幕" in result


# ── 邊界 2 ──────────────────────────────────────────────────────────────────

def test_b02_case_insensitive_uc():
    """大小寫不敏感：abp-999-uc.MP4、ABP-999-uC.mp4 同上。"""
    for filename in ("abp-999-uc.MP4", "ABP-999-uC.mp4"):
        result = effective_tags(filename, [])
        assert "無碼破解" in result, filename
        assert "中文字幕" in result, filename


# ── 邊界 3 ──────────────────────────────────────────────────────────────────

def test_b03_abcuc_hits_nothing():
    """ABCUC-123.mp4 → 不命中任何屬性（A6）。"""
    result = effective_tags("ABCUC-123.mp4", [])
    assert _has_canonical(result) == set()


# ── 邊界 4 ──────────────────────────────────────────────────────────────────

def test_b04_uncensored_paradise_hits_nothing():
    """Uncensored Paradise.mp4 → 不命中任何屬性（A6）。"""
    result = effective_tags("Uncensored Paradise.mp4", [])
    assert _has_canonical(result) == set()


# ── 邊界 5 ──────────────────────────────────────────────────────────────────

def test_b05_multipart_tokens_add_nothing():
    """ABC-123-cd1.mp4 / ABC-123-pt2.mp4 → 與 existing_tags 等價，零新增（A4）。"""
    existing = ["既有標籤"]
    assert effective_tags("ABC-123-cd1.mp4", existing) == existing
    assert effective_tags("ABC-123-pt2.mp4", existing) == existing


# ── 邊界 6 ──────────────────────────────────────────────────────────────────

def test_b06_cracked_and_leaked_not_mutex():
    """ABC-123-U-leak.mp4 → 無碼破解 與 無碼流出 兩個都在（A5，不互斥）。"""
    result = effective_tags("ABC-123-U-leak.mp4", [])
    assert "無碼破解" in result
    assert "無碼流出" in result


# ── 邊界 7 ──────────────────────────────────────────────────────────────────

def test_b07_dedup_cracked():
    """existing_tags=['無碼破解'] ＋ ABC-123-U.mp4 → 結果只有一個 無碼破解。"""
    result = effective_tags("ABC-123-U.mp4", ["無碼破解"])
    assert result.count("無碼破解") == 1
    assert result == ["無碼破解"]


# ── 邊界 8 ──────────────────────────────────────────────────────────────────

def test_b08_dedup_keeps_first_casing():
    """existing_tags=['vr'] ＋ ABC-123-VR.mp4 → 只有一項且為 'vr'。"""
    result = effective_tags("ABC-123-VR.mp4", ["vr"])
    assert result == ["vr"]


# ── 邊界 9 ──────────────────────────────────────────────────────────────────

def test_b09_cd10_4k_genre_confluence():
    """existing_tags=['4k'] / ['UHD'] / ['8K'] → 皆命中 4K（各一條）。"""
    assert _hits_4k(effective_tags("ABC-123.mp4", ["4k"]))
    assert _hits_4k(effective_tags("ABC-123.mp4", ["UHD"]))
    assert _hits_4k(effective_tags("ABC-123.mp4", ["8K"]))


# ── 邊界 10 ─────────────────────────────────────────────────────────────────

def test_b10_cd10_4k_remaster_does_not_hit():
    """existing_tags=['4K Remaster'] → 不命中 4K（不得新增 4K 項）。"""
    result = effective_tags("ABC-123.mp4", ["4K Remaster"])
    assert "4K" not in result
    assert not _hits_4k(result)


# ── 邊界 11 ─────────────────────────────────────────────────────────────────

def test_b11_bareword_left_right_boundary():
    """裸詞左右邊界：流出命中；ABC-123umr9 / XXumrYY 不命中。"""
    assert "無碼流出" in effective_tags("ABC-123-流出.mp4", [])
    umr_digit = effective_tags("ABC-123umr9.mp4", [])
    assert "無碼破解" not in umr_digit
    assert _has_canonical(umr_digit) == set()
    umr_letters = effective_tags("XXumrYY.mp4", [])
    assert "無碼破解" not in umr_letters
    assert _has_canonical(umr_letters) == set()


def test_b11b_bareword_left_boundary_alone():
    """左邊界獨立驗證：umr 右側是分隔字元／結尾（右邊界會放行），只有左邊界能擋。

    review finding（2026-08-19）：原 b11 的兩個負例右側都是英數，右邊界單獨就擋得住，
    左邊界被拿掉時測試仍全綠。這幾條才是左邊界的安全網——它破了，
    `SUMR-001.mp4` 這種真實檔名會被誤貼「無碼破解」寫進使用者的 .nfo。
    """
    for filename in ("SUMR-001.mp4", "Xumr.mp4", "ABC-123umr.mp4", "ABC-123umr-999.mp4"):
        result = effective_tags(filename, [])
        assert "無碼破解" not in result, filename
        assert _has_canonical(result) == set(), filename


def test_b11c_dedup_key_strips_whitespace():
    """既有 tag 帶前後空白時不得與新產生的 canonical 值並存（review finding）。

    第三方刮削器留下的 NFO 可能寫成 `<genre> VR </genre>`；不 strip 的話
    使用者的 .nfo 會出現兩筆幾乎相同的 tag，Jellyfin/Emby 分類列表看到重複項。
    """
    assert effective_tags("ABC-123-VR.mp4", [" VR"]) == [" VR"]
    assert effective_tags("ABC-123-VR.mp4", ["VR "]) == ["VR "]
    assert effective_tags("ABC-123.mp4", [" 4K "]) == [" 4K "]
    assert effective_tags("ABC-123.mp4", [" uhd"]) == [" uhd", "4K"]


# ── 邊界 12 ─────────────────────────────────────────────────────────────────

def test_b12_ch_token_hits_subtitle():
    """ABC-123-ch.mp4 → 中文字幕。"""
    result = effective_tags("ABC-123-ch.mp4", [])
    assert "中文字幕" in result


# ── 邊界 13 ─────────────────────────────────────────────────────────────────

def test_b13_empty_inputs():
    """effective_tags('', []) → []；existing_tags=None 不炸（回 []）。"""
    assert effective_tags("", []) == []
    assert effective_tags("ABC-123.mp4", None) == []


# ── 邊界 14 ─────────────────────────────────────────────────────────────────

def test_b14_does_not_mutate_input():
    """傳入的 list 物件在呼叫後長度不變。"""
    incoming = ["既有"]
    effective_tags("ABC-123-U.mp4", incoming)
    assert len(incoming) == 1
    assert incoming == ["既有"]


# ── 邊界 15 ─────────────────────────────────────────────────────────────────

def test_b15_manifest_payload_shape():
    """5 筆、欄位恰為指定 5 個 key、不含 tokens/source、display_order 符合表格。"""
    payload = manifest_payload()
    assert len(payload) == 5
    assert [row["id"] for row in payload] == [
        "subtitle",
        "cracked",
        "leaked",
        "4k",
        "vr",
    ]
    for row in payload:
        assert set(row.keys()) == _MANIFEST_KEYS
        assert "tokens" not in row
        assert "source" not in row
    orders = {row["id"]: row["display_order"] for row in payload}
    assert orders == {
        "subtitle": 1,
        "cracked": 2,
        "leaked": 2,
        "4k": 4,
        "vr": 3,
    }
    assert len(ATTRIBUTE_TABLE) == 5


# ── 邊界 16 ─────────────────────────────────────────────────────────────────

def test_b16_tokens_exclude_multipart_roots():
    """ATTRIBUTE_TABLE 的所有 token 不含 cd / pt / disc 詞根（A4）。"""
    roots = ("cd", "pt", "disc")
    for rule in ATTRIBUTE_TABLE:
        for token in rule.tokens:
            lowered = token.lower()
            for root in roots:
                assert root not in lowered, f"{rule.id} token {token!r} contains {root!r}"
