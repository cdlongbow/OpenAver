"""CI workflow contract guards (TASK-78-T3 / feature/78).

防止 `.github/workflows/test.yml` 的 lint-frontend job 被靜默移除——lint 守衛
（eslint + stylelint + ruff）必須在 CI 跑才 load-bearing（翻 reference_ci_no_eslint
前提）。解析 YAML 後檢查語意，不依賴 attribute 順序。

pin-drift parity 守衛（requirements-test.txt 與 CI lint-frontend step 的 ruff /
import-linter 版本一致性）留在 pytest（TASK-110b-T9，回退 Codex PR #122
round-2 把它遷去 lint 的方向；round-5 補強命令級解析）：本守衛須終結兩層語法，
`yaml.safe_load` 與命令級解析各自負責一層。

YAML 層：只取 lint-frontend job 底下各 step 的 `run` scalar **值**，區分
`run:` 這個 mapping key 與同檔案裡的註解、`name:`、`if:` 或其他 key。
static_guard_lint 是原始位元組流的 regex 引擎，做不到這件事——PR #122
round-2→4 已用真引擎逐輪實測：每一種 regex 近似要嘛留下假綠（pin 漂移到
註解或其他欄位仍判過），要嘛製造假紅（合法的 `run: |` 區塊寫法或加 flag
被誤判紅）。`yaml.safe_load` 終結的是這一層，不是全部。

shell 層：YAML parse 只把 `run: |` block scalar 讀成一段**字串**，字串內文
是 shell script——裡面的 `#` 是 shell 註解、不是 YAML 註解，YAML parser
不會（也不該）替你濾掉；同一個 scalar 也可能有多次 `pip install`，實際生效
的是最後裝的那個。round-2→4 的守衛把所有 run scalar `" ".join()` 後直接
`re.search` 抓第一個版本，於是「`pip install ruff` 下方留一行
`# legacy: pip install ruff==0.15.17`」這種形狀被誤判成有釘版（round-5，
Codex 對 staged T9 的 P1）。`_pip_installs()` 補上 shell 層：併行接續、逐行剝
shell 註解、依 `&&`/`||`/`;`/`|` 切命令段、略過 `do`/`then`/`sudo` 這類段首
前綴，然後回傳**全部**（非僅第一個）安裝，而不是只回傳第一個版本。

**關鍵是「認不得就明講認不得」，不是「認得越多越好」**（round-6，Codex 對
staged T9 的 P1）：一個解析器永遠會有不認得的安裝寫法，而「不認得」只有在
它是**唯一**安裝時才安全地變成 RED——前面若已有一個合法 pin，不認得的後續
安裝就直接消失在視野外 ＝ 假綠，正是這一連串 round 要消滅的形狀本身。所以
`_pip_installs()` 回傳兩個欄位：可完整辨識的安裝（`versions`）與**提到該
工具、看起來在安裝、但無法完整辨識**的命令段（`unparsed`），後者非空即 RED。

**封掉的假綠**：pin 只存在於註解（YAML 層或 shell 層皆然）、pin 在別的 key
／別的 job、同一 job 內多次安裝只看第一次、夾帶一次未釘版安裝覆蓋掉釘版、
把安裝藏進單行 `for … ; do … ; done`、用解析器不認得的安裝器（`uv` /
`poetry` / 包裝腳本）覆蓋掉釘版。
**看不見的**：安裝命令完全不提工具名字時（`bash scripts/setup.sh` 內部去裝）
——靜態讀 workflow 的任何做法都偵測不到，那是這個做法本身的邊界。
這裡不宣稱「終結整個語法家族」：那正是 round-2→5 每一輪都在犯的錯。
"""

import re
from pathlib import Path
from typing import NamedTuple

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "test.yml"
_REQUIREMENTS = _REPO_ROOT / "requirements-test.txt"
_REQUIREMENTS_RUNTIME = _REPO_ROOT / "requirements.txt"


@pytest.fixture(scope="module")
def workflow():
    assert _WORKFLOW.exists(), f"CI workflow 不存在：{_WORKFLOW}"
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _run_commands(job: dict) -> list[str]:
    """收集 job 內所有 step 的 `run` 字串（block scalar 多行也含）。"""
    return [step["run"] for step in job.get("steps", []) if isinstance(step, dict) and "run" in step]


# `[\d.]*` 而非 `\d*`：`pip3.12` / `python3.12 -m pip` 是真實會出現的寫法
# （round-6，Codex 具名指出）。認不得它們不是「安全的 RED」——見 _pip_installs 的
# fail-closed 說明。
_PIP_CMD_RE = re.compile(r"^pip[\d.]*$")
_PYTHON_CMD_RE = re.compile(r"^python[\d.]*$")

# 命令段開頭可被略過的 shell 前綴：控制流關鍵字與不改變「這段在跑什麼」的包裝命令。
# 少了它，`for i in 1; do pip install ruff; done` 會被切成 `for i in 1` / `do pip install
# ruff` / `done`，第二段的 tokens[0] 是 `do` → 整段被丟掉（連 None 都不記）＝**假綠**：
# CI 真的會跑那次未釘版安裝、覆蓋掉先前的釘版，守衛卻看不見（round-5 review 實測）。
_SHELL_PREFIX_TOKENS = frozenset({"then", "do", "else", "elif", "!", "time", "sudo", "command", "exec"})

