"""The power limit: the limit entity's value times the safety factor."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from custom_components.ev_charge_control.engine.limit import effective_power_limit

watts = st.floats(min_value=1, max_value=50_000, allow_nan=False)
factor = st.floats(min_value=0.5, max_value=1.0, allow_nan=False)


def test_factor_keeps_a_buffer_below_the_limit():
    assert effective_power_limit(8000, 0.9) == 7200


def test_full_factor_uses_the_limit():
    assert effective_power_limit(5200, 1.0) == 5200


def test_no_value_means_no_limit():
    assert effective_power_limit(None, 0.9) == 0
    assert effective_power_limit(0, 0.9) == 0


@given(limit=watts, f=factor)
def test_never_above_the_limit(limit, f):
    assert 0 < effective_power_limit(limit, f) <= limit
