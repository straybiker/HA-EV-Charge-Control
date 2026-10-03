"""Runtime settings shared by the setting entities and the coordinator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, replace
from typing import Any

from .const import DEFAULT_RECALC_INTERVAL_S
from .engine import Settings

RECALC_INTERVAL = "recalc_interval_s"
_ENGINE_FIELDS = {f.name for f in fields(Settings)}

type SettingsListener = Callable[[str], None]


class SettingsStore:
    """Holds the values of the setting entities.

    Entities write here; the coordinator reads a frozen snapshot. Listeners
    hear about changes made by the user, not about restores at start-up.
    """

    def __init__(self) -> None:
        self._settings = Settings()
        self.recalc_interval_s: float = DEFAULT_RECALC_INTERVAL_S
        self._listeners: list[SettingsListener] = []

    def snapshot(self) -> Settings:
        return self._settings

    def get(self, key: str) -> Any:
        if key == RECALC_INTERVAL:
            return self.recalc_interval_s
        return getattr(self._settings, key)

    def set(self, key: str, value: Any, *, notify: bool = True) -> None:
        if key == RECALC_INTERVAL:
            self.recalc_interval_s = float(value)
        elif key in _ENGINE_FIELDS:
            self._settings = replace(self._settings, **{key: value})
        else:
            raise KeyError(key)
        if notify:
            for listener in list(self._listeners):
                listener(key)

    def add_listener(self, listener: SettingsListener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)
