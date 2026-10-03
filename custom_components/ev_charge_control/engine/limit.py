"""The power limit the controller works with."""

from __future__ import annotations


def effective_power_limit(
    base_w: float, monthly_peak_w: float | None, factor: float, follow: bool
) -> float:
    """The base limit, raised to a share of the monthly peak when following it.

    The capacity tariff bills the highest quarter-hour of the month. Once that
    peak is set, charging up to a share of it costs nothing extra, so the
    limit may rise to `factor x peak`. It never drops below the base limit.
    """
    if not follow or monthly_peak_w is None:
        return base_w
    return max(base_w, factor * monthly_peak_w)
