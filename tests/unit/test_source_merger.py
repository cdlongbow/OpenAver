"""Unit tests for core.source_merger.merge_results (TASK-61a-6 / TASK-65b-2).

Contract: epic §5.1.1 (CD-61-9):
- text/meta: 整包贏 — first source in user_order present in candidates wins the
  whole text block (title/actresses/tags/series/maker/director) + meta
  (date/duration/rating/votes); empty fields fall back to later user_order sources.
- cover_url / sample_images: follow user_order — each field resolved independently
  (first non-empty source per field, may come from different sources).
- empty candidates → defensive (caller never calls with empty; return safe).
"""
import pytest

from core.scrapers.models import Video, Actress
from core.source_merger import merge_results


def _v(source, **kw):
    """Build a minimal Video for `source`."""
    return Video(number=kw.pop("number", "TEST-001"), source=source, **kw)


# ---------------------------------------------------------------------------
# Text/meta: user_order 整包贏
# ---------------------------------------------------------------------------

def test_text_fields_follow_user_order_whole_block():
    """Two sources with full text; user_order=[jav321, javbus] → jav321 wins ALL text."""
    javbus = _v(
        "javbus",
        title="JavBus Title",
        actresses=[Actress(name="JB Actress")],
        tags=["jb-tag"],
        series="JB Series",
        maker="JB Maker",
        director="JB Director",
    )
    jav321 = _v(
        "jav321",
        title="Jav321 Title",
        actresses=[Actress(name="J321 Actress")],
        tags=["j321-tag"],
        series="J321 Series",
        maker="J321 Maker",
        director="J321 Director",
    )
    merged = merge_results({"javbus": javbus, "jav321": jav321},
                           user_order=["jav321", "javbus"])

    assert merged.title == "Jav321 Title"
    assert [a.name for a in merged.actresses] == ["J321 Actress"]
    assert merged.tags == ["j321-tag"]
    assert merged.series == "J321 Series"
    assert merged.maker == "J321 Maker"
    assert merged.director == "J321 Director"
    assert merged.source == "jav321"


def test_text_source_empty_field_falls_back():
    """text_source has empty title → fall back to next user_order source's title."""
    primary = _v("jav321", title="", maker="J321 Maker")
    backup = _v("javbus", title="Backup Title", maker="JB Maker")
    merged = merge_results({"jav321": primary, "javbus": backup},
                           user_order=["jav321", "javbus"])

    # whole block from jav321 EXCEPT empty title falls back
    assert merged.title == "Backup Title"
    assert merged.maker == "J321 Maker"
    assert merged.source == "jav321"


def test_label_backfills_from_later_source():
    """label parity (61a-6 review B1): text_source empty label → backfill from later source.

    OLD merge block backfilled `label`; the field-list refactor must keep parity since
    `label` feeds NFO writing.
    """
    primary = _v("jav321", title="J321 Title", label="")
    backup = _v("javbus", title="JB Title", label="JB Label")
    merged = merge_results({"jav321": primary, "javbus": backup},
                           user_order=["jav321", "javbus"])

    assert merged.title == "J321 Title"   # whole block still from jav321
    assert merged.label == "JB Label"     # empty label backfilled
    assert merged.source == "jav321"


def test_label_kept_from_text_source_when_present():
    """text_source has a non-empty label → keep it, no backfill."""
    primary = _v("jav321", label="J321 Label")
    backup = _v("javbus", label="JB Label")
    merged = merge_results({"jav321": primary, "javbus": backup},
                           user_order=["jav321", "javbus"])
    assert merged.label == "J321 Label"


def test_summary_backfills_from_later_source():
    """summary parity (P2-1): winner with empty summary → backfill later source's plot.

    Regression: `summary` feeds NFO <plot>; if it were absent from the str-meta
    fallback group, a winning source with no summary + a losing source with one
    would drop the plot entirely.
    """
    primary = _v("jav321", title="J321 Title", summary="", rating=None)
    backup = _v("javbus", title="JB Title", summary="has plot", rating=4.5)
    merged = merge_results({"jav321": primary, "javbus": backup},
                           user_order=["jav321", "javbus"])

    assert merged.title == "J321 Title"    # whole block still from jav321
    assert merged.summary == "has plot"    # empty summary backfilled
    assert merged.rating == 4.5            # rating carries the same way (guard)
    assert merged.source == "jav321"


def test_summary_kept_from_text_source_when_present():
    """text_source has a non-empty summary → keep it, no backfill."""
    primary = _v("jav321", summary="J321 plot")
    backup = _v("javbus", summary="JB plot")
    merged = merge_results({"jav321": primary, "javbus": backup},
                           user_order=["jav321", "javbus"])
    assert merged.summary == "J321 plot"


