"""Runtime settings shared by the setting entities and the coordinator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, replace
from typing import Any

from .engine import Settings

# A setting the integration uses around the controller, not inside it.
CONTROL_CHARGER = "control_charger"
_EXTRA_DEFAULTS: dict[str, Any] = {CONTROL_CHARGER: False}
_ENGINE_FIELDS = {f.name for f in fields(Settings)}

type SettingsListener = Callable[[str], None]


class SettingsStore:
    """Holds the values of the setting entities.

    Entities write here; the coordinator reads a frozen snapshot. Listeners
    hear about changes made by the user, not about restores at start-up.
    """

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._settings = Settings()
        self._initial = dict(initial or {})
        self._extra: dict[str, Any] = dict(_EXTRA_DEFAULTS)
        self._listeners: list[SettingsListener] = []

    def initial(self, entity_key: str, default: Any) -> Any:
        """The first value of a setting entity: imported, else its default."""
        return self._initial.get(entity_key, default)

    def snapshot(self) -> Settings:
        return self._settings

    def get(self, key: str) -> Any:
        if key in self._extra:
            return self._extra[key]
        return getattr(self._settings, key)

    def set(self, key: str, value: Any, *, notify: bool = True) -> None:
        if key in self._extra:
            self._extra[key] = value
        elif key in _ENGINE_FIELDS:
            self._settings = replace(self._settings, **{key: value})
        else:
            raise KeyError(key)
        if notify:
            for listener in list(self._listeners):
                listener(key)

    def extras(self) -> dict[str, Any]:
        return dict(self._extra)

    def add_listener(self, listener: SettingsListener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)
