"""The controller: one step per run, with the state that runs share."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from .budget import Limits, ems_stops_charging, grid_gate_open, plan
from .model import (
    Available,
    CarSpec,
    ChargeMode,
    ChargerSpec,
    ConnectionState,
    Measurements,
    Output,
    Phase,
    Reason,
    Settings,
)
from .phases import choose_phase
from .policy import MODE_POLICY, ModePolicy, resolve_mode
from .setpoint import filter_write, to_current

# After a 1 -> 3 phase switch the charger sensors lag; wait before deciding.
GRACE_PERIOD = timedelta(seconds=40)
# A car that stays unplugged this long gets the fallback setpoint, so the next
# session starts gently.
RESET_AFTER_DISCONNECT = timedelta(seconds=60)

# Efficiency compares measured power with commanded current. A car that
# draws less than its limit looks inefficient, so real losses set a floor.
EFFICIENCY_FLOOR = 0.85
# Below this the power reading is too noisy to learn from.
EFFICIENCY_MIN_POWER_W = 1000.0
# Weight of a new sample in the running efficiency estimate.
EFFICIENCY_SMOOTHING = 0.3


class Controller:
    """Turns settings and measurements into a charger setpoint.

    Create one per charger and call step() on every run. The controller
    keeps the phase hold, the grace period and the efficiency estimates.
    """

    def __init__(self, charger: ChargerSpec, car: CarSpec | None = None) -> None:
        self.charger = charger
        self.car = car
        self._last_phase: Phase | None = None
        self._phase_hold_until: datetime | None = None
        self._grace_until: datetime | None = None
        # One estimate per phase count: the losses differ (B21).
        self._efficiency = {Phase.ONE: 1.0, Phase.THREE: 1.0}
        self._last_sample: tuple[float, Phase] | None = None
        self._disconnected_since: datetime | None = None

    def step(self, settings: Settings, m: Measurements, now: datetime) -> Output:
        car_aware = self._car_aware(settings, m)
        self._observe_phase(settings, m, car_aware, now)
        self._learn_efficiency(m)
        out = self._decide(settings, m, car_aware, now)
        # Whether the grid may be used depends only on price and EMS, so it
        # is known also when nothing is charging.
        grid_allowed = out.grid_allowed
        if grid_allowed is None:
            policy = self._policy(settings, m, car_aware)
            grid_allowed = grid_gate_open(settings, m, policy)
        return replace(
            out,
            grid_allowed=grid_allowed,
            efficiency=self._efficiency[_shown_phase(out, m)],
            phase_hold_until=_active(self._phase_hold_until, now),
            grace_until=_active(self._grace_until, now),
        )

    def efficiency_state(self) -> dict[str, float]:
        """The learned efficiencies, to save between restarts (B21)."""
        return {str(int(phase)): eff for phase, eff in self._efficiency.items()}

    def restore_efficiency(self, state: dict[str, Any] | None) -> None:
        """Take saved efficiencies back; values out of range are ignored."""
        for phase in Phase:
            value = (state or {}).get(str(int(phase)))
            if isinstance(value, int | float) and EFFICIENCY_FLOOR <= value <= 1.0:
                self._efficiency[phase] = float(value)

    def available(
        self, settings: Settings, m: Measurements, now: datetime
    ) -> Available | None:
        """The power the car would get now in the current mode, as if it were
        connected and charging, with the solar and grid parts.

        It follows the same plan, phase choice and rounding as step(), so
        while the car charges it equals the target power. It changes no
        state. None while the house power is unknown.
        """
        if m.house_power_w is None:
            return None
        nothing = Available(solar_w=0.0, grid_w=0.0)
        if settings.mode == ChargeMode.OFF or settings.power_limit_w <= 0:
            return nothing
        if settings.mode == ChargeMode.MIN_3P and settings.single_phase_only:
            return nothing
        car_aware = self._car_aware(settings, m)
        policy = self._policy(settings, m, car_aware)
        assert policy is not None
        soc = m.car_soc if m.car_soc is not None else 0.0
        emergency = car_aware and soc < settings.emergency_soc
        if car_aware and not emergency and soc >= settings.target_soc:
            return nothing
        min_a, max_a = self._current_range(car_aware)
        volts = self.charger.voltage_v
        limits = self._limits(min_a, max_a)
        budget = plan(
            settings, m, policy, limits, emergency, grid_gate_open(settings, m, policy)
        )
        target_w = min(budget.request_w, budget.headroom_w, limits.max_w)
        hold_active = (
            self._phase_hold_until is not None and now < self._phase_hold_until
        )
        phase = choose_phase(
            policy,
            settings,
            target_w / (volts * 3 * self._efficiency[Phase.THREE]),
            min_a,
            m.commanded_phase,
            hold_active,
        )
        eff = self._efficiency[phase]
        current = to_current(
            target_w, phase, self.charger, eff, min_a, max_a, budget.headroom_w
        )
        total_w = current * volts * int(phase) * eff
        solar_w = min(budget.solar_w, total_w)
        return Available(solar_w=solar_w, grid_w=total_w - solar_w)

    # --- state -------------------------------------------------------------

    def _car_aware(self, settings: Settings, m: Measurements) -> bool:
        """Car data counts only when switched on and complete (D08)."""
        return (
            settings.car_aware
            and self.car is not None
            and self.car.battery_capacity_wh is not None
            and m.car_soc is not None
        )

    def _observe_phase(
        self, settings: Settings, m: Measurements, car_aware: bool, now: datetime
    ) -> None:
        """Start the timers from phase changes the charger actually made.

        The first observation after start-up is not a change (B8).
        """
        new = m.commanded_phase
        if new is None:
            return
        previous, self._last_phase = self._last_phase, new
        if previous is None or previous == new:
            return
        if new == Phase.ONE:
            policy = self._policy(settings, m, car_aware)
            if (
                policy is not None
                and policy.phase_hold
                and m.connection == ConnectionState.CONNECTED
            ):
                self._phase_hold_until = now + timedelta(seconds=settings.phase_hold_s)
        else:
            self._grace_until = now + GRACE_PERIOD

    def _learn_efficiency(self, m: Measurements) -> None:
        """Running estimate of measured power over commanded power (B6).

        One estimate per phase count, kept across sessions (B21). Learns only
        while the applied current and the phases are steady, so ramps after a
        setpoint or phase change do not count.
        """
        if m.connection != ConnectionState.CONNECTED:
            self._last_sample = None
            return
        applied, power, phases = (
            m.applied_current_a,
            m.charger_power_w,
            m.active_phases,
        )
        if applied is None or power is None or phases is None:
            return
        steady = (applied, phases) == self._last_sample
        self._last_sample = (applied, phases)
        if not steady or applied <= 0 or power <= EFFICIENCY_MIN_POWER_W:
            return
        sample = power / (applied * self.charger.voltage_v * int(phases))
        sample = min(max(sample, EFFICIENCY_FLOOR), 1.0)
        eff = self._efficiency[phases]
        self._efficiency[phases] = eff + EFFICIENCY_SMOOTHING * (sample - eff)

    def _policy(
        self, settings: Settings, m: Measurements, car_aware: bool
    ) -> ModePolicy | None:
        if settings.mode == ChargeMode.OFF:
            return None
        mode = resolve_mode(settings.mode, car_aware, m.car_soc, settings.comfort_soc)
        return MODE_POLICY[mode]

    # --- decision -----------------------------------------------------------

    def _decide(
        self, settings: Settings, m: Measurements, car_aware: bool, now: datetime
    ) -> Output:
        skipped = self._skip(settings, m, now)
        if skipped is not None:
            return skipped

        assert m.commanded_phase is not None
        assert m.commanded_current_a is not None
        min_a, max_a = self._current_range(car_aware)

        if None in (
            m.house_power_w,
            m.charger_power_w,
            m.applied_current_a,
            m.active_phases,
        ):
            # Never raise the current. The phase goes to the safe fallback
            # phase, so a charger that stops responding is not left on an
            # unintended phase, unless the charger option keeps it (D11).
            current = min(m.commanded_current_a, self.charger.fallback_current_a)
            phase = (
                m.commanded_phase
                if self.charger.failsafe_keeps_phase
                else self.charger.fallback_phase
            )
            return self._result(Reason.FAILSAFE, phase, current, settings, m, min_a)

        if settings.mode == ChargeMode.MIN_3P and settings.single_phase_only:
            return self._result(Reason.REFUSED, Phase.ONE, 0.0, settings, m, min_a)
        if settings.mode == ChargeMode.OFF:
            return self._result(Reason.OFF, m.commanded_phase, 0.0, settings, m, min_a)

        policy = self._policy(settings, m, car_aware)
        assert policy is not None
        soc = m.car_soc if m.car_soc is not None else 0.0
        emergency = car_aware and soc < settings.emergency_soc
        target_reached = car_aware and not emergency and soc >= settings.target_soc
        stop_phase = policy.forced_phase or m.commanded_phase
        gate_open = grid_gate_open(settings, m, policy)

        if target_reached:
            return self._result(
                Reason.TARGET_REACHED,
                stop_phase,
                0.0,
                settings,
                m,
                min_a,
                grid_allowed=gate_open,
                target_reached=True,
            )

        volts = self.charger.voltage_v
        limits = self._limits(min_a, max_a)
        budget = plan(settings, m, policy, limits, emergency, gate_open)
        target_w = min(budget.request_w, budget.headroom_w, limits.max_w)

        hold_active = (
            self._phase_hold_until is not None and now < self._phase_hold_until
        )
        current_3p = target_w / (volts * 3 * self._efficiency[Phase.THREE])
        phase = choose_phase(
            policy, settings, current_3p, min_a, m.commanded_phase, hold_active
        )
        current = to_current(
            target_w,
            phase,
            self.charger,
            self._efficiency[phase],
            min_a,
            max_a,
            budget.headroom_w,
        )

        if current > 0:
            reason = Reason.EMERGENCY if emergency else Reason.CHARGING
        else:
            phase = stop_phase
            blocked = not gate_open or ems_stops_charging(settings, m, policy)
            reason = Reason.GRID_BLOCKED if blocked else Reason.INSUFFICIENT_POWER

        return self._result(
            reason,
            phase,
            current,
            settings,
            m,
            min_a,
            grid_allowed=emergency or gate_open,
            emergency=emergency,
            budget=budget,
        )

    def _skip(
        self, settings: Settings, m: Measurements, now: datetime
    ) -> Output | None:
        """Runs that write nothing, or only the reset after a disconnect."""
        if m.connection != ConnectionState.CONNECTED:
            return self._not_connected(settings, m, now)
        self._disconnected_since = None
        if m.commanded_phase is None or m.commanded_current_a is None:
            return _skipped(Reason.CHARGER_UNAVAILABLE)
        if settings.power_limit_w <= 0:
            return _skipped(Reason.NO_POWER_LIMIT)
        if self._grace_until is not None and now < self._grace_until:
            return _skipped(Reason.GRACE_PERIOD)
        return None

    def _not_connected(
        self, settings: Settings, m: Measurements, now: datetime
    ) -> Output:
        if m.connection != ConnectionState.DISCONNECTED:
            self._disconnected_since = None
            return _skipped(Reason.NOT_CONNECTED)
        if self._disconnected_since is None:
            self._disconnected_since = now
        if now - self._disconnected_since < RESET_AFTER_DISCONNECT:
            return _skipped(Reason.NOT_CONNECTED)
        reset = self._result(
            Reason.NOT_CONNECTED,
            self.charger.fallback_phase,
            self.charger.fallback_current_a,
            settings,
            m,
            self.charger.min_current_a,
        )
        # The fallback setpoint prepares the next session; without a car
        # nothing is drawn, so the target power is 0.
        return replace(reset, power_w=0.0)

    def _current_range(self, car_aware: bool) -> tuple[float, float]:
        """The car narrows the charger range only when its data is trusted."""
        if car_aware and self.car is not None:
            return (
                max(self.car.min_current_a, self.charger.min_current_a),
                min(self.car.max_current_a, self.charger.max_current_a),
            )
        return self.charger.min_current_a, self.charger.max_current_a

    def _limits(self, min_a: float, max_a: float) -> Limits:
        """Charger power bounds, each with the efficiency of its phases."""
        volts = self.charger.voltage_v
        eff1, eff3 = self._efficiency[Phase.ONE], self._efficiency[Phase.THREE]
        return Limits(
            min_1p_w=min_a * volts * eff1,
            min_3p_w=min_a * volts * 3 * eff3,
            max_w=max_a * volts * 3 * eff3,
        )

    def _result(
        self,
        reason: Reason,
        phase: Phase,
        current: float,
        settings: Settings,
        m: Measurements,
        min_a: float,
        **extra: Any,
    ) -> Output:
        setpoint = filter_write(
            phase,
            current,
            m.commanded_phase,
            m.commanded_current_a,
            self.charger,
            min_a,
            settings.power_update_threshold_w,
        )
        eff = self._efficiency[phase]
        power = current * self.charger.voltage_v * int(phase) * eff
        return Output(
            reason=reason,
            phase=phase,
            current_a=current,
            power_w=power,
            efficiency=eff,
            setpoint=setpoint,
            **extra,
        )


def _skipped(reason: Reason) -> Output:
    return Output(
        reason=reason, phase=None, current_a=None, power_w=None, efficiency=1.0
    )


def _shown_phase(out: Output, m: Measurements) -> Phase:
    """The phases whose efficiency the output shows: the target's, else the
    charger's, else 1."""
    return out.phase or m.active_phases or m.commanded_phase or Phase.ONE


def _active(deadline: datetime | None, now: datetime) -> datetime | None:
    return deadline if deadline is not None and now < deadline else None
