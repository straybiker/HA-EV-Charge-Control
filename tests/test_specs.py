"""Config entry options become engine specs."""

from __future__ import annotations

from custom_components.ev_charge_control.engine import CarSpec, ChargerSpec
from custom_components.ev_charge_control.inputs import car_spec, charger_spec


def test_charger_spec_from_options():
    spec = charger_spec(
        {
            "max_current_a": 32,
            "min_current_a": 6,
            "fallback_current_a": 8,
            "voltage_v": 230,
            "current_step_a": "1",
            "widen_small_decreases": True,
            "failsafe_keeps_phase": True,
        }
    )
    assert spec == ChargerSpec(
        max_current_a=32,
        min_current_a=6,
        fallback_current_a=8,
        voltage_v=230,
        current_step_a=1.0,
        widen_small_decreases=True,
        failsafe_keeps_phase=True,
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
