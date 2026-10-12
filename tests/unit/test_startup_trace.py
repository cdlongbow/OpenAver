"""core.startup_trace 純邏輯（166-T3）。"""
import importlib
import logging
import types

import pytest

from core import startup_trace

LOGGER = "OpenAver.startup"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    # BE-TEST-38：模組級狀態前後各 reload 歸零；測試一律用 startup_trace.<attr> 取用
    importlib.reload(startup_trace)
    yield
    importlib.reload(startup_trace)


def _clock(monkeypatch, seconds):
    it = iter(seconds)
    monkeypatch.setattr(startup_trace, "time", types.SimpleNamespace(perf_counter=lambda: next(it)))
    monkeypatch.setattr(startup_trace, "_T0", 0.0)


def _msgs(caplog):
    return [r.getMessage() for r in caplog.records if r.name == LOGGER]


def test_mark_before_flush_is_silent(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    _clock(monkeypatch, [0.1])
    startup_trace.mark("modules_loaded")
    assert _msgs(caplog) == []


def test_flush_replays_buffered_marks_with_original_cum(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    _clock(monkeypatch, [0.120, 0.150])
    startup_trace.mark("a")
    startup_trace.mark("b")
    startup_trace.flush()
    msgs = _msgs(caplog)
    assert msgs[1:] == ["啟動計時 a 累計 120ms（+120ms）", "啟動計時 b 累計 150ms（+30ms）"]


def test_armed_mark_writes_directly(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    _clock(monkeypatch, [0.2])
    startup_trace.flush()
    n = len(_msgs(caplog))
    startup_trace.mark("x")
    assert _msgs(caplog)[n:] == ["啟動計時 x 累計 200ms（+200ms）"]


def test_duplicate_key_is_logged_once(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    _clock(monkeypatch, [0.1, 0.2, 0.3, 0.4, 0.5])
    startup_trace.mark("a")
    startup_trace.mark("a")  # buffer 內重複
    startup_trace.flush()
    startup_trace.mark("b")
    startup_trace.mark("b")  # armed 後重複
    startup_trace.mark("a")
    msgs = [m for m in _msgs(caplog) if m.startswith("啟動計時 ")]
    assert [m.split()[1] for m in msgs] == ["a", "b"]


def test_total_written_once_after_first_page_loaded(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    _clock(monkeypatch, [0.1, 0.5, 0.9])
    startup_trace.flush()
    startup_trace.mark("server_ready")
    startup_trace.mark("first_page_loaded")
    startup_trace.mark("first_page_loaded")
    msgs = _msgs(caplog)
    assert msgs[-2:] == ["啟動計時 first_page_loaded 累計 500ms（+400ms）", "啟動計時 total 累計 500ms"]
    assert sum("total" in m for m in msgs) == 1


def test_total_written_once_when_first_page_loaded_is_buffered(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    _clock(monkeypatch, [0.3, 0.4])
    startup_trace.mark("first_page_loaded")
    startup_trace.flush()
    assert _msgs(caplog)[-1] == "啟動計時 total 累計 300ms"
    startup_trace.mark("first_page_loaded")
    assert sum("total" in m for m in _msgs(caplog)) == 1


def test_cum_is_whole_milliseconds_since_t0(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    _clock(monkeypatch, [0.0019, 1.2349, 3.0])
    startup_trace.flush()
    startup_trace.mark("a")
    startup_trace.mark("b")
    startup_trace.mark("c")
    assert [m.split("（")[0].split()[-1] for m in _msgs(caplog)[1:]] == ["1ms", "1234ms", "3000ms"]


def test_step_is_delta_from_previous_recorded_stage(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    _clock(monkeypatch, [0.120, 0.150, 0.500])
    startup_trace.flush()
    for k in ("a", "b", "c"):
        startup_trace.mark(k)
    assert [m.split("（")[1] for m in _msgs(caplog)[1:]] == ["+120ms）", "+30ms）", "+350ms）"]


def test_logger_name_level_and_baseline_once(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    _clock(monkeypatch, [0.1])
    startup_trace.mark("a")
    startup_trace.flush()
    startup_trace.flush()
    recs = [r for r in caplog.records if r.name == LOGGER]
    assert all(r.levelno == logging.INFO for r in recs)
    assert sum("載入起算" in r.getMessage() for r in recs) == 1
    assert len(recs) == 2
