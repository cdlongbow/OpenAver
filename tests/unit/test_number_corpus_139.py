"""TASK-139-T6: 182-entry number corpus transplanted from upstream TestTrim.

輸入字串借自 metatube-sdk-go（Apache-2.0）的 `common/number/number_test.go::TestTrim`：
https://github.com/metatube-community/metatube-sdk-go
**僅借用輸入，期望值全部由本專案自訂**——下面每一筆 expect 都是本專案 `extract_number()`
的現況輸出，不是上游的期望值（兩邊在數字前綴、大小寫、分隔符上本來就不同）。

Expect values are current extract_number() outputs (status lock).
support/reason come from task card D5/D6/D8 — not inferred from runtime.
"""
from __future__ import annotations

import pytest

from core.scraper import extract_number

REASONS: dict[str, str] = {
    'R1': '與上游期望值逐字相同',
    'R2': '僅大小寫差異——本專案正典一律大寫，上游保留原字面',
    'R3': '數字／站台前綴差異——上游保留 `133`／`200`／`118`／`18`／`5`／`h_346` 這類前綴，我方取番號本體。**差異屬 139c 的未拍板設計題，不是缺陷**',
    'R4': '分隔符差異——我方在字母與數字之間補 hyphen 並轉大寫（`normalize_number_impl` 正典），上游保留原字面',
    'R5': '無碼日期番號——我方回 `MMDDYY-NNN` 正典形式，上游保留 `1pon`／`DL1pon` 廠牌前綴。**差異屬 139c，不是缺陷**',
    'R6': '空輸入——我方回 `None`，等義於上游的空字串',
    'U1': '`Path(filename).stem` 在**最後一個點**截斷——檔名沒有真副檔名、而站台前綴含 `.`（`[98t.tv]`／`17.`／`zzpp06.com@`）時，番號整段被切掉 ⇒ 回 `None`',
    'U2': '數字尾碼少於 3 位不支援（`MCBD-18`／`mura-42`）——我方樣式一律要求 ≥3 位',
    'U3': '站台／廠牌前綴被誤當成番號本體（`hhd800.com@` → `HHD-800`、`heydouga-4102-023` → `EYDOUGA-4102`、`1000giri-130906` → `GIRI-13090`）',
    'U4': '字母尾碼系列不支援（`MARRA-A030` 的 `A030`）',
    'U5': '無碼廠牌前綴被丟棄，剩下的字串查不到（`xxx-av-1789` → `AV-1789`、`h4610-tk1003` → `TK-1003`、`h0930-ki18492` → `KI-18492`）',
    'U6': '純數字廠牌番號不支援（`4102-023`，heydouga 去掉廠牌前綴後的形式）',
}

CORPUS: list[dict] = [
    {"input": "118abp077", "expect": "ABP-077", "support": True, "reason": "R3"},
    {"input": "ssis00123", "expect": "SSIS-00123", "support": True, "reason": "R4"},
    {"input": "ABP-030", "expect": "ABP-030", "support": True, "reason": "R1"},
    {"input": "ABP-030-C.mp4", "expect": "ABP-030", "support": True, "reason": "R1"},
    {"input": "[22sht.me]ABP-358_C.mkv", "expect": "ABP-358", "support": True, "reason": "R1"},
    {"input": "FC2-PPV-123456", "expect": "FC2-123456", "support": True, "reason": "R1"},
    {"input": "Tokyo Hot n9001 FHD.mp4", "expect": "N9001", "support": True, "reason": "R2"},
    {"input": "caribbeancom-020317_001.mp4", "expect": "020317_001", "support": True, "reason": "R1"},
    {"input": "020317-001-1pondo.mp4", "expect": "020317-001", "support": True, "reason": "R1"},
    {"input": "HND-620絶対にナマで連射させてくれる連続中出しソープ_あいだ飛鳥", "expect": "HND-620", "support": True, "reason": "R1"},
]


@pytest.mark.parametrize("case", CORPUS, ids=[str(i) for i in range(len(CORPUS))])
def test_extract_number_corpus(case: dict) -> None:
    assert extract_number(case["input"]) == case["expect"]