# 判定「這段像不像在裝東西」用的動詞（pip/uv/poetry/pipx 共通）。只在**未能完整辨識**
# 的命令段上使用，用來決定要不要 fail-closed，不用來解析版本。
_INSTALL_VERBS = frozenset({"install", "add"})


class _Installs(NamedTuple):
    """`versions`：每一次**可完整辨識**的安裝（版本字串，或 None＝未釘版）。
    `unparsed`：提到該 tool、看起來在安裝、但**無法完整辨識**的命令段原文。

    兩者必須一起看。只看 `versions` 正是 round-6 被指出的假綠：前面有一個合法
    pin、後面跟一個解析器不認得的安裝命令時，`versions` 只有那個合法 pin，四道
    斷言全過，但 CI 實際跑的是後面那個。
    """

    versions: list[str | None]
    unparsed: list[str]


# 外層要剝掉的引號與 shell grouping 標點。`ruff)` / `` ruff` `` / `$(pip` 這些形狀若不剝，
# 名字比對就對不上——而它們**明確提到了 tool**，屬於必須被 unparsed 收下的可疑命令，
# 不是文件聲明的「命令完全沒提 tool」那條不可見邊界（round-7，Codex 具名 `(pip install ruff)`）。
_SHELL_WRAPPER_CHARS = "'\"()`{}$"


def _norm_pkg_name(arg: str) -> str:
    """參數 → 正規化套件名（比照本檔既有 `_direct_pkgs()`）。

    先剝外層引號與 shell grouping 標點：`'ruff==9.9.9'` 會正規化成 `'ruff`
    （round-6 實測的假綠之一）、`(pip install ruff)` 的 `ruff)` 會正規化成
    `ruff)`（round-7 實測的假綠），兩者都因為名字對不上而整段消失。
    """
    stripped = arg.strip(_SHELL_WRAPPER_CHARS)
    return re.split(r"[=<>!~\[]", stripped, maxsplit=1)[0].strip().lower().replace("_", "-")


def _logical_lines(run: str) -> list[str]:
    """把 shell 行接續（行尾 `\\`）併成邏輯行後再回傳。

    不併的話 `pip install \\` / `  ruff==9.9.9` 會被拆成「無參數的 pip install」
    與「不含 install 動詞的裸 spec」，兩段都不會被記錄 → 前面若有合法 pin 就是
    假綠（round-6）。
    """
    lines: list[str] = []
    buf = ""
    for raw in run.splitlines():
        stripped = raw.rstrip()
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
            continue
        lines.append(buf + raw)
        buf = ""
    if buf:
        lines.append(buf)
    return lines


def _pip_installs(job: dict, tool: str) -> _Installs:
    """從 job 全部 run scalar 辨識**每一次**安裝 `tool` 的命令。

    回傳 `_Installs(versions, unparsed)`——**兩個欄位必須一起檢查**，理由見
    `_Installs` 的 docstring。

    解析步驟：

    1. 逐個 run scalar → 先併行接續（`_logical_lines`）→ 逐行剝 shell 註解
       （`#` 之後，於任何其他處理前）
    2. 每行依 `&&` / `||` / `;` / `|` 切成命令段，逐段判斷
    3. 段首略過 `_SHELL_PREFIX_TOKENS`（`do` / `then` / `sudo` …），否則單行
       控制流會把命令藏起來
    4. 完整辨識：開頭是 `pip[X.Y] install` 或 `python[X.Y] -m pip install`
       → 逐參數用 `_norm_pkg_name()` 比名字，命中則 `==` 有記版本、無記 `None`
    5. **無法完整辨識但可疑者一律 fail-closed**：該段沒被 4 認出來，卻同時
       (a) 有 `_INSTALL_VERBS` 裡的動詞、(b) 某個參數正規化後就是 `tool`
       → 原文進 `unparsed`。`uv pip install ruff`、`poetry add ruff`、subshell
       （`(pip install ruff)` / `$(…)` / backtick）、任何包裝腳本都落在這裡。
       **subshell 形式刻意不解析、只 fail-closed**：猜它在裝什麼比直說「認不得」
       更危險，而 fail-closed 的成本只是要求作者把寫法補進本函式。

    round-6（Codex 對 staged T9 的 P1）：前一版把「解析器不認得的安裝寫法」
    寫成「一律往 RED 方向失效」——**那只在該命令是唯一安裝時成立**。前面若
    已經有一個合法 pin，`versions` 就有值、四道斷言全過，而 CI 實際跑的是
    後面那個不認得的安裝 ＝ 假綠，正是本輪要消滅的形狀本身。所以規則不是
    「認得越多越好」，而是**認不得就明講認不得**（步驟 5），讓「job 內所有
    安裝都受檢」這句話真的成立。

    **仍然看不見的東西**（誠實邊界，不宣稱終結）：安裝命令若完全不提 `tool`
    的名字——例如 `bash scripts/setup.sh` 或 `curl … | sh` 內部去裝——靜態讀
    workflow 的任何做法都偵測不到。這不是本函式的缺口，是「讀 YAML」這個
    做法的邊界；真要防得靠 CI 執行期回報實際版本。
    """
    versions: list[str | None] = []
    unparsed: list[str] = []
    for run in _run_commands(job):
        for raw_line in _logical_lines(run):
            line = raw_line.split("#", 1)[0]
            if not line.strip():
                continue
            for segment in re.split(r"&&|\|\||;|\|", line):
                tokens = segment.split()
                while tokens and tokens[0] in _SHELL_PREFIX_TOKENS:
                    tokens = tokens[1:]
                if not tokens:
                    continue
                if _PIP_CMD_RE.match(tokens[0]) and len(tokens) >= 2 and tokens[1] == "install":
                    args = tokens[2:]
                elif (
                    _PYTHON_CMD_RE.match(tokens[0])
                    and len(tokens) >= 4
                    and tokens[1] == "-m"
                    and tokens[2] == "pip"
                    and tokens[3] == "install"
                ):
                    args = tokens[4:]
                else:
                    # 未完整辨識：只要「像在裝東西」且「提到這個 tool」就 fail-closed。
                    # `ruff check .` 提到 tool 但無安裝動詞 → 不誤報。
                    if _INSTALL_VERBS.intersection(tokens) and any(
                        _norm_pkg_name(t) == tool for t in tokens
                    ):
                        unparsed.append(segment.strip())
                    continue
                for arg in args:
                    if _norm_pkg_name(arg) != tool:
                        continue
                    spec = arg.strip("'\"")
                    versions.append(spec.split("==", 1)[1].strip() if "==" in spec else None)
    return _Installs(versions=versions, unparsed=unparsed)