def test_meta_fields_from_text_source():
    """date/duration/rating/votes come from text_source (整包贏)."""
    primary = _v("jav321", date="2024-01-01", duration=120, rating=4.5, votes=10)
    backup = _v("javbus", date="2099-12-31", duration=999, rating=1.0, votes=999)
    merged = merge_results({"jav321": primary, "javbus": backup},
                           user_order=["jav321", "javbus"])

    assert merged.date == "2024-01-01"
    assert merged.duration == 120
    assert merged.rating == 4.5
    assert merged.votes == 10


def test_duration_zero_is_present():
    """duration=0 is a value (is None check), not falsy → not overwritten."""
    primary = _v("jav321", duration=0)
    backup = _v("javbus", duration=120)
    merged = merge_results({"jav321": primary, "javbus": backup},
                           user_order=["jav321", "javbus"])
    assert merged.duration == 0


# ---------------------------------------------------------------------------
# Cover: user_order with independent fields
# ---------------------------------------------------------------------------

def test_cover_follows_user_order():
    """cover_url follows user_order — jav321 first → cover from jav321, NOT javbus.

    KEY behavioral proof (TASK-65b-2): javbus ordered LAST → cover must NOT be javbus's.
    """
    javbus = _v("javbus", title="JB", cover_url="http://javbus/cover.jpg",
                sample_images=["http://javbus/s1.jpg"])
    jav321 = _v("jav321", title="J321", cover_url="http://jav321/cover.jpg",
                sample_images=["http://jav321/s1.jpg"])
    merged = merge_results({"javbus": javbus, "jav321": jav321},
                           user_order=["jav321", "javbus"])

    # text from jav321 (first in user_order)
    assert merged.title == "J321"
    assert merged.source == "jav321"
    # cover from jav321 (first in user_order) — NOT javbus
    assert merged.cover_url == "http://jav321/cover.jpg"
    assert merged.sample_images == ["http://jav321/s1.jpg"]
    assert merged.cover_url != "http://javbus/cover.jpg"


def test_cover_and_sample_images_resolved_independently():
    """cover_url and sample_images may come from different sources."""
    # javbus has cover but no samples; jav321 has samples but no cover
    javbus = _v("javbus", cover_url="http://javbus/cover.jpg", sample_images=[])
    jav321 = _v("jav321", cover_url="", sample_images=["http://jav321/s.jpg"])
    merged = merge_results({"javbus": javbus, "jav321": jav321},
                           user_order=["javbus", "jav321"])

    assert merged.cover_url == "http://javbus/cover.jpg"
    assert merged.sample_images == ["http://jav321/s.jpg"]


def test_cover_user_order_direct():
    """user_order directly selects cover source — any source in user_order wins."""
    # avsox is the only source; user_order=['avsox'] → avsox cover wins directly
    avsox = _v("avsox", title="AV", cover_url="http://avsox/cover.jpg")
    merged = merge_results({"avsox": avsox},
                           user_order=["avsox"])
    assert merged.cover_url == "http://avsox/cover.jpg"


def test_cover_skips_empty_source_in_user_order():
    """user_order source with empty cover → skip to next qualifying source in user_order."""
    # user_order=['javbus','jav321']; javbus has empty cover → jav321 wins
    javbus = _v("javbus", cover_url="")
    jav321 = _v("jav321", cover_url="http://jav321/cover.jpg")
    merged = merge_results({"javbus": javbus, "jav321": jav321},
                           user_order=["javbus", "jav321"])
    assert merged.cover_url == "http://jav321/cover.jpg"


# ---------------------------------------------------------------------------
# preview_cover_url 同源綁定（TASK-113c-T3b, CD-113c-12）
# ---------------------------------------------------------------------------

def test_preview_cover_url_follows_cover_winner_when_metatube():
    """①文字勝者非 metatube、封面勝者是 metatube → preview 有值且對得上封面勝者。

    user_order=['metatube:FANZA', 'javbus']；metatube:FANZA 兩者皆有 →
    cover_url 與 preview_cover_url 都必須來自 metatube:FANZA（同一候選）。
    """
    javbus = _v("javbus", title="JB Title", cover_url="http://javbus/cover.jpg",
                preview_cover_url="")
    metatube = _v("metatube:FANZA", title="", cover_url="http://mt/cover.jpg",
                   preview_cover_url="http://mt:8080/v1/images/primary/FANZA/X?url=y")
    merged = merge_results({"javbus": javbus, "metatube:FANZA": metatube},
                           user_order=["metatube:FANZA", "javbus"])
    assert merged.cover_url == "http://mt/cover.jpg"
    assert merged.preview_cover_url == "http://mt:8080/v1/images/primary/FANZA/X?url=y"


