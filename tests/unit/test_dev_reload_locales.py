"""#7 的兩支守衛：dev server 的 locale hot-reload 旗標。

沒有這個旗標時：改了 `locales/*.json` 之後，長跑中的 dev server 會一直渲染舊字
——熱重載預設只監看 `.py`、不監看 JSON，而 `core/i18n.py` 的 `load_locale()` 又是
`@lru_cache` 且無 mtime 檢查。畫面上看起來像 i18n key 沒生效，實際只是需要手動重啟。

⚠️ **本檔的散文若同時出現 `uvicorn` 與獨立的重載旗標字面，會被下面的 sweep 掃到**
——那時它必須也帶著 `--reload-include 'locales/*.json'`，否則 `invalid_flag_lines`
會紅（`RELOAD_RE` 刻意拆成兩段字面就是為了自己不中獎）。
127b-T6 改寫本 docstring 時原地踩了一次：全套只紅這一支。

# [lint-guard: pytest-justified] 掃描標的是 run.sh（shell）與四份 Markdown，
# 不是 HTML/JS/CSS ⇒ 落在 eslint/stylelint/scripts/*.mjs 的射程之外；且對帳鎖與行為鎖
# 共用同一組正規式常數，拆成兩種語言等於製造兩份會漂的判準。比照 tests/unit/ 既有的
# boundary guard 慣例留在 pytest。
"""
from pathlib import Path
import re
import subprocess
import pytest

try:
    import watchfiles  # noqa: F401
except ImportError:
    pytest.fail("watchfiles is required for --reload-include glob support, but it is not installed")

from uvicorn.config import Config
from uvicorn.supervisors.watchfilesreload import FileFilter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RELOAD_RE = re.compile(r"(?<![\w-])--re" + r"load(?![-\w])")
INCLUDE_RE = re.compile(r"--reload-include\s+(['\"]?)([^'\"\s`]+)\1")


def test_run_sh_reload_include_accepts_locale_json():
    run_sh_path = REPO_ROOT / "run.sh"
    content = run_sh_path.read_text(encoding="utf-8")

    # 錨點：先挑出 run.sh 裡的啟動指令行（判準見 RELOAD_RE），並斷言恰好一行。
    # 不用整檔 first-match（FE-GUARD-07：.index()/first-match 會靜默錨到別的地方）。
    #
    # ⚠️ 本檔的註解與字串都不得同時出現「uvicorn」與獨立的旗標字面——
    #    對帳鎖掃全部追蹤檔（含本檔），寫進去就會變成第 6 個命中。
    #    不准為此加排除清單（CD-127b-8：白名單為空），一律拆字面。
    launch_lines = [
        line
        for line in content.splitlines()
        if "uvicorn" in line and RELOAD_RE.search(line)
    ]
    assert len(launch_lines) == 1, (
        f"run.sh 應有且只有 1 行 uvicorn 啟動指令，實際 {len(launch_lines)} 行：\n"
        + "\n".join(launch_lines)
    )

    match = INCLUDE_RE.search(launch_lines[0])
    reload_includes = [match.group(2)] if match else []

    config = Config("web.app:app", reload=True, reload_includes=reload_includes)
    file_filter = FileFilter(config)

    assert file_filter(Path("locales/zh_TW.json")) is True, (
        "FileFilter rejected locales/zh_TW.json (reload_includes was: "
        f"{reload_includes})"
    )
    assert file_filter(Path("web/app.py")) is True, (
        "FileFilter rejected web/app.py"
    )


def test_all_tracked_uvicorn_reload_lines_carry_the_flag():
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception as exc:
        pytest.fail(f"Failed to run git ls-files: {exc}")

    tracked_files = [REPO_ROOT / f for f in proc.stdout.splitlines() if f.strip()]

    matched_lines = []
    invalid_flag_lines = []

    for file_path in tracked_files:
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            if "uvicorn" in line and RELOAD_RE.search(line):
                rel_path = file_path.relative_to(REPO_ROOT)
                loc_str = f"{rel_path}:{lineno}"
                matched_lines.append((loc_str, line))

                inc_match = INCLUDE_RE.search(line)
                if not inc_match or inc_match.group(2) != "locales/*.json":
                    invalid_flag_lines.append(loc_str)

    # ⚠️ 刻意**不釘死基數**：不合規的新增由下面的 invalid_flag_lines 擋住，
    # 所以 `== N` 只會在「合規的新增」上開火 ＝ 純摩擦（127b-T6 與 0.14.7 pre-merge
    # 各中過一次）。這裡只確保 sweep 真的有掃到東西（正規式壞掉時會歸零）。
    assert matched_lines, (
        "Found no line matching uvicorn + reload in tracked files — "
        "the sweep regex is probably broken (it should match at least run.sh)."
    )

    assert not invalid_flag_lines, (
        f"The following {len(invalid_flag_lines)} line(s) matched uvicorn + reload but are missing "
        f"--reload-include 'locales/*.json':\n"
        + "\n".join(invalid_flag_lines)
    )
