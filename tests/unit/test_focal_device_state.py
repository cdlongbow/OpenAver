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
) -> None:
    save_config(
        {
            "focal_device": {
                "disabled": disabled,
                "consecutive_timeout_count": consecutive_timeout_count,
                "judged_at_version": judged_at_version,
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
