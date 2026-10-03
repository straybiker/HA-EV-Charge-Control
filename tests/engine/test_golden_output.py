"""The 13 golden cases from the original Jinja test, with exact values.

The Jinja test accepted 13.7 A and 8.6 A within a 0.2 A tolerance. The
template actually produces 13.8 A and 8.7 A. The engine must match the
template, not the rounded expectation.
"""

from __future__ import annotations

import pytest

from custom_components.ev_charge_control.engine import ChargeMode, Phase

EMS_ZERO_NO_PV = {"ems_control": True, "pv_prioritized": False}
EMS_ZERO_PV = {"ems_control": True, "pv_prioritized": True}

CASES = [
    # name, mode, household W, settings, ems_signal W, expected phase, expected A
    ("fast plenty", ChargeMode.FAST, 500, {}, 0.0, Phase.THREE, 13.8),
    ("fast low headroom", ChargeMode.FAST, 7000, {}, 0.0, Phase.ONE, 13.0),
    ("3p min enough", ChargeMode.MIN_3P, 500, {}, 0.0, Phase.THREE, 6.0),
    ("3p min low headroom", ChargeMode.MIN_3P, 8000, {}, 0.0, Phase.THREE, 0.0),
    ("1p min enough", ChargeMode.MIN_1P, 500, {}, 0.0, Phase.ONE, 6.0),
    ("solar no sun", ChargeMode.SOLAR, 500, {}, 0.0, Phase.ONE, 0.0),
    ("solar 6 kW surplus", ChargeMode.SOLAR, -6000, {}, 0.0, Phase.THREE, 8.7),
    (
        "ems 0 limited no pv",
        ChargeMode.LIMITED,
        -6000,
        EMS_ZERO_NO_PV,
        0.0,
        Phase.ONE,
        0.0,
    ),
    ("ems 0 limited pv", ChargeMode.LIMITED, -6000, EMS_ZERO_PV, 0.0, Phase.THREE, 8.7),
    ("ems 0 fast no pv", ChargeMode.FAST, -6000, EMS_ZERO_NO_PV, 0.0, Phase.ONE, 0.0),
    ("ems 0 fast pv", ChargeMode.FAST, -6000, EMS_ZERO_PV, 0.0, Phase.THREE, 8.7),
    (
        "ems 0 solar no pv",
        ChargeMode.SOLAR,
        -6000,
        EMS_ZERO_NO_PV,
        0.0,
        Phase.THREE,
        8.7,
    ),
    (
        "ems 3 kW limited",
        ChargeMode.LIMITED,
        -1000,
        EMS_ZERO_NO_PV,
        3000.0,
        Phase.ONE,
        16.0,
    ),
]


@pytest.mark.parametrize(
    ("mode", "household_w", "settings", "ems_signal_w", "phase", "current_a"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_golden(run_case, mode, household_w, settings, ems_signal_w, phase, current_a):
    d = run_case(
        mode,
        household_w,
        settings=settings,
        measurements={"ems_signal_w": ems_signal_w},
    )
    assert d.should_write
    assert d.phase == phase
    assert d.current_a == pytest.approx(current_a, abs=0.05)
