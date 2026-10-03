"""The power limit the controller works with."""

from __future__ import annotations


def effective_power_limit(limit_w: float | None, factor: float) -> float:
    """The limit entity's value times the safety factor; 0 when it is unknown.

    The limit comes from a helper or an EMS, for example the month's capacity
    tariff peak. The factor keeps the house a margin below it. A limit of 0
    stops the controller (no power limit).
    """
    if limit_w is None or limit_w <= 0:
        return 0.0
    return limit_w * factor
