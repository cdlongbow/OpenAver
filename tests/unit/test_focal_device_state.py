"""tests/unit/test_focal_device_state.py — INV-152c-1 / INV-152c-2 / INV-152c-3

裝置級停用判定（feature/152c TASK-4）。每支測試把 CONFIG_PATH 指到各自的
tmp_path，走真檔案 I/O，不 mock load_config / save_config / mutate_config。
"""

from __future__ import annotations

import json
import threading

import pytest

import core.config as core_config
from core.config import load_config, mutate_config, save_config
from core.focal.subprocess_runner import RunnerOutcome


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _patch_config_paths(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(core_config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(core_config, "CONFIG_DEFAULT_PATH", tmp_path / "config.default.json")
    return config_path


def _seed_focal_device(
    *,
    disabled: bool = False,
    consecutive_timeout_count: int = 0,
    judged_at_version: str = "",
    set_by_user: bool = False,
) -> None:
    save_config(
        {
            "focal_device": {
                "disabled": disabled,
                "consecutive_timeout_count": consecutive_timeout_count,
                "judged_at_version": judged_at_version,
                "set_by_user": set_by_user,
            }
        }
    )


def _read_focal_device() -> dict:
    return load_config()["focal_device"]


def _abandoned(reason: str) -> RunnerOutcome:
    return RunnerOutcome(kind="ABANDONED", reason=reason)


def _found(x: float = 0.5, y: float = 0.5) -> RunnerOutcome:
    return RunnerOutcome(kind="FOUND", focal=(x, y))


def _no_face() -> RunnerOutcome:
    return RunnerOutcome(kind="NO_FACE")


# ---------------------------------------------------------------------------
# INV-152c-1 — 只有 detect_timeout 遞增；FOUND 歸零計數但不解除 disabled
# ---------------------------------------------------------------------------


class TestInv152c1Classification:
    def test_startup_timeout_noop_then_two_detect_timeout_disables_then_found_zeros_count(
        self, tmp_path, monkeypatch
    ):
        """INV-152c-1 主流程（DoD）。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(judged_at_version=VERSION)

        assert device_state.record_outcome(_abandoned("startup_timeout")) is False
        assert device_state.record_outcome(_abandoned("startup_timeout")) is False
        fd = _read_focal_device()
        assert fd["consecutive_timeout_count"] == 0
        assert fd["disabled"] is False

        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        just = device_state.record_outcome(_abandoned("detect_timeout"))
        assert just is True
        fd = _read_focal_device()
        assert fd["consecutive_timeout_count"] == 2
        assert fd["disabled"] is True

        assert device_state.record_outcome(_found()) is False
        fd = _read_focal_device()
        assert fd["consecutive_timeout_count"] == 0
        assert fd["disabled"] is True

    @pytest.mark.parametrize(
        "reason",
        ["crashed", "circuit_open", "skipped_disabled"],
    )
    def test_abandoned_noop_reasons_leave_state_unchanged(
        self, tmp_path, monkeypatch, reason
    ):
        """INV-152c-1 no-op 覆蓋（DoD）：各自獨立連續呼叫後計數與 disabled 不變。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(
            disabled=False,
            consecutive_timeout_count=1,
            judged_at_version=VERSION,
        )

        assert device_state.record_outcome(_abandoned(reason)) is False
        assert device_state.record_outcome(_abandoned(reason)) is False
        fd = _read_focal_device()
        assert fd["consecutive_timeout_count"] == 1
        assert fd["disabled"] is False

    def test_one_detect_timeout_then_found_resets_count(self, tmp_path, monkeypatch):
        """明確斷言「一次超時接著成功 → 歸零」（DoD）。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(judged_at_version=VERSION)

        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        assert _read_focal_device()["consecutive_timeout_count"] == 1

        assert device_state.record_outcome(_found()) is False
        fd = _read_focal_device()
        assert fd["consecutive_timeout_count"] == 0
        assert fd["disabled"] is False

    def test_no_face_also_resets_count_without_clearing_disabled(
        self, tmp_path, monkeypatch
    ):
        """FOUND／NO_FACE 都歸零計數，但不解除 disabled。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(
            disabled=True,
            consecutive_timeout_count=2,
            judged_at_version=VERSION,
        )

        assert device_state.record_outcome(_no_face()) is False
        fd = _read_focal_device()
        assert fd["consecutive_timeout_count"] == 0
        assert fd["disabled"] is True


# ---------------------------------------------------------------------------
# INV-152c-2 — lazy reset（讀路徑立即失真、寫路徑先重置再套用）
# ---------------------------------------------------------------------------


class TestInv152c2LazyReset:
    def test_version_mismatch_read_false_write_resets_then_applies(
        self, tmp_path, monkeypatch
    ):
        """INV-152c-2 主流程（DoD）。"""
        from core.focal import device_state

        _patch_config_paths(tmp_path, monkeypatch)
        monkeypatch.setattr(device_state, "VERSION", "0.16.4")
        _seed_focal_device(
            disabled=True,
            consecutive_timeout_count=2,
            judged_at_version="0.16.3",
        )

        assert device_state.is_disabled() is False

        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        fd = _read_focal_device()
        assert fd["consecutive_timeout_count"] == 1
        assert fd["disabled"] is False
        assert fd["judged_at_version"] == "0.16.4"

        just = device_state.record_outcome(_abandoned("detect_timeout"))
        assert just is True
        fd = _read_focal_device()
        assert fd["consecutive_timeout_count"] == 2
        assert fd["disabled"] is True
        assert fd["judged_at_version"] == "0.16.4"
        assert device_state.is_disabled() is True

    def test_same_version_found_never_clears_disabled(self, tmp_path, monkeypatch):
        """明確斷言「版本不變不自己解除」（DoD）。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(
            disabled=True,
            consecutive_timeout_count=2,
            judged_at_version=VERSION,
        )

        assert device_state.is_disabled() is True
        for _ in range(5):
            assert device_state.record_outcome(_found()) is False
        fd = _read_focal_device()
        assert fd["disabled"] is True
        assert fd["consecutive_timeout_count"] == 0
        assert device_state.is_disabled() is True


# ---------------------------------------------------------------------------
# just_disabled 回傳語意（False→True 那一次）
# ---------------------------------------------------------------------------


class TestJustDisabledReturn:
    def test_just_disabled_only_on_false_to_true_crossing(self, tmp_path, monkeypatch):
        """record_outcome 回傳值：只在 False→True 那一次為 True（DoD）。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(judged_at_version=VERSION)

        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        assert device_state.record_outcome(_abandoned("detect_timeout")) is True
        # 已停用後再超時 → 一律 False
        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        assert _read_focal_device()["disabled"] is True

    def test_just_disabled_false_when_already_disabled_even_after_count_reset(
        self, tmp_path, monkeypatch
    ):
        """disabled 已 True、FOUND 歸零計數後再湊滿兩次超時 → 不再回 True。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(
            disabled=True,
            consecutive_timeout_count=0,
            judged_at_version=VERSION,
        )

        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        assert _read_focal_device()["disabled"] is True


# ---------------------------------------------------------------------------
# record_outcome 不得吞 mutate_config 例外（設計決策硬性要求第 2 條）
# ---------------------------------------------------------------------------


class TestRecordOutcomePropagatesMutateConfigErrors:
    def test_record_outcome_does_not_swallow_mutate_config_exception(
        self, tmp_path, monkeypatch
    ):
        """mutate_config 拋例外時，record_outcome 必須原樣往外拋，不得吞掉回傳 bool。

        T10 的通知綁在 record_outcome 的回傳值上。若內部包 try/except 吞掉寫入
        失敗並回傳 True，就會出現「config.json 根本沒寫成功，卻發了一則『自動
        對焦已自動關閉』通知」——狀態沒落盤、通知已送出，重開 App 之後那則
        通知說的事情不存在。
        """
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(judged_at_version=VERSION)

        def _boom(_mutator):
            raise OSError("disk full (simulated)")

        # device_state 用 from-import 綁定 mutate_config，必須 patch 該 binding。
        monkeypatch.setattr(device_state, "mutate_config", _boom)

        with pytest.raises(OSError, match="disk full \\(simulated\\)"):
            device_state.record_outcome(_abandoned("detect_timeout"))


# ---------------------------------------------------------------------------
# INV-152c-3 — record_outcome mutator 遵守 mutate_config 契約（真檔案 I/O + 真 thread）
# ---------------------------------------------------------------------------


class TestInv152c3ConcurrentMutate:
    """INV-152c-3：驗證 record_outcome 的 mutator 遵守既有 mutate_config 契約。

    mutate_config 本身已用單一 ``_config_write_lock`` 序列化整個
    load→mutator→save（見 ``test_mutate_config_holds_lock``），兩條 thread 的
    RMW 臨界區物理上不可能交錯，因此本測試**不**證明獨立的 lost-update 防護。

    它證明的是：新 mutator 沒有繞過鎖，且與另一支任意 mutator 共存時兩邊寫入
    都落盤（plan INV-152c-3 oracle）。
    """

    def test_concurrent_record_outcome_and_unrelated_mutate_both_persist(
        self, tmp_path, monkeypatch
    ):
        """兩 thread 各經 mutate_config 寫 focal_device / general.folder_format，兩邊都落盤。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(judged_at_version=VERSION)

        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def write_focal() -> None:
            try:
                barrier.wait(timeout=5)
                device_state.record_outcome(_abandoned("detect_timeout"))
            except BaseException as exc:  # noqa: BLE001 — 收集到主 thread 再 raise
                errors.append(exc)

        def write_unrelated() -> None:
            try:
                barrier.wait(timeout=5)

                def _mut(cfg: dict) -> None:
                    cfg.setdefault("general", {})["folder_format"] = "{actor}/{maker}"

                mutate_config(_mut)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=write_focal, name="inv152c3-focal"),
            threading.Thread(target=write_unrelated, name="inv152c3-general"),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
            assert not t.is_alive(), f"{t.name} did not finish"

        assert errors == [], f"worker errors: {errors!r}"

        cfg = load_config()
        assert cfg["focal_device"]["consecutive_timeout_count"] == 1
        assert cfg["focal_device"]["disabled"] is False
        assert cfg["general"]["folder_format"] == "{actor}/{maker}"

        # 真檔案 I/O：磁碟上的 config.json 也同時含兩邊
        persisted = json.loads(core_config.CONFIG_PATH.read_text(encoding="utf-8"))
        assert persisted["focal_device"]["consecutive_timeout_count"] == 1
        assert persisted["general"]["folder_format"] == "{actor}/{maker}"


# ---------------------------------------------------------------------------
# T10 — F6 通知埠：只在 disabled false→true 的那一刻經 sink 發一則
# (CD-152b-15 / CD-152c-20)
# ---------------------------------------------------------------------------


class TestNotificationSinkTransition:
    def test_sink_called_once_on_transition_not_on_first_timeout(
        self, tmp_path, monkeypatch
    ):
        """DoD：連續兩次超時湊滿 → sink 恰好被呼叫一次，且發生在第二次那一輪。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(judged_at_version=VERSION)
        calls: list[tuple] = []
        monkeypatch.setattr(
            device_state, "_notification_sink",
            lambda *args, **kwargs: calls.append((args, kwargs)),
        )

        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        assert calls == []  # 第一次超時：還沒轉態，不發

        assert device_state.record_outcome(_abandoned("detect_timeout")) is True
        assert calls == [(("warn", "notif.focal_auto_disabled"), {})]

    def test_no_notification_without_transition_when_already_disabled(
        self, tmp_path, monkeypatch
    ):
        """DoD：裝置已經是停用狀態，再超時一次 → 沒有轉態，零通知。

        mutation 錨點 M1：record_outcome 裡
        `if just_disabled and _notification_sink is not None:`。
        """
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(
            disabled=True, consecutive_timeout_count=2, judged_at_version=VERSION,
        )
        calls: list[tuple] = []
        monkeypatch.setattr(
            device_state, "_notification_sink",
            lambda *args, **kwargs: calls.append((args, kwargs)),
        )

        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        assert calls == []

    def test_found_scan_never_notifies(self, tmp_path, monkeypatch):
        """DoD：全庫有碼片掃描完成（只有 FOUND/NO_FACE，從未超時）→ 零通知。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(judged_at_version=VERSION)
        calls: list[tuple] = []
        monkeypatch.setattr(
            device_state, "_notification_sink",
            lambda *args, **kwargs: calls.append((args, kwargs)),
        )

        for _ in range(5):
            assert device_state.record_outcome(_found()) is False
        assert calls == []

    def test_transition_is_caller_path_agnostic(self, tmp_path, monkeypatch):
        """DoD：停用由路徑④（海報產生）湊成也一樣發通知。

        record_outcome 本身不知道呼叫端是 worker（路徑①）或 organizer（路徑④）
        ——判定只吃 outcome 序列，跟哪個模組呼叫無關。這裡用「兩次超時之間夾雜
        其他事件」模擬跨情境湊成停用（不限單一掃描或單一路徑）。
        """
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(judged_at_version=VERSION)
        calls: list[tuple] = []
        monkeypatch.setattr(
            device_state, "_notification_sink",
            lambda *args, **kwargs: calls.append((args, kwargs)),
        )

        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        assert device_state.record_outcome(_found()) is False  # 計數歸零，換一個情境
        assert calls == []
        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        assert device_state.record_outcome(_abandoned("detect_timeout")) is True
        assert len(calls) == 1

    def test_version_change_resets_then_notifies_again(self, tmp_path, monkeypatch):
        """DoD：版本變更後重新判定、再次湊滿兩次超時 → 再發一則。"""
        from core.focal import device_state

        _patch_config_paths(tmp_path, monkeypatch)
        monkeypatch.setattr(device_state, "VERSION", "0.16.4")
        _seed_focal_device(
            disabled=True, consecutive_timeout_count=2, judged_at_version="0.16.3",
        )
        calls: list[tuple] = []
        monkeypatch.setattr(
            device_state, "_notification_sink",
            lambda *args, **kwargs: calls.append((args, kwargs)),
        )

        assert device_state.record_outcome(_abandoned("detect_timeout")) is False  # lazy reset，第一次
        assert calls == []
        assert device_state.record_outcome(_abandoned("detect_timeout")) is True
        assert len(calls) == 1

    def test_unregistered_sink_is_silent_noop(self, tmp_path, monkeypatch):
        """DoD：未註冊 sink 時，record_outcome 走完轉態路徑不拋例外、不發通知。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(judged_at_version=VERSION)
        monkeypatch.setattr(device_state, "_notification_sink", None)

        device_state.record_outcome(_abandoned("detect_timeout"))
        assert device_state.record_outcome(_abandoned("detect_timeout")) is True

    def test_raising_sink_does_not_propagate_and_state_stays_usable(
        self, tmp_path, monkeypatch
    ):
        """DoD：sink 拋例外時，偵測 outcome 逐字不變、且不外洩例外。

        record_outcome 內部把 sink 呼叫包在自己的 try/except（CD-152b-9 不變式
        (c)）——record_outcome 本身不拋出即可，等同 run_detection 收到的
        on_outcome 回呼「正常完成」。鎖的釋放與下一件工作的 spawn 已由既有的
        test_focal_subprocess_runner.py::test_on_outcome_raises_preserves_outcome_and_releases_lock
        （驗的是 on_outcome 真的拋例外，更嚴格的情境）結構性涵蓋。本測試只證
        「sink 拋例外不會讓 record_outcome 變成那個情境」：緊接著再呼叫一次
        record_outcome 模擬下一件工作，證明狀態沒有被打壞。
        """
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(judged_at_version=VERSION)

        def _boom_sink(*args, **kwargs):
            raise RuntimeError("sink boom (simulated)")

        monkeypatch.setattr(device_state, "_notification_sink", _boom_sink)

        device_state.record_outcome(_abandoned("detect_timeout"))
        just_disabled = device_state.record_outcome(_abandoned("detect_timeout"))
        assert just_disabled is True
        assert _read_focal_device()["disabled"] is True

        assert device_state.record_outcome(_found()) is False
        assert _read_focal_device()["consecutive_timeout_count"] == 0

    def test_notification_copy_has_no_numbers_and_mentions_manual_escape_hatch(self):
        """DoD：文案不含張數／具體耗時數字、含手動拖曳逃生口（F6）。"""
        import json
        import re
        from pathlib import Path

        zh = json.loads(Path("locales/zh_TW.json").read_text(encoding="utf-8"))
        text = zh["notif"]["focal_auto_disabled"]

        # [lint-guard: pytest-justified] i18n fallback 字串 fingerprint（明文例外）：驗的是
        # locales/zh_TW.json 的值本身，不是 html/js/css 渲染輸出；且兩條都是 spec F6 的
        # 文案不變式（不得含數字、必須寫出逃生口），不是靜態存在性檢查。
        assert not re.search(r"\d", text), f"F6 明文禁止張數／耗時數字，實際文案：{text}"
        assert "拖" in text, f"F6 要求提到手動拖曳的逃生口，實際文案：{text}"


# ---------------------------------------------------------------------------
# feature/152d TASK-D1 — set_by_user：使用者的決定不被系統覆寫
# ---------------------------------------------------------------------------


class TestSetByUser:
    def test_missing_set_by_user_key_treated_as_false(self, tmp_path, monkeypatch):
        """舊 config.json 的 focal_device 沒有 set_by_user → 視同 False，行為與今天相同。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        # 刻意不寫 set_by_user（模擬升級前的舊檔）
        save_config(
            {
                "focal_device": {
                    "disabled": False,
                    "consecutive_timeout_count": 0,
                    "judged_at_version": VERSION,
                }
            }
        )

        assert device_state.is_disabled() is False
        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        just = device_state.record_outcome(_abandoned("detect_timeout"))
        assert just is True
        fd = _read_focal_device()
        assert fd["disabled"] is True
        assert fd["consecutive_timeout_count"] == 2
        assert device_state.is_disabled() is True

    def test_set_by_user_true_blocks_auto_disable(self, tmp_path, monkeypatch):
        """set_by_user=True 時，連續 2 次 detect_timeout 不會把 disabled 翻成 True。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(
            disabled=False,
            consecutive_timeout_count=0,
            judged_at_version=VERSION,
            set_by_user=True,
        )

        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        fd = _read_focal_device()
        assert fd["disabled"] is False
        assert fd["set_by_user"] is True
        assert fd["consecutive_timeout_count"] == 2
        assert device_state.is_disabled() is False

    def test_set_by_user_true_survives_version_bump(self, tmp_path, monkeypatch):
        """set_by_user=True 時，版本升級不會把 disabled／set_by_user 重置回系統管理中。"""
        from core.focal import device_state

        _patch_config_paths(tmp_path, monkeypatch)
        monkeypatch.setattr(device_state, "VERSION", "0.16.4")
        _seed_focal_device(
            disabled=True,
            consecutive_timeout_count=2,
            judged_at_version="0.16.3",
            set_by_user=True,
        )

        # 讀路徑：與版本無關，直接回 disabled
        assert device_state.is_disabled() is True

        # 寫路徑：整段 lazy reset 跳過；disabled／set_by_user 都不被打回
        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        fd = _read_focal_device()
        assert fd["disabled"] is True
        assert fd["set_by_user"] is True
        assert fd["consecutive_timeout_count"] == 3  # 未 reset，繼續累積
        assert fd["judged_at_version"] == "0.16.4"
        assert device_state.is_disabled() is True

    def test_set_by_user_true_still_stamps_version_and_accumulates_count(
        self, tmp_path, monkeypatch
    ):
        """set_by_user=True 時只抑制翻旗標；judged_at_version 蓋章、count 照常累積。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(
            disabled=False,
            consecutive_timeout_count=0,
            judged_at_version="old-version",
            set_by_user=True,
        )

        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        fd = _read_focal_device()
        assert fd["disabled"] is False
        assert fd["set_by_user"] is True
        assert fd["consecutive_timeout_count"] == 1
        assert fd["judged_at_version"] == VERSION

        assert device_state.record_outcome(_abandoned("detect_timeout")) is False
        fd = _read_focal_device()
        assert fd["disabled"] is False
        assert fd["consecutive_timeout_count"] == 2
        assert fd["judged_at_version"] == VERSION

    def test_set_disabled_by_user_only_touches_disabled_and_set_by_user(
        self, tmp_path, monkeypatch
    ):
        """使用者切換只寫 disabled ＋ set_by_user；count／judged_at_version 逐字不變。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(
            disabled=False,
            consecutive_timeout_count=1,
            judged_at_version=VERSION,
            set_by_user=False,
        )

        before = _read_focal_device()
        device_state.set_disabled_by_user(True)
        after = _read_focal_device()

        assert after["disabled"] is True
        assert after["set_by_user"] is True
        assert after["consecutive_timeout_count"] == before["consecutive_timeout_count"]
        assert after["judged_at_version"] == before["judged_at_version"]
        assert device_state.is_disabled() is True

        device_state.set_disabled_by_user(False)
        after2 = _read_focal_device()
        assert after2["disabled"] is False
        assert after2["set_by_user"] is True  # 仍標記為使用者決定
        assert after2["consecutive_timeout_count"] == before["consecutive_timeout_count"]
        assert after2["judged_at_version"] == before["judged_at_version"]


# ---------------------------------------------------------------------------
# feature/152d TASK-D2 — record_manual_outcome：前景單次逾時判定、不發 sink
# ---------------------------------------------------------------------------


class TestRecordManualOutcome:
    def test_record_manual_outcome_does_not_call_sink(self, tmp_path, monkeypatch):
        """前景轉態不呼叫 notification sink（CD-152d-5）——即使 sink 會拋例外也不影響。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(judged_at_version=VERSION)

        calls = []

        def _boom_sink(*args, **kwargs):
            calls.append((args, kwargs))
            raise RuntimeError("sink must not be called on manual path")

        monkeypatch.setattr(device_state, "_notification_sink", _boom_sink)

        just = device_state.record_manual_outcome(_abandoned("detect_timeout"))
        assert just is True
        assert calls == []
        assert device_state.is_disabled() is True

    def test_record_manual_outcome_single_timeout_disables(self, tmp_path, monkeypatch):
        """前景單次 detect_timeout 就翻 disabled（不必累積到背景的 2 次門檻）。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(
            disabled=False,
            consecutive_timeout_count=0,
            judged_at_version=VERSION,
        )

        just = device_state.record_manual_outcome(_abandoned("detect_timeout"))
        assert just is True
        fd = _read_focal_device()
        assert fd["disabled"] is True
        assert fd["consecutive_timeout_count"] == 0  # count_timeouts=False：不碰 streak
        assert fd["judged_at_version"] == VERSION
        assert device_state.is_disabled() is True

    def test_record_manual_outcome_set_by_user_suppresses_flip_but_stamps_version(
        self, tmp_path, monkeypatch
    ):
        """set_by_user=True 時抑制翻旗標，但仍蓋章 judged_at_version。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(
            disabled=False,
            consecutive_timeout_count=0,
            judged_at_version="old-version",
            set_by_user=True,
        )

        just = device_state.record_manual_outcome(_abandoned("detect_timeout"))
        assert just is False
        fd = _read_focal_device()
        assert fd["disabled"] is False
        assert fd["set_by_user"] is True
        assert fd["consecutive_timeout_count"] == 0
        assert fd["judged_at_version"] == VERSION
        assert device_state.is_disabled() is False

    def test_manual_success_does_not_reset_background_streak(self, tmp_path, monkeypatch):
        """前景 FOUND 不得清掉背景累積的 consecutive_timeout_count。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(
            disabled=False,
            consecutive_timeout_count=1,
            judged_at_version=VERSION,
        )

        just = device_state.record_manual_outcome(_found())
        assert just is False
        fd = _read_focal_device()
        assert fd["consecutive_timeout_count"] == 1

    def test_background_threshold_still_reachable_after_manual_success(
        self, tmp_path, monkeypatch
    ):
        """背景逾時→前景成功→背景再逾時，仍能湊到門檻 2 並翻 disabled。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(
            disabled=False,
            consecutive_timeout_count=1,
            judged_at_version=VERSION,
        )

        assert device_state.record_manual_outcome(_found()) is False
        assert _read_focal_device()["consecutive_timeout_count"] == 1

        just_disabled = device_state.record_outcome(_abandoned("detect_timeout"))
        fd = _read_focal_device()
        assert fd["consecutive_timeout_count"] == 2
        assert fd["disabled"] is True
        assert just_disabled is True

    def test_record_outcome_found_still_resets_streak(self, tmp_path, monkeypatch):
        """背景路徑 FOUND 仍須歸零 streak（迴歸鎖；不得被 count_timeouts 守衛誤傷）。"""
        from core.focal import device_state
        from core.version import VERSION

        _patch_config_paths(tmp_path, monkeypatch)
        _seed_focal_device(
            disabled=False,
            consecutive_timeout_count=1,
            judged_at_version=VERSION,
        )

        just = device_state.record_outcome(_found())
        assert just is False
        fd = _read_focal_device()
        assert fd["consecutive_timeout_count"] == 0
