"""WAVE 7 — full system mixed load helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "wave7_full_system.py"


def _load_wave7():
    spec = importlib.util.spec_from_file_location("wave7_full_system", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_mixed_flow_cycle_covers_all_flows():
    w7 = _load_wave7()
    names = {n for n, _ in w7.MIXED_FLOWS}
    cycle_names = set(w7._FLOW_CYCLE)
    assert names == cycle_names
    assert len(w7._FLOW_CYCLE) == sum(w for _, w in w7.MIXED_FLOWS)


def test_gate_memory_leak_passes_stable_ram():
    w7 = _load_wave7()
    soak = [{"ram_growth_mb_per_hour": 50, "ram_growth_mb": 50, "duration_sec": 180}]
    result = w7._gate_memory_leak(soak)
    assert result["gate"] == "PASS"


def test_gate_memory_leak_passes_negative_growth():
    w7 = _load_wave7()
    soak = [{"ram_growth_mb": -200, "duration_sec": 180}]
    result = w7._gate_memory_leak(soak)
    assert result["gate"] == "PASS"


def test_gate_memory_leak_fails_runaway():
    w7 = _load_wave7()
    soak = [{"ram_growth_mb": 500, "duration_sec": 180}]
    result = w7._gate_memory_leak(soak)
    assert result["gate"] == "FAIL"


def test_gate_queue_drain():
    w7 = _load_wave7()
    ok = w7._gate_queue_drain([{"label": "a", "queue_drained": True}])
    bad = w7._gate_queue_drain([{"label": "a", "queue_drained": False}])
    assert ok["gate"] == "PASS"
    assert bad["gate"] == "FAIL"


def test_gate_memory_leak_2h_negative_growth():
    w7 = _load_wave7()
    soak = {"ram_growth_mb": -100, "ram_growth_mb_per_hour": -200, "duration_sec": 7200}
    result = w7._gate_memory_leak_2h(soak)
    assert result["gate"] == "PASS"
