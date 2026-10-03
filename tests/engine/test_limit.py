"""The effective power limit."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from custom_components.ev_charge_control.engine.limit import effective_power_limit

watts = st.floats(min_value=0, max_value=30000, allow_nan=False)
peak = st.one_of(st.none(), watts)
factor = st.floats(min_value=0.5, max_value=1.0)


def test_follows_the_peak_when_it_is_higher():
    # 8 kW peak x 90 % = 7.2 kW, above the 5 kW base.
    assert effective_power_limit(5000, 8000, 0.9, True) == 7200


def test_base_wins_when_the_peak_is_low():
    assert effective_power_limit(5000, 2500, 0.9, True) == 5000


def test_follow_off_uses_the_base():
    assert effective_power_limit(5000, 8000, 0.9, False) == 5000


def test_unknown_peak_uses_the_base():
    assert effective_power_limit(5000, None, 0.9, True) == 5000


@given(base=watts, peak_w=peak, f=factor, follow=st.booleans())
def test_never_below_the_base(base, peak_w, f, follow):
    assert effective_power_limit(base, peak_w, f, follow) >= base


@given(base=watts, peak_w=peak, f=factor)
def test_follow_off_always_equals_the_base(base, peak_w, f):
    assert effective_power_limit(base, peak_w, f, False) == base
