"""core/platform_info.py — 平台環境訊號偵測模組（TASK-159-T3）"""
import os

DSM_PERMISSION_HINT = "控制台 → 共用資料夾 → 編輯 → 權限 → 系統內部使用者帳號 → openaver-svc 勾可讀寫"


def is_synology() -> bool:
    """判斷這台機器是不是從 spk 裝起來的 Synology 版。

    讀取由 start-stop-status 腳本設定的 OPENAVER_SYNOLOGY 環境變數。
    """
    return os.environ.get("OPENAVER_SYNOLOGY") == "1"
