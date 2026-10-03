"""Importing the EV Load Balancer package: parsing and mapping. All ids are fake."""

from __future__ import annotations

from custom_components.ev_charge_control.yaml_import import (
    _find_user_config,
    initial_settings,
    input_options,
    parse_package,
    value_options,
)

USER_CONFIG = """
template:
  - sensor:
      # Household settings
      - unique_id: ev_load_balancer_house
        name: EV Load Balancer House
        availability: "{{ has_value('sensor.test_house') }}"
        state: "{{ states('sensor.test_house') | int(0) }}"
        attributes:
          pv_power: "{{ states('sensor.test_pv') }}"

      - unique_id: ev_load_balancer_charger
        name: EV Load Balancer Charger
        state: Test charger
        attributes:
          active_power: "{{ states('sensor.test_power') }}"
          current_input: "{{ states('sensor.test_applied') }}"
          current_output: number.test_limit
          phases_input: "{{ states('sensor.test_phases') }}"
          phases_output: select.test_phases
          max_current: "{{ states('sensor.test_max') | int }}"
          min_current: "{{ 6 | int }}"
          connection_state: >
            {% set m3 = states('sensor.test_mode3') %}
            {% if m3 in ['A', 'E'] %} Disconnected
            {% else %} Connected
            {% endif %}

      - unique_id: ev_load_balancer_car
        attributes:
          battery_percentage: "{{ states('sensor.test_soc') | int }}"

      - unique_id: ev_load_balancer
        attributes:
          power_limit: "{{ states('input_number.test_limit') | int }}"
          ems_signal: "{{ states('sensor.test_ems') | float(0) }}"
          electricity_price: "{{ state_attr('sensor.test_price','rate_import') }}"
"""


def test_parse_keeps_nested_keys_and_multiline_templates():
    blocks = parse_package(USER_CONFIG)
    charger = blocks["ev_load_balancer_charger"]
    assert charger["current_output"] == "number.test_limit"
    assert "sensor.test_mode3" in charger["connection_state"]
    assert "Connected" in charger["connection_state"]
    assert charger["min_current"] == '"{{ 6 | int }}"'


def test_input_entities_from_the_templates():
    assert input_options(USER_CONFIG) == {
        "house_power_entity": "sensor.test_house",
        "solar_power_entity": "sensor.test_pv",
        "charger_power_entity": "sensor.test_power",
        "applied_current_entity": "sensor.test_applied",
        "active_phases_entity": "sensor.test_phases",
        "connection_entity": "sensor.test_mode3",
        "max_current_entity": "sensor.test_max",
        "car_soc_entity": "sensor.test_soc",
        "power_limit_entity": "input_number.test_limit",
        "ems_entity": "sensor.test_ems",
        "price_entity": "sensor.test_price",
        "price_attribute": "rate_import",
    }


def test_values_from_the_rendered_attributes():
    charger = {
        "current_output": "number.test_limit",
        "phases_output": "select.test_phases",
        "phase_1_state": "1 Phase",
        "phase_3_state": "3 Phases",
        "min_current": 6,
        "default_current": 7,
        "default_phases": 1,
        "nominal_voltage": 230,
    }
    car = {"max_current": 16, "min_current": 6, "battery_capacity_wh": 74000}
    balancer = {"power_update_threshold": 230.0, "phase_switch_delay": 5}
    assert value_options(charger, car, balancer) == {
        "current_limit_entity": "number.test_limit",
        "phase_select_entity": "select.test_phases",
        "phase_option_1": "1 Phase",
        "phase_option_3": "3 Phases",
        "min_current_a": 6.0,
        "fallback_current_a": 7.0,
        "voltage_v": 230.0,
        "car_max_current_a": 16.0,
        "car_min_current_a": 6.0,
        "power_update_threshold_w": 230.0,
        "phase_switch_delay_min": 5.0,
        "fallback_phase": "1",
        "battery_capacity_kwh": 74.0,
        "current_step_a": "0_1",
        "widen_small_decreases": True,
    }


BALANCER = {
    "power_limit": 5200,
    "car_aware": True,
    "pv_prioritized": False,
    "pv_prio_threshold": 500.0,
    "single_phase_only": False,
    "ems_as_onoff": True,
    "ems_control": "False",
    "max_cost_rate": 0.29,
    "emergency_soc": 20,
    "comfort_soc": 45,
    "target_soc": 100,
}


def test_settings_follow_the_package():
    assert initial_settings("Limited", BALANCER) == {
        "charge_mode": "limited",
        "max_charging_cost": 0.29,
        "target_soc": 100.0,
        "comfort_soc": 45.0,
        "emergency_soc": 20.0,
        "solar_bridge": 500.0,
        "car_aware": True,
        "single_phase_only": False,
        "ems_control": False,
        "ems_as_onoff": True,
        "solar_when_ems_blocks": False,
    }


def test_limited_with_solar_priority_becomes_solar_mode():
    settings = initial_settings("Limited", BALANCER | {"pv_prioritized": True})
    assert settings["charge_mode"] == "solar"
    assert settings["solar_bridge"] == 500.0
    assert settings["solar_when_ems_blocks"] is True


def test_package_solar_mode_was_pure_solar():
    assert initial_settings("Solar", BALANCER)["solar_bridge"] == 0.0


def test_control_charger_is_never_imported():
    assert "control_charger" not in initial_settings("Fast", BALANCER | {"x": 1})


def test_finds_the_file_that_defines_the_sensors(tmp_path):
    """The logic file reads the charger sensor too; it must not be picked."""
    packages = tmp_path / "packages"
    packages.mkdir()
    (packages / "a_logic.yaml").write_text(
        "variables:\n"
        "  out: \"{{ state_attr('sensor.ev_load_balancer_charger', "
        "'current_output') }}\"\n",
        "utf-8",
    )
    (packages / "b_user_config.yaml").write_text(USER_CONFIG, "utf-8")
    text = _find_user_config(str(tmp_path))
    assert text is not None
    assert input_options(text)["charger_power_entity"] == "sensor.test_power"


def test_no_user_config_file(tmp_path):
    assert _find_user_config(str(tmp_path)) is None
