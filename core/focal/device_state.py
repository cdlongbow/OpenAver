"""Device-level focal auto-disable (feature/152c TASK-4).

Two consecutive ABANDONED("detect_timeout") outcomes mark the machine as too
slow for auto-focus. Version mismatch lazy-resets: reads look enabled
immediately; the next write clears streak/disabled before applying the event
(CD-152b-5 / CD-152b-7 / CD-152b-8).
"""

from __future__ import annotations

from typing import Callable, Optional

from core.config import load_config, mutate_config
from core.focal.subprocess_runner import RunnerOutcome
from core.logger import get_logger
from core.version import VERSION

logger = get_logger(__name__)

_DISABLE_THRESHOLD = 2

# CD-152c-20：依賴反轉的通知埠。core/ 不可 import web/（import-linter 契約），
# 所以 web/app.py 在 module level 呼叫 set_notification_sink(emit_notification)
# 註冊真正的實作；未註冊時是 no-op，純 core 測試與非 web 進入點自然靜音。
_notification_sink: Optional[Callable[..., None]] = None


def set_notification_sink(fn: Callable[..., None]) -> None:
    """Register the callable record_outcome() uses to emit a disable notice."""
    global _notification_sink
    _notification_sink = fn


def is_disabled() -> bool:
    """True only when persisted disabled flag matches the running App VERSION."""
    cfg = load_config()
    fd = cfg.get("focal_device", {})
    return bool(fd.get("disabled", False)) and fd.get("judged_at_version", "") == VERSION


def record_outcome(outcome: RunnerOutcome) -> bool:
    """Apply one RunnerOutcome to focal_device. Returns just_disabled.

    just_disabled is True only on the False→True crossing of ``disabled``
    (same shape as subprocess_runner._apply_breaker's just_tripped). Exceptions
    from mutate_config / save propagate unchanged — callers own the try/except.
    """
    just_disabled = False

    def mutator(cfg: dict) -> None:
        nonlocal just_disabled
        # Reset first: mutate_config does not retry, but a stale True would
        # make T10 emit a spurious "auto-focus disabled" notification.
        just_disabled = False

        fd = cfg.setdefault("focal_device", {})
        judged_version = fd.get("judged_at_version", "")
        if judged_version != VERSION:
            fd["disabled"] = False
            fd["consecutive_timeout_count"] = 0

        if outcome.kind in ("FOUND", "NO_FACE"):
            fd["consecutive_timeout_count"] = 0
        elif outcome.kind == "ABANDONED":
            reason = outcome.reason
            if reason == "detect_timeout":
                count = int(fd.get("consecutive_timeout_count", 0)) + 1
                fd["consecutive_timeout_count"] = count
                if count >= _DISABLE_THRESHOLD:
                    was_disabled = bool(fd.get("disabled", False))
                    fd["disabled"] = True
                    just_disabled = not was_disabled
            # startup_timeout / crashed / skipped_disabled / circuit_open: no-op

        fd["judged_at_version"] = VERSION

    mutate_config(mutator)

    if just_disabled and _notification_sink is not None:
        try:
            _notification_sink("warn", "notif.focal_auto_disabled")
        except Exception:
            logger.exception("focal_device notification sink raised; record_outcome result unaffected")

    return just_disabled