def test_test_job_still_present(workflow):
    """既有 pytest job 不可被誤刪。"""
    jobs = workflow["jobs"]
    assert "test" in jobs, "既有 test (pytest) job 消失了"
    runs = " ".join(_run_commands(jobs["test"]))
    assert "pytest" in runs, "test job 不再跑 pytest"


def test_lint_frontend_job_exists(workflow):
    assert "lint-frontend" in workflow["jobs"], "CI 缺 lint-frontend job（lint 守衛未進 CI）"


def test_lint_frontend_runs_npm_lint_and_ruff(workflow):
    """lint job 必須跑 npm run lint（eslint+stylelint）與 ruff check。"""
    runs = " ".join(_run_commands(workflow["jobs"]["lint-frontend"]))
    assert "npm ci" in runs, "lint-frontend 未跑 npm ci（無可重現安裝）"
    assert "npm run lint" in runs, "lint-frontend 未跑 npm run lint（eslint+stylelint）"
    assert "ruff check" in runs, "lint-frontend 未跑 ruff check"


def test_lint_frontend_is_independent(workflow):
    """lint-frontend 與 test 平行（無 needs），任一紅各自擋 PR。"""
    assert "needs" not in workflow["jobs"]["lint-frontend"], "lint-frontend 不應依賴其他 job（平行擋 PR）"


# [lint-guard: pytest-justified 需 YAML 語意＋命令級解析（只取 lint-frontend job 的
# run scalar 值，並在 shell 層逐行辨識真正的 pip install 命令）——static_guard_lint
# 是 raw-text regex 引擎：YAML 層分不出 run: key 與註解/name:/if:/block-scalar 內文，
# shell 層更分不出 block scalar 內文裡的 shell 註解、多次 pip install、未釘版安裝，
# 也無從表達「這段我認不得，所以 fail-closed」這個判斷；PR #122 round-2→6 實證每種
# regex 近似都留假綠或製造假紅 | migrate → 無（除非 lint 端同時引入 YAML parser 與
# shell 命令解析）]
@pytest.mark.parametrize(
    "tool",
    [
        pytest.param("ruff", id="ruff"),
        pytest.param("import-linter", id="import-linter"),
    ],
)
def test_ci_ruff_pin_matches_requirements(workflow, tool):
    """CI 的 <tool> pin 必須與 requirements-test.txt 一致——

    pip `-c` constraints 無法消費含 extras 的 requirements-test.txt（uvicorn[standard]
    → pip 拒絕），故版本必須在兩處各寫一次（CI step + requirements）。本守衛把
    這個「兩處重複」鎖成 single source of truth：任一漂移即 RED，防 upstream 套件
    自動升級或人為忘記同步在 repo 無改動下讓 CI 轉紅。

    TASK-110a-T5：本測試現以 `tool` 參數化，同時涵蓋 `ruff` 與 `import-linter`
    兩個被「requirements-test.txt + CI step」各釘一次版本的工具；node 名稱保留
    `test_ci_ruff_pin_matches_requirements`（不改名，AC7 逐字指名此 node）。

    round-5：改用 `_pip_installs()` 取得 lint-frontend job 內**全部**命中的
    pip install（不是只取第一個 `re.search`），依序做四道 fail-closed 斷言。
    """
    pattern = re.escape(tool) + r"==(\S+)"
    req_match = re.search(rf"^{pattern}", _REQUIREMENTS.read_text(encoding="utf-8"), re.MULTILINE)
    assert req_match, f"requirements-test.txt 缺 `{tool}==<version>` 精確 pin（lint 是 PR gate，需鎖版本）"
    req_version = req_match.group(1).split("#")[0].strip()

    installs = _pip_installs(workflow["jobs"]["lint-frontend"], tool)
    assert not installs.unparsed, (
        f"CI lint-frontend 有提到 {tool} 且看起來在安裝、但本守衛無法完整辨識的命令："
        f"{installs.unparsed}。fail-closed：無法辨識就不能宣稱「所有安裝都受檢」"
        f"（有先前的合法 pin 時這正是假綠的來源）。請把該寫法補進 `_pip_installs()`，不要放寬斷言"
    )
    versions = installs.versions
    assert versions, (
        f"CI lint-frontend 未偵測到任何 `pip install {tool}`（未以 `{tool}==<version>` 精確 pin 安裝）"
    )
    assert None not in versions, (
        f"CI lint-frontend 含未釘版的 `pip install {tool}`（無 `==`），會覆蓋掉先前的釘版安裝："
        f"實際命中序列 {versions}"
    )
    distinct_versions = set(versions)
    assert len(distinct_versions) == 1, (
        f"CI lint-frontend 同一 job 內有多個不同的 {tool} 釘版 {sorted(distinct_versions)}，"
        f"後裝的會覆蓋先裝的：實際命中序列 {versions}"
    )
    ci_version = versions[0]

    assert ci_version == req_version, (
        f"CI {tool} pin（{ci_version}）與 requirements-test.txt（{req_version}）不一致；"
        "兩處必須同步（single source of truth）"
    )


