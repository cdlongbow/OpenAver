"""CI workflow contract guards (TASK-78-T3 / feature/78).

防止 `.github/workflows/test.yml` 的 lint-frontend job 被靜默移除——lint 守衛
（eslint + stylelint + ruff）必須在 CI 跑才 load-bearing（翻 reference_ci_no_eslint
前提）。解析 YAML 後檢查語意，不依賴 attribute 順序。
"""

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "test.yml"


@pytest.fixture(scope="module")
def workflow():
    assert _WORKFLOW.exists(), f"CI workflow 不存在：{_WORKFLOW}"
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _run_commands(job: dict) -> list[str]:
    """收集 job 內所有 step 的 `run` 字串（block scalar 多行也含）。"""
    return [step["run"] for step in job.get("steps", []) if isinstance(step, dict) and "run" in step]


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
