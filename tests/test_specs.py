"""Config entry options become engine specs."""

from __future__ import annotations

from custom_components.ev_charge_control.engine import CarSpec, ChargerSpec, Phase
from custom_components.ev_charge_control.inputs import (
    Tuning,
    car_spec,
    charger_spec,
    tuning,
)


def test_charger_spec_from_options():
    spec = charger_spec(
        {
            "min_current_a": 6,
            "fallback_current_a": 8,
            "voltage_v": 230,
            "current_step_a": "1",
            "widen_small_decreases": True,
            "failsafe_keeps_phase": True,
            "fallback_phase": "3",
        }
    )
    assert spec == ChargerSpec(
        min_current_a=6,
        fallback_current_a=8,
        voltage_v=230,
        current_step_a=1.0,
        widen_small_decreases=True,
        failsafe_keeps_phase=True,
        fallback_phase=Phase.THREE,
    )


def test_charger_spec_defaults():
    assert charger_spec({}) == ChargerSpec()


def test_no_soc_sensor_means_no_car():
    assert car_spec({"car_max_current_a": 16}) is None


def test_car_capacity_in_wh():
    spec = car_spec(
        {
            "car_soc_entity": "sensor.test_soc",
            "battery_capacity_kwh": 74,
            "car_max_current_a": 16,
            "car_min_current_a": 6,
        }
    )
    assert spec == CarSpec(max_current_a=16, min_current_a=6, battery_capacity_wh=74000)


def test_tuning_defaults_match_the_yaml_package():
    assert tuning({}) == Tuning(
        power_update_threshold_w=230,
        phase_hold_s=300,
        recalc_interval_s=10,
        peak_factor=0.9,
    )


def test_tuning_from_options():
    t = tuning(
        {
            "power_update_threshold_w": 460,
            "phase_switch_delay_min": 2,
            "recalc_interval_s": 30,
            "peak_factor_pct": 80,
        }
    )
    assert t == Tuning(460, 120, 30, 0.8)