@pytest.mark.parametrize(
    "run_scalar, tool, expected_versions, expected_unparsed",
    [
        pytest.param(
            "pip install ruff\n# legacy: pip install ruff==0.15.17\n",
            "ruff",
            [None],
            [],
            id="shell-comment-is-not-a-command",
        ),
        pytest.param(
            "pip install ruff==0.15.17\npip install ruff==9.9.9\n",
            "ruff",
            ["0.15.17", "9.9.9"],
            [],
            id="two-different-pinned-versions",
        ),
        pytest.param(
            "pip install ruff==0.15.17\npip install ruff\n",
            "ruff",
            ["0.15.17", None],
            [],
            id="pinned-then-unpinned-overrides",
        ),
        pytest.param(
            "pip install ruff==0.15.17\n",
            "ruff",
            ["0.15.17"],
            [],
            id="legal-single-pinned-install",
        ),
        pytest.param(
            "pip install -q ruff==0.15.17\n",
            "ruff",
            ["0.15.17"],
            [],
            id="legal-with-flag",
        ),
        pytest.param(
            "pip install ruff==0.15.17  # keep in sync with requirements-test.txt pin\n",
            "ruff",
            ["0.15.17"],
            [],
            id="legal-trailing-comment",
        ),
        pytest.param(
            "pip install import-linter==2.13\n",
            "ruff",
            [],
            [],
            id="different-package-yields-empty",
        ),
        # 這格專門鎖「剝 shell 註解」那一行：拿掉它，誘餌 `ruff==9.9.9` 會被當成第二個
        # 參數 → 命中序列變 ['0.15.17', '9.9.9'] → 假紅。上面 shell-comment-is-not-a-command
        # 與 legal-trailing-comment 兩格都靠 `tokens[0] != 'pip'` 就過關，鎖不到這行
        # （round-5 review 實測：把剝註解那行拿掉，全檔 32 支照樣全綠）。
        pytest.param(
            "pip install ruff==0.15.17  # decoy: ruff==9.9.9\n",
            "ruff",
            ["0.15.17"],
            [],
            id="trailing-comment-decoy-must-not-be-parsed-as-arg",
        ),
        # 單行控制流：`do` 開頭的段若不略過，整段被丟掉（連 None 都不記）＝假綠，
        # 而 CI 實際會跑那次未釘版安裝並覆蓋釘版（round-5 review 找到的 BLOCKER）。
        pytest.param(
            "pip install ruff==0.15.17\nfor i in 1; do pip install ruff; done\n",
            "ruff",
            ["0.15.17", None],
            [],
            id="unpinned-hidden-in-shell-loop",
        ),
        pytest.param(
            'pip install ruff==0.15.17\nif [ "$X" = "1" ]; then pip install ruff==9.9.9; fi\n',
            "ruff",
            ["0.15.17", "9.9.9"],
            [],
            id="drifted-pin-hidden-in-shell-conditional",
        ),
        # ── round-6：合法 pin 在前、解析器不認得的安裝在後 ＝ 假綠的通用形狀 ──
        # 這五格全部要能看見「後面那次安裝」，不論是靠擴大辨識（前四格）還是靠
        # fail-closed（最後一格）。少任何一格，四道斷言都會在「versions 只剩合法
        # pin」的情況下全過（Codex round-6 具名的 P1）。
        pytest.param(
            "pip install ruff==0.15.17\npip3.12 install ruff\n",
            "ruff",
            ["0.15.17", None],
            [],
            id="dotted-pip-interpreter-is-recognized",
        ),
        pytest.param(
            "pip install ruff==0.15.17\npython3.12 -m pip install ruff==9.9.9\n",
            "ruff",
            ["0.15.17", "9.9.9"],
            [],
            id="dotted-python-m-pip-is-recognized",
        ),
        pytest.param(
            "pip install ruff==0.15.17\npip install \\\n  ruff==9.9.9\n",
            "ruff",
            ["0.15.17", "9.9.9"],
            [],
            id="line-continuation-is-joined",
        ),
        pytest.param(
            "pip install ruff==0.15.17\npip install 'ruff==9.9.9'\n",
            "ruff",
            ["0.15.17", "9.9.9"],
            [],
            id="quoted-spec-is-unwrapped",
        ),
        pytest.param(
            "pip install ruff==0.15.17\nuv pip install ruff\n",
            "ruff",
            ["0.15.17"],
            ["uv pip install ruff"],
            id="unknown-installer-fails-closed",
        ),
        pytest.param(
            "pip install ruff==0.15.17\npoetry add ruff\n",
            "ruff",
            ["0.15.17"],
            ["poetry add ruff"],
            id="unknown-installer-verb-add-fails-closed",
        ),
        # 反向：提到 tool 但不是安裝的命令不得被誤判成 unparsed，否則真 workflow
        # 的 `ruff check .` 會讓守衛永遠紅（fail-closed 不等於見字就紅）。
        pytest.param(
            "ruff check .\n",
            "ruff",
            [],
            [],
            id="non-install-mention-is-not-suspicious",
        ),
        # ── round-7：shell grouping 標點讓名字對不上 → 連 unparsed 都收不到 ──
        # `(pip install ruff)` 的 token 是 `ruff)`，round-6 版本既不記 versions 也不記
        # unparsed，前面的合法 pin 就讓整支綠 ＝ 假綠（Codex round-7 具名）。
        pytest.param(
            "pip install ruff==0.15.17\n(pip install ruff)\n",
            "ruff",
            ["0.15.17"],
            ["(pip install ruff)"],
            id="subshell-paren-fails-closed",
        ),
        # 未釘版才鎖得住剝標點那行：帶 `==` 的 spec 會被 `[=<>!~\[]` 切割順便把尾括號
        # 丟掉，即使不剝標點也對得上名字（實測），那種格子驗不到任何東西。
        pytest.param(
            "pip install ruff==0.15.17\n$(pip install ruff)\n",
            "ruff",
            ["0.15.17"],
            ["$(pip install ruff)"],
            id="command-substitution-fails-closed",
        ),
    ],
)
def test_pip_installs_command_level_parsing(run_scalar, tool, expected_versions, expected_unparsed):
    """`_pip_installs()` 表驅動邊界形狀（round-5 建立、round-6 擴充）——鎖住命令級
    解析，防止下一個人無聲弱化回「join 全部 run scalar 後 `re.search` 抓第一個」。

    輸入是 job 內單一 step 的 `run` scalar 字串（`yaml.safe_load` 解析 `run: |`
    block scalar 後得到的就是這種多行字串），走真正的呼叫路徑
    `_pip_installs(job, tool)`，不是重新實作一份解析邏輯來比對。

    每格同時斷言 `versions` 與 `unparsed`：只驗前者的話，round-6 那類「合法 pin
    在前、不認得的安裝在後」會全部看起來正常。
    """
    job = {"steps": [{"run": run_scalar}]}
    installs = _pip_installs(job, tool)
    assert installs.versions == expected_versions
    assert installs.unparsed == expected_unparsed