def test_preview_cover_url_empty_when_cover_winner_not_metatube():
    """②封面勝者不是 metatube，即使**其他**候選有 preview → preview 仍必須空，
    不得沿用非勝出候選的值（同源綁定的核心防呆：不可逐欄位各自 _first_non_empty）。

    user_order=['javbus', 'metatube:FANZA']；javbus 是 cover 勝者（無 preview），
    metatube:FANZA 雖有 preview 但不是勝出候選 → merged.preview_cover_url 必須為空。
    """
    javbus = _v("javbus", title="JB Title", cover_url="http://javbus/cover.jpg",
                preview_cover_url="")
    metatube = _v("metatube:FANZA", title="", cover_url="http://mt/cover.jpg",
                   preview_cover_url="http://mt:8080/v1/images/primary/FANZA/X?url=y")
    merged = merge_results({"javbus": javbus, "metatube:FANZA": metatube},
                           user_order=["javbus", "metatube:FANZA"])
    assert merged.cover_url == "http://javbus/cover.jpg"
    assert merged.preview_cover_url == ""


def test_preview_cover_url_text_source_value_does_not_leak_when_cover_winner_differs():
    """同源綁定的第二種洩漏路徑：text_source（整包贏的來源）自己有 preview_cover_url，
    但 cover 的勝出候選是**另一個**來源時，merged 不能沿用 text_source 自己的 preview。

    user_order=['metatube:FANZA', 'javbus']；metatube:FANZA 是 text_source 但沒有
    cover_url（跳過），javbus 是 cover 勝者（無 preview）→ merged.preview_cover_url
    必須為空，不可誤用 text_source 的 preview_cover_url 預設值以外的殘留。
    """
    metatube_no_cover = _v("metatube:FANZA", title="", cover_url="",
                            preview_cover_url="")
    javbus = _v("javbus", title="JB Title", cover_url="http://javbus/cover.jpg",
                preview_cover_url="")
    merged = merge_results({"javbus": javbus, "metatube:FANZA": metatube_no_cover},
                           user_order=["metatube:FANZA", "javbus"])
    assert merged.cover_url == "http://javbus/cover.jpg"
    assert merged.preview_cover_url == ""


# ---------------------------------------------------------------------------
# Fallbacks / edge cases
# ---------------------------------------------------------------------------

def test_single_source_passthrough():
    """single candidate → that source's data verbatim."""
    only = _v("javbus", title="Only Title", cover_url="http://c.jpg",
              maker="M", actresses=[Actress(name="A")])
    merged = merge_results({"javbus": only}, user_order=["javbus"])
    assert merged.title == "Only Title"
    assert merged.cover_url == "http://c.jpg"
    assert merged.maker == "M"
    assert merged.source == "javbus"


def test_text_source_keys_not_in_user_order_falls_back_to_insertion_order():
    """candidates whose keys are not in user_order → use insertion-order first."""
    a = _v("avsox", title="AVSOX Title")
    b = _v("fc2", title="FC2 Title")
    merged = merge_results({"avsox": a, "fc2": b}, user_order=["javbus", "jav321"])
    # neither in user_order → insertion-order first = avsox
    assert merged.source == "avsox"
    assert merged.title == "AVSOX Title"


def test_empty_candidates_returns_none():
    """defensive: empty candidates → None (caller guards before merge)."""
    assert merge_results({}, user_order=["javbus"]) is None




def test_preview_cover_url_cleared_when_no_candidate_has_cover():
    """③`cover_winner is None`（**沒有任何候選有 cover_url**）→ preview 必須被明確清空。

    這是 T3b review 的 P2：該分支原本不寫 `updates['preview_cover_url']`，於是結果
    會**繼承 text_source 自己的 preview**。今天漏不出來，只因為 mapper 的
    `_build_preview_cover_url()` 在 cover 空時回 ''——但那是**別的模組**的不變式。
    merger 隱性依賴它，正是 CD-113c-12 要消滅的形狀。

    本測試刻意**繞過 mapper**、直接建一個違反該不變式的 `Video`（有 preview、無
    cover），確認 merger 這一層自己守得住，而不是靠上游剛好沒送出這種值。
    """
    leaky = _v("metatube:FANZA", title="MT Title", cover_url="",
               preview_cover_url="http://mt:8080/v1/images/primary/FANZA/X?url=y")
    other = _v("javbus", title="", cover_url="", preview_cover_url="")
    merged = merge_results({"metatube:FANZA": leaky, "javbus": other},
                           user_order=["metatube:FANZA", "javbus"])
    assert merged.cover_url == ""
    assert merged.preview_cover_url == "", (
        "沒有任何候選有封面時 preview 必須清空，不得從 text_source 漏出"
    )


