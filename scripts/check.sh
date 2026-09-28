#!/usr/bin/env bash
# 單一驗證入口 —— 內容必須與 .github/workflows/test.yml 兩個 job 保持一致。
#
#   ./scripts/check.sh --fast   lint 六道，不含 pytest（約 10 秒）→ 每個 task 收尾
#   ./scripts/check.sh          全部七道（約 5 分鐘：2026-09-28 本機實測 xdist -n 2，pytest 270–289 秒）→ commit / PR 前
#
# 改這支的時候一定要同步 .github/workflows/test.yml，反之亦然：
# 這支存在的唯一理由就是「本機綠 ＝ CI 綠」，指令來源分兩處就失去意義。
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f venv/bin/activate ]]; then
  echo "✗ 找不到 venv/bin/activate（在 $(pwd)）" >&2
  exit 1
fi
# shellcheck disable=SC1091
source venv/bin/activate

FAST=0
[[ "${1:-}" == "--fast" ]] && FAST=1

# --- CI job: lint-frontend ---
echo "▶ npm run lint";  npm run lint
echo "▶ npm test";      npm test
echo "▶ ruff";          ruff check .
echo "▶ import-linter"; lint-imports
echo "▶ function-size"; python scripts/py_function_size_lint.py
echo "▶ no-raw-sqlite-connect"; python scripts/no_raw_sqlite_connect_lint.py

# --- CI job: test ---
if [[ $FAST -eq 0 ]]; then
  echo "▶ pytest"
  pytest tests/ -q -n 2 --ignore=tests/smoke --ignore=tests/e2e -m "not smoke and not e2e"
fi

echo "✅ all green"