# ── exact-pin 守衛（TASK-79-T6）─────────────────────────────────────────────
# 兩份 requirements 必須 exact `==` pin（綠色軟體可重現 build：同 git tag = 同 ZIP）。
# float floor（`>=` 等）→ pip 抓最新 → 不同機器/時間建出不同依賴樹。

def _requirement_lines(path: Path) -> list[str]:
    """回傳實際依賴行（去掉註解 + 空行 + pip 選項行如 `-r`；inline `# comment` 也剝除）。"""
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.split("#", 1)[0].strip()
        if stripped and not stripped.startswith("-"):  # 跳過 `-r requirements.txt` 等 pip 選項
            lines.append(stripped)
    return lines


def test_requirements_are_exact_pinned():
    """requirements.txt / requirements-test.txt 每行都須 `==` exact-pin，
    不得含 `>=` / `<=` / `~=` / bare `>` / bare `<`（含 uvicorn[standard]==0.46.0）。"""
    loose = re.compile(r">=|<=|~=|>|<")
    for path in (_REQUIREMENTS_RUNTIME, _REQUIREMENTS):
        assert path.exists(), f"requirements 檔不存在：{path}"
        for line in _requirement_lines(path):
            assert "==" in line, (
                f"{path.name} 有未 exact-pin 的依賴行（缺 `==`）：{line!r}"
            )
            assert not loose.search(line), (
                f"{path.name} 有 loose 約束（>= / <= / ~= / > / <），須改 `==`：{line!r}"
            )


def test_requirements_test_inherits_runtime_pins():
    """requirements-test.txt 必須以 `-r requirements.txt` 繼承 runtime pinned 依賴。

    CI test job 只裝 requirements-test.txt（.github/workflows/test.yml）；若 runtime 依賴
    （fastapi/starlette/pydantic…）不在本檔，test 就跑在浮動的 transitive 版本上，與
    runtime/build 出貨版本不一致 → 破壞可重現性、且漏接 framework 簽名漂移
    （見 tests/integration/test_page_routes_render.py 守的 Starlette TemplateResponse 變更）。
    用 `-r` 繼承＝結構上保證 test 環境 = runtime pinned + 測試工具，杜絕「漏鏡像」漂移
    （Codex T6 修正：原本 starlette 只 pin 在 requirements.txt，test 檔遺漏）。"""
    text = _REQUIREMENTS.read_text(encoding="utf-8")
    assert re.search(r"^\s*-r\s+requirements\.txt\s*$", text, re.MULTILINE), (
        "requirements-test.txt 必須含 `-r requirements.txt`（繼承 runtime pinned 依賴）；"
        "否則 CI test job 會跑在浮動的 runtime-only 依賴版本上"
    )


