"""
test_focal_trigger.py — TASK-98b-T2 / 99b-T2: maybe_submit_video_focal helper 契約
                         + TASK-105-T6: schedule_focal_after_cover_write 收斂 helper

TDD-lite（注入假 submit_focal / 假 repo / 假 gate，不真跑 pigo、不碰真 DB）：
- gate：有碼 → 不 submit；無碼 → submit
- exists guard：cover None / 檔不在 → 不 submit
- submit 參數：kind=='video'、ratio==0.71、cover_fs、video_path_uri 對齊
- commit lambda：呼叫 update_auto_focal(video_path_uri, focal_str, cover_path_uri)（fp 忽略）
- 防禦：helper 內任何例外都吞掉（不冒泡打斷 scrape/scan）
- 99b-T2 CD-99b-9：cover_path_uri 為 keyword-only 必填，省略即 TypeError（fail-closed）

TASK-105-T6 schedule_focal_after_cover_write：
- 順序鎖：reset_focal_to_auto 必早於 maybe_submit_video_focal
- args passthrough：reset 單一 video_uri；submit 位置 (number, maker, video_uri, cover_fs)
  + keyword-only cover_path_uri
- cover_path_uri 派生：truthy → to_file_uri(cover_fs, path_mappings)；falsy → ""
- db_path 不傳
"""

from unittest.mock import patch, MagicMock



# ─── gate：有碼片零成本（不 submit） ────────────────────────────────────────

def test_censored_number_does_not_submit():
    with (
        patch("core.focal_trigger.requires_face_detection", return_value=False),
        patch("core.focal_trigger.submit_focal") as mock_submit,
        patch("core.focal_trigger.os.path.exists", return_value=True),
    ):
        from core.focal_trigger import maybe_submit_video_focal
        maybe_submit_video_focal(
            "SONE-205", "SOD", "file:///x/SONE-205.mp4", "/x/SONE-205.jpg",
            cover_path_uri="file:///x/SONE-205.jpg",
        )

    mock_submit.assert_not_called()


# ─── gate：無碼片 → submit（參數契約） ──────────────────────────────────────

def test_uncensored_number_submits_with_correct_args():
    with (
        patch("core.focal_trigger.requires_face_detection", return_value=True),
        patch("core.focal_trigger.submit_focal") as mock_submit,
        patch("core.focal_trigger.os.path.exists", return_value=True),
        patch("core.focal_trigger.VideoRepository"),
    ):
        from core.focal_trigger import maybe_submit_video_focal, _DETECT_RATIO
        maybe_submit_video_focal(
            "SIRO-1234", "", "file:///x/SIRO-1234.mp4", "/x/SIRO-1234.jpg",
            cover_path_uri="file:///x/SIRO-1234.jpg",
        )

    mock_submit.assert_called_once()
    args, kwargs = mock_submit.call_args
    # submit_focal(kind, id, fs_path, ratio, commit)
    assert args[0] == "video"
    assert args[1] == "file:///x/SIRO-1234.mp4"
    assert args[2] == "/x/SIRO-1234.jpg"
    assert args[3] == _DETECT_RATIO
    assert _DETECT_RATIO == 0.71


# ─── exists guard：cover None / 檔不在 → 不 submit ──────────────────────────


# ─── commit lambda：綁定 video_path_uri + cover_path_uri，呼叫 update_auto_focal ──

def test_commit_lambda_calls_update_auto_focal_with_uri_and_expected_cover():
    """99b-T2：commit lambda 必須把 cover_path_uri（submit 當下捕獲）一併穿進
    update_auto_focal 的 expected_cover_path 第三參——mutation：把 commit lambda
    改回只傳 (video_path_uri, focal_str) 兩參 → 本測 RED（call args 缺第三參）。"""
    captured = {}

    def _capture_submit(kind, id, fs_path, ratio, commit):
        captured["commit"] = commit

    with (
        patch("core.focal_trigger.requires_face_detection", return_value=True),
        patch("core.focal_trigger.submit_focal", side_effect=_capture_submit),
        patch("core.focal_trigger.os.path.exists", return_value=True),
        patch("core.focal_trigger.VideoRepository") as MockRepo,
    ):
        from core.focal_trigger import maybe_submit_video_focal
        maybe_submit_video_focal(
            "SIRO-1234", "", "file:///x/SIRO-1234.mp4", "/x/SIRO-1234.jpg",
            cover_path_uri="file:///x/SIRO-1234.jpg",
        )

        # 模擬 worker dequeue 完成後呼叫 commit(focal_str, fp)
        captured["commit"]("0.5,0.4", ("/x/SIRO-1234.jpg", 123, 456))

    MockRepo.return_value.update_auto_focal.assert_called_once_with(
        "file:///x/SIRO-1234.mp4", "0.5,0.4", "file:///x/SIRO-1234.jpg"
    )


# ─── 防禦：submit 拋例外也不冒泡（scrape/scan 不被打斷） ─────────────────────

def test_submit_failure_never_raises():
    with (
        patch("core.focal_trigger.requires_face_detection", return_value=True),
        patch("core.focal_trigger.submit_focal", side_effect=RuntimeError("boom")),
        patch("core.focal_trigger.os.path.exists", return_value=True),
        patch("core.focal_trigger.VideoRepository"),
    ):
        from core.focal_trigger import maybe_submit_video_focal
        # 不應拋出
        maybe_submit_video_focal(
            "SIRO-1234", "", "file:///x/SIRO-1234.mp4", "/x/SIRO-1234.jpg",
            cover_path_uri="file:///x/SIRO-1234.jpg",
        )


# ─── TASK-98b-T7: commit 寫入「注入的 db_path」而非預設 DB（P2 silent-miss 修） ──


# ─── 99b-T2 CD-99b-9: cover_path_uri 為 keyword-only 必填（fail-closed） ────────


# ══════════════════════════════════════════════════════════════════════════
# TASK-105-T6: schedule_focal_after_cover_write（三站收斂 helper）
# ══════════════════════════════════════════════════════════════════════════


def test_schedule_focal_submit_passthrough():
    """maybe_submit_video_focal 收到 (number, maker, video_uri, cover_fs) 位置參
    + cover_path_uri= keyword；第三位置參與 reset 同一個 video_uri（防未來誤拆兩 URI）。
    """
    repo = MagicMock()
    video_uri = "file:///x/SIRO-1234.mp4"
    cover_fs = "/x/SIRO-1234.jpg"

    with patch("core.focal_trigger.maybe_submit_video_focal") as mock_submit:
        from core.focal_trigger import schedule_focal_after_cover_write
        schedule_focal_after_cover_write(
            repo, video_uri, "SIRO-1234", "SOD", cover_fs, {},
        )

    mock_submit.assert_called_once()
    args, kwargs = mock_submit.call_args
    assert args[0] == "SIRO-1234"
    assert args[1] == "SOD"
    assert args[2] == video_uri
    assert args[3] == cover_fs
    assert "cover_path_uri" in kwargs


# ─── T10：enqueue 前 is_disabled() 檢查（純優化，CD-152b-15） ────────────────


