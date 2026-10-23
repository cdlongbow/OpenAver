"""[lint-guard: pytest-justified] install.ps1／OpenAver-Windows-Setup.bat 是
PowerShell／batch 檔，不是 Python，也不是前端資產——現有 eslint／stylelint／
scripts/*.mjs 都不吃這兩種副檔名。比照 CD-145b-5 的 [lint-guard:ps1-i18n] 先例，
用 pytest 頂替 lint 的角色，驗 T6（QuickEdit 關閉）的承重語意。

與既有 tests/unit/test_installer_script_guard.py（TASK-120b-T3）互不重疊：
那支驗 Exit-WithPause／trap 的結構順序與裸 exit，完全不知道 QuickEdit 這件事；
這支只驗 QuickEdit 區塊本身，不重新驗證 trap 結構。
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_INSTALL_PS1 = _ROOT / "install.ps1"


def _ps1_lines() -> list[str]:
    return _INSTALL_PS1.read_text(encoding="utf-8").splitlines()


def test_newmode_line_sets_both_flags():
    """(2) 承重行：$newMode 必須同時清 QUICK_EDIT、設 EXTENDED_FLAGS。
    少設 EXTENDED_FLAGS：Win32 文件記載 SetConsoleMode 會整次忽略這兩個旗標，
    等於使用者點一下黑視窗、安裝照樣被凍住——F1 沒有真的修好。
    """
    lines = _ps1_lines()
    newmode_lines = [l for l in lines if re.search(r"\$newMode\s*=", l)]
    assert len(newmode_lines) == 1, f"應該恰好一行 $newMode 賦值，找到 {len(newmode_lines)} 行"
    line = newmode_lines[0]
    # 鎖定運算元配對：-bnot 必須緊接 $ENABLE_QUICK_EDIT_MODE 且被 -band 消費；
    # -bor 必須緊接 $ENABLE_EXTENDED_FLAGS。四個 token 散落同列不算過關。
    assert re.search(
        r"-band\s*\(\s*-bnot\s+\$ENABLE_QUICK_EDIT_MODE\s*\)",
        line,
    ), f"$newMode 那一行沒有以 -band (-bnot $ENABLE_QUICK_EDIT_MODE) 清除 QUICK_EDIT：{line}"
    assert re.search(
        r"-bor\s+\$ENABLE_EXTENDED_FLAGS",
        line,
    ), f"$newMode 那一行沒有以 -bor $ENABLE_EXTENDED_FLAGS 設定 EXTENDED_FLAGS：{line}"


def test_quickedit_wrapped_in_try_catch():
    """(4) 整段被 try { ... } catch {} 包住，失敗吞掉不觸發 trap。"""
    text = "\n".join(_ps1_lines())
    m = re.search(
        r"try\s*\{.*?ENABLE_QUICK_EDIT_MODE.*?SetConsoleMode\(.*?\}\s*catch\s*\{\}",
        text,
        re.DOTALL,
    )
    assert m is not None, "QuickEdit 區塊必須整段包在 try { ... } catch {} 裡"