# ── mypy 殭屍防復活（TASK-78-T5）────────────────────────────────────────────
# mypy config + 依賴齊全但 CI 從不執行＝殭屍（spec D4）。已於 feature/78 刪除；
# 以下守衛防它被無意識復活（config 在但永不跑的假象保護）。

def test_no_mypy_ini():
    assert not (_REPO_ROOT / "mypy.ini").exists(), "mypy.ini 殭屍復活（spec D4：已刪除，CI 從不跑 mypy）"


def test_requirements_test_has_no_mypy():
    txt = (_REPO_ROOT / "requirements-test.txt").read_text(encoding="utf-8")
    lines = [ln.split("#")[0].strip().lower() for ln in txt.splitlines()]
    offenders = [ln for ln in lines if ln.startswith("mypy") or ln.startswith("types-requests")]
    assert not offenders, f"requirements-test.txt 不應有 mypy/types-requests 依賴（已刪）：{offenders}"


# ============================================================
# build.py Allowlist 模型契約（T2：棄 pip freeze + denylist）
# 緣起：T1 前 denylist 反覆漏 transitive（mypy orphan +11MB、playwright +32MB、uvloop +16MB）。
# T2 改為 allowlist 模型（requirements.txt 解析 + manifest extract），根除漂移根因。
# 本段守衛驗「allowlist 解析結果不含測試/開發工具、含必備 runtime」合約。
# ============================================================

def _direct_pkgs(req_path: Path) -> set:
    """抽 requirements 檔的直列套件名（跳 `-r`/註解/空行；去版本/extras、標準化）。"""
    names = set()
    for line in req_path.read_text(encoding="utf-8").splitlines():
        s = line.split("#", 1)[0].strip()
        if not s or s.startswith("-"):
            continue
        name = re.split(r"[=<>!~\[]", s, maxsplit=1)[0].strip().lower().replace("_", "-")
        if name:
            names.add(name)
    return names


def _get_allowlist_names() -> set[str]:
    """取得 build.py allowlist 解析結果的套件名集合（標準化）。

    包含 parse_requirements_allowlist() + _UVICORN_WIN_SAFE_EXTRAS + extra_deps。
    """
    import build
    import re as _re

    def _norm(spec: str) -> str:
        return _re.split(r"[=<>!~\[]", spec, maxsplit=1)[0].strip().lower().replace("_", "-")

    names: set[str] = set()
    for dep in build.parse_requirements_allowlist():
        names.add(_norm(dep))
    for dep in build._UVICORN_WIN_SAFE_EXTRAS:
        names.add(_norm(dep))
    # extra_deps 改讀模組級常數 EXTRA_DEPS_NO_DEPS（N2）：新增 extra dep 即被守衛涵蓋，
    # 不再用 hardcoded list 代理（避免漏守衛）。proxy-tools 亦在此清單，SDIST_OK 另有專門守衛。
    for dep in build.EXTRA_DEPS_NO_DEPS:
        names.add(_norm(dep))
    return names


def test_build_allowlist_excludes_dev_tools():
    """allowlist 解析結果不得含 uvloop / playwright / mypy / pytest / ruff 等測試/開發工具。

    T2 allowlist 模型：依賴來源 = requirements.txt，無 pip freeze，無 dev venv 污染。
    uvloop 尤其重要：曾以 Linux .so（16MB）混入每個 release ZIP（P2 bug）。
    playwright 曾 +32MB；mypy 曾 +11MB——三者在 T1/T2 前長期隨 release 送到用戶。
    """
    banned = {"uvloop", "playwright", "mypy", "mypyc", "mypy-extensions",
              "pytest", "pytest-asyncio", "pytest-mock", "pytest-cov",
              "pytest-playwright", "ruff", "pyee", "langdetect"}
    names = _get_allowlist_names()
    found = sorted(banned & names)
    assert not found, (
        f"build.py allowlist 含不應出現的測試/開發工具：{found}\n"
        f"（T2 allowlist 模型：這些套件不在 requirements.txt，不應被 parse_requirements_allowlist 引入）"
    )


def test_build_allowlist_contains_required_runtime():
    """allowlist 必須含所有必備 runtime 套件——否則 build 缺套件、用戶端壞掉。"""
    required = {
        "fastapi", "uvicorn", "starlette", "jinja2", "python-multipart",
        "requests", "httpx", "beautifulsoup4", "lxml", "curl-cffi",
        "pydantic", "websockets", "pillow", "pywebview",
        "httptools", "watchfiles", "python-dotenv", "pyyaml",
        "bottle", "clr-loader", "pythonnet", "win32-setctime", "colorama",
        "proxy-tools",
    }
    names = _get_allowlist_names()
    # 標準化比較（curl_cffi → curl-cffi, clr_loader → clr-loader 等）
    missing = sorted(required - names)
    assert not missing, (
        f"build.py allowlist 缺少必備 runtime 套件（會做出缺套件的 ZIP）：{missing}"
    )