# ---------------------------------------------------------------------------
# preview_sample_images 同源綁定（TASK-126-T2, CD-126-2／CD-113c-12 形狀）
# ---------------------------------------------------------------------------

def test_merge_preview_sample_images_follows_same_winner():
    """邊界 8：候選 A 有 sample_images（無 preview）、候選 B 有 sample＋preview，
    A 排前 → 兩欄都取 A（含 A 的空 preview），不得從 B 漏過來。"""
    a = _v(
        "javbus",
        title="JB Title",
        sample_images=["http://javbus/s1.jpg"],
        preview_sample_images=[],
    )
    b = _v(
        "metatube:FANZA",
        title="",
        sample_images=["http://mt/s1.jpg"],
        preview_sample_images=["http://mt:8080/v1/images/primary/FANZA/X?url=s1"],
    )
    merged = merge_results(
        {"javbus": a, "metatube:FANZA": b},
        user_order=["javbus", "metatube:FANZA"],
    )
    assert merged.sample_images == ["http://javbus/s1.jpg"]
    assert merged.preview_sample_images == []


def test_merge_preview_sample_images_positive_copies_winner_previews():
    """邊界 8b（**正向**）：勝出候選自己帶非空 preview_sample_images → merged 必須拿到那組值。

    Pre-merge mutation 自驗抓到的洞（`source_merger.py:139` SURVIVED）＋ SA-pre-6 獨立指到同一處：
    邊界 8 的斷言是 `preview_sample_images == []`，而該案例的勝出候選 preview 本來就是 `[]`——
    把那行賦值整個刪掉，值會從 text_source 沿用下來、**也是 `[]`**，測試照樣綠。
    封面那組有這支對稱的正向鎖（test_preview_cover_url_follows_cover_winner_when_metatube），
    劇照這組沒有。

    使用者流程：來源順序把 metatube 排第一 → 搜到一片、metatube 有劇照 → 若日後有人
    改壞這行，燈箱的劇照代理網址整組消失、退回冷門圖床 403 破圖，而測試全綠沒人發現。
    """
    previews = [
        "http://mt:8080/v1/images/primary/FANZA/X?url=s1",
        "http://mt:8080/v1/images/primary/FANZA/X?url=s2",
    ]
    javbus = _v("javbus", title="JB Title", sample_images=[], preview_sample_images=[])
    metatube = _v(
        "metatube:FANZA",
        title="",
        sample_images=["http://mt/s1.jpg", "http://mt/s2.jpg"],
        preview_sample_images=previews,
    )
    merged = merge_results(
        {"javbus": javbus, "metatube:FANZA": metatube},
        user_order=["javbus", "metatube:FANZA"],
    )
    # javbus 是 text_source（整包贏）但沒有劇照 → 劇照勝出候選是 metatube
    assert merged.sample_images == ["http://mt/s1.jpg", "http://mt/s2.jpg"]
    assert merged.preview_sample_images == previews, (
        "勝出候選帶非空 preview_sample_images 時，merged 必須取到該值（同源綁定的正向半邊）"
    )
    assert len(merged.preview_sample_images) == len(merged.sample_images), (
        "CD-126-2 等長契約"
    )


def test_merge_preview_sample_images_cleared_when_no_sample_winner():
    """邊界 9：無任何候選有 sample_images，但 text_source 有 preview_sample_images
    → preview_sample_images 明確清空為 []，不得從 text_source 漏出。"""
    leaky = _v(
        "metatube:FANZA",
        title="MT Title",
        sample_images=[],
        preview_sample_images=["http://mt:8080/v1/images/primary/FANZA/X?url=s1"],
    )
    other = _v("javbus", title="", sample_images=[], preview_sample_images=[])
    merged = merge_results(
        {"metatube:FANZA": leaky, "javbus": other},
        user_order=["metatube:FANZA", "javbus"],
    )
    assert merged.sample_images == []
    assert merged.preview_sample_images == [], (
        "沒有任何候選有劇照時 preview_sample_images 必須清空，不得從 text_source 漏出"
    )
