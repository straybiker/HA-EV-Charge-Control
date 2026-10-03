"""Applying the controller's output to the charger.

The first release runs in shadow mode: it computes and shows the decision
but writes nothing. A writer that sets the charger's own entities will plug
in behind a "Control charger" switch.
"""

from __future__ import annotations

from typing import Protocol

from .engine import Output, Setpoint


class ChargerWriter(Protocol):
    last_setpoint: Setpoint | None

    async def async_apply(self, output: Output) -> None:
        """Perform output.setpoint, if any."""


class ShadowWriter:
    """Remembers what it would write, and writes nothing."""

    def __init__(self) -> None:
        self.last_setpoint: Setpoint | None = None

    async def async_apply(self, output: Output) -> None:
        if output.setpoint is not None:
            self.last_setpoint = output.setpoint
