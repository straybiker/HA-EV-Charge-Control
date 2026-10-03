"""Skip the Home Assistant tests where their harness cannot run (Windows)."""

import importlib.util

collect_ignore = (
    [] if importlib.util.find_spec("pytest_homeassistant_custom_component") else ["ha"]
)
