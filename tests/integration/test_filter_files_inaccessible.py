"""
test_filter_files_inaccessible.py — P2-T6（spec-107 功能 D）

filter-files 的 `rejected.inaccessible` 桶：把「無讀權限（PermissionError）＋未掛載/UNC
（啟發式）」與「檔案真的不存在（not_found）」分流，讓桌面拖入存取不到的 Windows 檔時能顯示
正確訊息（前端 path_inaccessible）而非誤導的「無法識別番號」。

涵蓋：
- `_looks_unmounted_drive` 純函式全分支（mock is_mount 決定性）。
- 端點 stat-early：PermissionError→inaccessible、FileNotFoundError+未掛載→inaccessible、
  FileNotFoundError+已掛載/非 mnt→not_found、SMB ValueError→inaccessible。
- **min_size_mb=0 預設下仍 stat**（原 bug：預設不 stat 則權限/未掛載無從判別）。
- 既有 filter-files 零回歸。
- 故障注入 mutation 自驗（見各測試 docstring）。
"""
import pytest
from pathlib import Path

from web.routers.search import _filter_files_sync
from core.database.connection import init_db


@pytest.fixture(autouse=True)
def _t6_isolated_failure_db(tmp_path, monkeypatch):
    """TASK-144-T6：這支檔案裡的測試現在會間接碰到 organize_failures 這張表。

    `POST /api/search/filter-files` 會查失敗記憶、`scrape_single()` 成功時會清失敗記憶，
    兩者都開 sqlite 連線——而這些測試原本完全不碰 DB，於是被 repo-write 守衛（G1，
    `tests/conftest.py:250`）擋成 `RepoWriteGuardViolation`（繼承 `BaseException`，
    產品碼的 `except Exception` 攔不到，整個請求變 500）。

    **這不是放寬守衛**：守衛擋的是「寫進真實 output/openaver.db」，把預設 db_path 指到
    tmp 正是它訊息裡列的四種修法第一種。形狀照 `tests/unit/test_auto_organize.py::isolated_db`
    的既有慣例（T3 建立）。
    """
    db_path = tmp_path / "t6_organize_failures.db"
    init_db(db_path)
    monkeypatch.setattr("core.database.connection.get_db_path", lambda: db_path)
    return db_path


class TestFilterFilesInaccessible:
    """端點層：rejected.inaccessible 分流（透過 _filter_files_sync 直呼，繞過 asyncio）"""

    def _mock_stat_raise(self, monkeypatch, target: str, exc):
        """只對 target 路徑的 Path.stat 拋 exc，其餘走原生（is_file/is_mount 內部 stat 不受影響）"""
        original_stat = Path.stat

        def fake_stat(self_path, *args, **kwargs):
            if str(self_path) == target:
                raise exc
            return original_stat(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", fake_stat)

    def test_permission_error_to_inaccessible(self, tmp_path, monkeypatch):
        """stat PermissionError → inaccessible（非 not_found）。
        mutation：把 `except PermissionError` 分支拿掉 → 落 OSError→not_found，本測試轉紅。
        min_size_mb 為 config 預設（0），本測試同時證明**預設下仍 stat**（否則永不觸發權限例外）。"""
        mp4 = tmp_path / "PERM-001.mp4"
        mp4.write_bytes(b"x")
        self._mock_stat_raise(monkeypatch, str(mp4), PermissionError("denied"))

        result = _filter_files_sync([str(mp4)])
        assert result["rejected"]["inaccessible"] == 1
        assert result["rejected"]["not_found"] == 0
        assert result["files"] == []


    def test_smb_unc_value_error_to_inaccessible(self):
        """SMB/UNC 路徑 → normalize_path 拋 ValueError → inaccessible（WSL 與純 Linux 皆拋 ValueError）。
        mutation：把 `except ValueError` 改回記 not_found → 本測試轉紅。"""
        result = _filter_files_sync(["\\\\server\\share\\video.mp4"])
        assert result["rejected"]["inaccessible"] == 1
        assert result["rejected"]["not_found"] == 0