def test_build_allowlist_no_uvicorn_standard_extra():
    """allowlist 中 uvicorn 不應帶 [standard] extra。

    uvicorn[standard] 在 pip download --platform win_amd64 時會嘗試解 uvloop
    （marker sys_platform != 'win32' 不被求值）→ 無 win_amd64 wheel → build 失敗。
    T2 fix：uvicorn 去 [standard]，win-safe extras 改由 _UVICORN_WIN_SAFE_EXTRAS 明列。
    """
    import build
    for dep in build.parse_requirements_allowlist():
        assert "[standard]" not in dep, (
            f"parse_requirements_allowlist() 仍含 uvicorn[standard]：{dep!r}\n"
            f"應改為 uvicorn（去 extra），win-safe extras 由 _UVICORN_WIN_SAFE_EXTRAS 明列"
        )


def test_build_sdist_ok_contains_proxy_tools():
    """SDIST_OK 必須含 proxy-tools（PyPI 只有 sdist，無 wheel）。"""
    import build
    assert "proxy-tools" in build.SDIST_OK, (
        "build.SDIST_OK 缺 'proxy-tools'（PyPI 從未發 wheel，只有 proxy_tools-0.1.0.tar.gz）"
    )


def test_build_skip_if_no_win_wheel_contains_uvloop():
    """SKIP_IF_NO_WIN_WHEEL 必須含 uvloop（Windows 合法缺席，無 win_amd64 wheel）。"""
    import build
    assert "uvloop" in build.SKIP_IF_NO_WIN_WHEEL, (
        "build.SKIP_IF_NO_WIN_WHEEL 缺 'uvloop'（uvloop 無 win_amd64 wheel，應 skip + warning）"
    )


def test_build_greenlet_not_wrongly_excluded():
    """greenlet 不應被 allowlist 模型排除（pywebview Windows backend 的合法 transitive）。

    T1 前的 denylist 模型曾被誤列；T2 allowlist 模型無 denylist，greenlet 由 pip 依賴解析
    自動帶入（若 pywebview 需要）。此守衛確保 greenlet 未被誤加入任何排除機制。
    """
    import build
    # T2 無 EXCLUDE_PACKAGES；確認 SKIP_IF_NO_WIN_WHEEL 和 SDIST_OK 也未誤含 greenlet
    assert "greenlet" not in build.SKIP_IF_NO_WIN_WHEEL, (
        "SKIP_IF_NO_WIN_WHEEL 誤含 greenlet（greenlet 有 win_amd64 wheel，不應 skip）"
    )
    assert "greenlet" not in build.SDIST_OK, (
        "SDIST_OK 誤含 greenlet（greenlet 有 win_amd64 wheel，非 sdist-only）"
    )


def test_build_no_exclude_packages_attribute():
    """T2 後 build.py 不再有 EXCLUDE_PACKAGES（已由 allowlist 模型取代）。

    EXCLUDE_PACKAGES 是 denylist 模型的遺跡，必須移除。
    若此 test 失敗，代表 denylist 被復活——需重新評估是否違反 T2 設計。
    """
    import build
    assert not hasattr(build, "EXCLUDE_PACKAGES"), (
        "build.py 仍有 EXCLUDE_PACKAGES（denylist 模型遺跡）；"
        "T2 改為 allowlist + manifest-based extract，EXCLUDE_PACKAGES 應移除"
    )


def test_extra_deps_no_deps_all_pinned():
    """EXTRA_DEPS_NO_DEPS 每個項目都必須精確 pin（==）。

    未 pin 的 Phase 2 套件有兩個失效路徑：
    1. CI cache 有舊版 → 名稱命中跳下載 → 出貨舊版（stale-reuse）。
    2. cache 同時有多版 → cache-hit loop 全部加入 manifest → 兩版都解壓
       → last-writer-wins 覆蓋（multi-version corruption）。
    Pin 後 stale-cleanup 能靠版本號偵測並強制重下，確保 reproducible build。
    """
    import build
    unpinned = [dep for dep in build.EXTRA_DEPS_NO_DEPS if "==" not in dep]
    assert not unpinned, (
        f"EXTRA_DEPS_NO_DEPS 有未 exact-pin（==）的項目：{unpinned}\n"
        "所有 Phase 2 套件必須精確釘版本，防止 CI cache stale-reuse 和多版本解壓污染。"
    )


def test_uvicorn_win_safe_extras_all_pinned():
    """_UVICORN_WIN_SAFE_EXTRAS 每個項目都必須精確 pin（==）。

    httptools / watchfiles / python-dotenv / PyYAML 是 uvicorn[standard] 的 win-safe 子集，
    經 Phase 1 with-deps 下載。若無 pin，cold cache 或任一套件發佈新版時，pip 抓最新
    → 不同時間 / 不同機器建出不同版本 → 破壞可重現 build 契約（與 EXTRA_DEPS_NO_DEPS 同規範）。
    """
    import build
    unpinned = [dep for dep in build._UVICORN_WIN_SAFE_EXTRAS if "==" not in dep]
    assert not unpinned, (
        f"_UVICORN_WIN_SAFE_EXTRAS 有未 exact-pin（==）的項目：{unpinned}\n"
        "所有 win-safe extras 必須精確釘版本，確保 reproducible build（同 git tag = 同 ZIP）。"
    )


