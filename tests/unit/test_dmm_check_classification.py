"""Pure-function tests for scripts/dmm_prefix_table_check.py (TASK-134b-T7).

No network. Feeds synthetic cids / prefix maps / _meta into the classification
and report helpers.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import dmm_prefix_table_check as check  # noqa: E402


# ── parse_cid ─────────────────────────────────────────────────────────────────


def test_parse_cid_with_h_prefix():
    assert check.parse_cid("h_1711sioz00004") == ("h_1711", "sioz", "00004")


def test_parse_cid_with_numeric_dmm_prefix():
    assert check.parse_cid("1svvrt00087") == ("1", "svvrt", "00087")


def test_parse_cid_empty_observed_dmm_prefix():
    """Default-rule cids (ymlw / vrkm) — observed_dmm_prefix is empty."""
    assert check.parse_cid("ymlw00075") == ("", "ymlw", "00075")
    assert check.parse_cid("vrkm01909") == ("", "vrkm", "01909")


def test_parse_cid_inconclusive_non_match():
    assert check.parse_cid("!!!not-a-cid!!!") is None
    assert check.parse_cid("") is None


# ── classify：兩桶／空 observed／inconclusive ──────────────────────────────────


def test_empty_observed_not_in_any_bucket():
    """DoD 4：observed_dmm_prefix 為空者不進任何一桶。"""
    prefix_map = {"sioz": "h_1711"}
    cids = [
        "ymlw00075",       # empty observed → skip
        "vrkm01909",       # empty observed → skip
        "h_1711sioz00004", # need prefix, in table
        "1svvrt00087",     # need prefix, not in table
    ]
    result = check.classify_cids(cids, prefix_map)

    assert result.bucket_a_denom == 2  # sioz, svvrt only
    assert set(result.bucket_a_prefixes) == {"sioz", "svvrt"}
    assert ("svvrt", "1svvrt00087") in result.bucket_a_missing
    assert ("sioz", "h_1711sioz00004") not in result.bucket_a_missing
    assert result.bucket_b_denom == 1  # only sioz is in the table
    assert result.bucket_b_correct == 1
    assert result.default_rule_count == 2
    assert result.inconclusive_count == 0


def test_inconclusive_not_in_denominator():
    prefix_map = {"sioz": "h_1711"}
    cids = ["!!!bad!!!", "h_1711sioz00004"]
    result = check.classify_cids(cids, prefix_map)

    assert result.inconclusive_count == 1
    assert result.bucket_a_denom == 1
    assert result.bucket_a_prefixes == ["sioz"]


def test_bucket_b_mismatch_counts_as_incorrect():
    """Table value differs from observed_dmm_prefix → not correct."""
    prefix_map = {"sioz": "h_9999"}  # wrong value
    cids = ["h_1711sioz00004"]
    result = check.classify_cids(cids, prefix_map)

    assert result.bucket_a_denom == 1
    assert result.bucket_a_missing == []
    assert result.bucket_b_denom == 1
    assert result.bucket_b_correct == 0


def test_bucket_a_distinct_prefixes_not_sample_count():
    """Same prefix appearing twice counts once in bucket A denom."""
    prefix_map = {"sioz": "h_1711"}
    cids = ["h_1711sioz00004", "h_1711sioz00005"]
    result = check.classify_cids(cids, prefix_map)
    assert result.bucket_a_denom == 1
    assert result.bucket_b_denom == 1


# ── days_since_crawl（D6 / DoD 5）─────────────────────────────────────────────


def test_days_since_reads_crawl_date_not_corrected():
    """DoD 5 / M2：天數對應 crawl_date，不是 corrected。"""
    meta = {"corrected": "2026-08-29", "count": 164, "crawl_date": "2026-07-03"}
    today = date(2026, 8, 29)
    # crawl_date 2026-07-03 → 2026-08-29 = 57 days
    assert check.days_since_crawl(meta, today) == 57
    # If someone read corrected instead, days would be 0 — lock that out.
    assert check.days_since_crawl(meta, today) != 0


# ── format_report：樣本空／分母 0（DoD 2 / DoD 3）─────────────────────────────


def test_empty_samples_no_percentage_dod2():
    """DoD 2 / M1：樣本空 → 失敗訊息、不含 %、可當 stdout 斷言。"""
    report = check.format_report(
        cids=[],
        prefix_map={"sioz": "h_1711"},
        crawl_date="2026-07-03",
        today=date(2026, 8, 29),
        fetch_failed=False,
    )
    assert "樣本取得失敗，體檢無法進行" in report
    assert "%" not in report
    assert "VPN" not in report


def test_fetch_failed_no_percentage_dod2():
    """DoD 2：請求非 200（fetch_failed=True）同樣不印百分比。"""
    report = check.format_report(
        cids=["h_1711sioz00004"],  # even with cids present, fetch_failed wins
        prefix_map={"sioz": "h_1711"},
        crawl_date="2026-07-03",
        today=date(2026, 8, 29),
        fetch_failed=True,
    )
    assert "樣本取得失敗，體檢無法進行" in report
    assert "%" not in report
    assert "VPN" not in report


def test_bucket_a_denom_zero_no_percentage_dod3():
    """DoD 3：桶 A 分母為 0（全是 empty observed）→ 樣本不可用、不印 %。"""
    report = check.format_report(
        cids=["ymlw00075", "vrkm01909"],
        prefix_map={"sioz": "h_1711"},
        crawl_date="2026-07-03",
        today=date(2026, 8, 29),
        fetch_failed=False,
    )
    assert "樣本不可用" in report
    assert "%" not in report
    assert "VPN" not in report


def test_bucket_a_denom_zero_all_inconclusive():
    """DoD 3：全部正則不匹配 → 同樣樣本不可用。"""
    report = check.format_report(
        cids=["!!!", "???"],
        prefix_map={},
        crawl_date="2026-07-03",
        today=date(2026, 8, 29),
        fetch_failed=False,
    )
    assert "樣本不可用" in report
    assert "%" not in report


def test_normal_report_prints_bucket_a_list_and_bucket_b_pct():
    """Happy path：桶 A 印清單（無門檻％）、桶 B 印百分比與達標。"""
    prefix_map = {"sioz": "h_1711"}
    cids = [
        "ymlw00075",
        "h_1711sioz00004",
        "1svvrt00087",
    ]
    report = check.format_report(
        cids=cids,
        prefix_map=prefix_map,
        crawl_date="2026-07-03",
        today=date(2026, 8, 29),
        fetch_failed=False,
    )
    # Bucket A: list missing prefixes with sample cid — NO A-threshold.
    assert "svvrt → 1svvrt00087" in report
    missing_block = report.split("不在出貨表裡")[1].split("【桶 B")[0]
    assert "sioz" not in missing_block  # sioz is in the table → not listed
    # D7：桶 A 區塊**完全不得**出現任何門檻字樣。
    # ⚠️ 2026-08-29 review（grok P3-3）：原本只斷言 `"門檻 10%" not in report`，
    #    擋不住有人加回「門檻 15%」或全形「門檻 10％」。改成鎖整個桶 A 區塊沒有「門檻」二字。
    bucket_a_block = report.split("【桶 A")[1].split("【桶 B")[0]
    assert "門檻" not in bucket_a_block, f"桶 A 不得有門檻（D7）：{bucket_a_block}"
    assert "%" not in bucket_a_block, f"桶 A 不印百分比，只印清單（D7）：{bucket_a_block}"
    # Bucket B: 1/1 = 100% ≥ 95%
    assert "%" in report
    # ⚠️ 2026-08-29 review（grok P3-1）：`"達標" in report` 是空殼——
    #    「達標」是「未達標」的子字串，verdict 永遠印「未達標」時它照樣綠。
    assert "：達標" in report
    assert "未達標" not in report
    assert "crawl_date=2026-07-03" in report
    assert "57" in report
    assert "VPN" not in report


def test_bucket_b_below_threshold_marked():
    prefix_map = {"sioz": "h_9999", "svvrt": "9"}  # both wrong
    cids = ["h_1711sioz00004", "1svvrt00087"]
    report = check.format_report(
        cids=cids,
        prefix_map=prefix_map,
        crawl_date="2026-07-03",
        today=date(2026, 8, 29),
        fetch_failed=False,
    )
    assert "未達標" in report


def test_bucket_b_denom_zero_skips_rate_without_crashing():
    """桶 A 分母 > 0、但**一個前綴都不在表裡** ⇒ 桶 B 分母為 0。

    ⚠️ 2026-08-29 review（sonnet P1）：這條分支原本**拿掉也沒有測試會紅**
    （把 `if result.bucket_b_denom == 0:` 改成 `if False:` 後 17 條全綠）。
    而它正是**表最過期、最需要示警**的那個情境——樣本裡需要前綴的片，
    一個都算不出來。那時候腳本反而 `ZeroDivisionError` 崩掉、印 traceback、
    以非 0 exit code 結束，直接違反 D1「無論命中率高低一律 exit 0」。

    使用者流程：owner 在 release 前跑這支兩分鐘體檢 → 表已經很舊 →
    **他拿不到報告，只拿到一個 traceback**，還得自己判斷能不能忽略。
    """
    report = check.format_report(
        cids=["h_1711sioz00004", "1svvrt00087"],
        prefix_map={},  # 表是空的 ⇒ 桶 A 分母 2、桶 B 分母 0
        crawl_date="2026-07-03",
        today=date(2026, 8, 29),
        fetch_failed=False,
    )
    assert "無表內前綴可驗，略過正確率" in report
    # 不得印任何正確率百分比（沒有分母就沒有比率可言）
    bucket_b_block = report.split("【桶 B")[1]
    assert "%" not in bucket_b_block, f"桶 B 分母為 0 卻印了百分比：{bucket_b_block}"
    assert "達標" not in bucket_b_block


# ── sys.exit(0) 顯式（DoD 6）───────────────────────────────────────────────────


def test_sys_exit_zero_explicit_in_source():
    """DoD 6：原始碼必須顯式 sys.exit(0)。"""
    src = Path(check.__file__).read_text(encoding="utf-8")
    assert "sys.exit(0)" in src


def test_run_check_always_exits_zero_on_empty(capsys):
    """DoD 6：數字再差也是 exit 0。"""
    with pytest.raises(SystemExit) as exc:
        check.run_check(
            fetch_samples=lambda: [],
            load_prefix_map=lambda: {},
            load_meta=lambda: {
                "crawl_date": "2026-07-03",
                "corrected": "2026-08-29",
            },
            today=date(2026, 8, 29),
        )
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "%" not in out
    assert "樣本取得失敗，體檢無法進行" in out


def test_run_check_exits_zero_even_when_below_threshold(capsys):
    """DoD 6 的另一半：**數字難看的時候**也必須 exit 0（非 exit-code gate）。

    ⚠️ 2026-08-29 review（grok P3-2）：原本只有「空樣本」那條路徑驗過 exit 0。
    在 `run_check` 裡加一句「未達標就 raise SystemExit(1)」後，17 條全綠——
    也就是說「日後有人把它改成 gate」不會被任何測試擋住，而 CD-134-8 明文禁止那件事。
    """
    with pytest.raises(SystemExit) as exc:
        check.run_check(
            fetch_samples=lambda: ["h_1711sioz00004", "1svvrt00087"],
            load_prefix_map=lambda: {"sioz": "h_9999", "svvrt": "9"},  # 兩個都錯
            load_meta=lambda: {
                "crawl_date": "2026-07-03",
                "corrected": "2026-08-29",
            },
            today=date(2026, 8, 29),
        )
    assert exc.value.code == 0, "命中率再差也不得以非 0 結束（CD-134-8：非 exit-code gate）"
    out = capsys.readouterr().out
    assert "未達標" in out


# ── fetch_latest_cids 的例外收斂（2026-08-29 Codex P3）────────────────────────


@pytest.mark.parametrize(
    "exc_name",
    ["TooManyRedirects", "ChunkedEncodingError", "ContentDecodingError", "RetryError"],
)
def test_fetch_latest_cids_swallows_all_requests_exceptions(monkeypatch, exc_name):
    """任何 requests 例外都要收斂成 (None, True)，不得 traceback。

    原本只攔 (Timeout, ConnectionError)。其餘 RequestException 子類會直接冒出去 →
    腳本 traceback ＋ 非零離開 → 使用者分不出「腳本自己失敗」與「表過期」，
    而那正是 CD-134-8 明文要求要能分辨的兩件事。
    這幾個都是真的會發生的：DMM 對沒 VPN 的請求重導到封鎖頁 = TooManyRedirects。
    """
    import requests

    exc_cls = getattr(requests.exceptions, exc_name)
    assert issubclass(exc_cls, requests.RequestException)
    assert not issubclass(exc_cls, (requests.Timeout, requests.ConnectionError)), (
        f"{exc_name} 若本來就是舊 except 的子類，這條測試證明不了任何事"
    )

    def _boom(*args, **kwargs):
        raise exc_cls("simulated")

    monkeypatch.setattr(requests.Session, "post", _boom)
    assert check.fetch_latest_cids() == (None, True)


# ── 出貨表讀不起來也要 exit 0（2026-08-29 branch review P3）────────────────────


@pytest.mark.parametrize(
    "exc",
    [ValueError("跨片商撞名：abc（MakerA / MakerB）"), KeyError("crawl_date")],
)
def test_run_check_exits_zero_when_table_loader_raises(capsys, exc):
    """`_prefix_map()` 對撞名**刻意**拋 ValueError、`_meta` 缺欄位是 KeyError。

    這兩條真路徑原本沒有被 `run_check` 接住 ⇒ traceback ＋ 非零離開 ⇒
    使用者分不出「腳本自己壞了」與「表過期了」，而 CD-134-8 要求這兩件事
    在輸出上分得出來。既有的 exit-0 測試全部走注入版 loader，踩不到這條。
    """

    def _boom():
        raise exc

    with pytest.raises(SystemExit) as got:
        check.run_check(
            fetch_samples=lambda: ["h_1711sioz00004"],
            load_prefix_map=_boom,
            load_meta=lambda: {"crawl_date": "2026-07-03"},
            today=date(2026, 8, 29),
        )
    assert got.value.code == 0
    out = capsys.readouterr().out
    assert "出貨表讀取失敗" in out
    assert "不代表表過期" in out
    assert "%" not in out, "讀不到表就不得印任何百分比"