def test_parse_allowlist_rewrites_only_uvicorn_standard():
    """uvicorn[standard]==X → uvicorn==X（去 extra）；其餘無 extra 的行原樣保留。"""
    import build
    out = build._parse_allowlist_lines([
        "uvicorn[standard]==0.46.0",
        "fastapi==0.136.1",
        "# comment",
        "-r requirements.txt",
    ])
    assert "uvicorn==0.46.0" in out, f"uvicorn[standard] 未正確改寫：{out}"
    assert all("[standard]" not in d for d in out), f"殘留 [standard]：{out}"
    assert "fastapi==0.136.1" in out


def test_parse_allowlist_fails_closed_on_unexpected_extra():
    """非 uvicorn[standard] 的任何 extra → hard-fail（不靜默剝除子依賴）。

    Codex P2：blanket 剝 extra 會讓未來 `pkg[extra]==...` 的子依賴從 Windows ZIP
    無聲消失（正是 T2 要根除的漂移）。必須 fail-closed，逼維護者顯式處理。
    """
    import build
    with pytest.raises(SystemExit):
        build._parse_allowlist_lines(["redis[hiredis]==5.0.0"])
    # uvicorn 帶非 standard extra 也須 fail-closed（只認 [standard]）
    with pytest.raises(SystemExit):
        build._parse_allowlist_lines(["uvicorn[foo]==0.46.0"])


# ============================================================
# TASK-80-BUILD-T4b：build.py 模型「三禁」契約（防退回舊模型）
# 與 T2 的 allowlist 斷言互補：T2 驗「解析結果對」，本段驗「模型沒退回」。
# 與 T4a（build.yml 真實 ZIP 產物斷言）互補：本段早、快、便宜，在 PR pytest 階段先報紅。
# 三禁：① 不得回到 pip freeze 取安裝集 ② 不得 glob 整個 cache extract ③ 不得平台不符 fallback。
# ============================================================

def _build_source_no_comments() -> str:
    """build.py 原始碼，逐行剝除 `#` 註解（避免註解中提到的字觸發守衛誤判）。"""
    src = (_REPO_ROOT / "build.py").read_text(encoding="utf-8")
    return "\n".join(line.split("#", 1)[0] for line in src.splitlines())


def test_build_no_pip_freeze():
    """① build.py 不得用 pip freeze 取安裝集（T2 棄 freeze；舊函式 get_all_dependencies 須消失）。

    freeze 凍結的是「當前 dev venv」→ 任何測試/orphan 套件混入即被打包（denylist 漂移根因）。
    註解可提及 freeze（歷史說明），但程式碼不得再呼叫。
    """
    import build
    assert not hasattr(build, "get_all_dependencies"), (
        "build.py 仍有 get_all_dependencies（pip freeze 取安裝集的舊函式）；T2 已改 allowlist，應移除"
    )
    code = _build_source_no_comments()
    assert "freeze" not in code, (
        "build.py 程式碼（非註解）仍出現 'freeze'；不得退回 pip freeze 取安裝集模型"
    )


def test_build_extract_uses_manifest_not_glob_all():
    """② extract 必須只解壓 extract_manifest，不得 glob 整個 cache（殘留 orphan 會被帶入）。"""
    code = _build_source_no_comments()
    assert "for f in extract_manifest" in code, (
        "build.py 未見『for f in extract_manifest』；extract 應只迭代本次解析的 manifest"
    )
    assert 'glob("*.whl")' not in code, (
        "build.py 出現 glob(\"*.whl\")（舊 extract-整個-cache 模式）；應改 manifest-based extract"
    )


class _FakePipFail:
    """模擬 pip download 失敗的 CompletedProcess。"""
    returncode = 1
    stdout = ""
    stderr = "ERROR: No matching distribution found"


def test_build_download_fail_closed_no_platform_fallback(monkeypatch, tmp_path):
    """③ 必要套件無 win wheel → 硬失敗、且只嘗試一次（無平台不符 fallback retry）。

    舊模型：win wheel 失敗 → 再 `pip download`（不限平台）拉 Linux wheel（uvloop .so 混入途徑）。
    本守衛 mock pip 失敗，斷言 _download_one_package 對非 skip 套件 SystemExit 且只呼叫 pip 一次。
    """
    import build
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakePipFail()

    monkeypatch.setattr(build.subprocess, "run", fake_run)
    with pytest.raises(SystemExit):
        build._download_one_package("somerequiredpkg==1.0.0", tmp_path)
    assert len(calls) == 1, (
        f"非 skip 套件無 win wheel 時應只嘗試一次（無 fallback retry），實際 {len(calls)} 次"
    )


def test_build_download_skip_if_no_win_wheel(monkeypatch, tmp_path):
    """SKIP_IF_NO_WIN_WHEEL 成員（uvloop）無 win wheel → skip（不 raise）、回空集、只嘗試一次。"""
    import build
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakePipFail()

    monkeypatch.setattr(build.subprocess, "run", fake_run)
    result = build._download_one_package("uvloop==0.22.1", tmp_path)
    assert result == set(), f"uvloop 應 skip 並回空集，實際 {result}"
    assert len(calls) == 1, f"應只嘗試一次（不 fallback），實際 {len(calls)} 次"
