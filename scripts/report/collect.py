"""Collect the test-report data.

Runs the full test suite and hassfest in Docker (the Home Assistant harness
needs Linux), evaluates the golden cases with the engine and, when the
sibling EV_Loadbalancer checkout exists, with the YAML package, and reads
the decision record. Writes build/report/data.json.

    python scripts/report/collect.py
    python scripts/report/build.py
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "report"
IMAGE = "ev-charge-control-tests"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from yaml_golden import available as yaml_available  # noqa: E402
from yaml_golden import yaml_result  # noqa: E402

from tests.engine import test_controller as tc  # noqa: E402
from tests.engine.conftest import result, step  # noqa: E402


def run_tests() -> tuple[str, list[dict]]:
    subprocess.run(
        [
            "docker",
            "build",
            "-q",
            "-f",
            "scripts/ha-tests.Dockerfile",
            "-t",
            IMAGE,
            ".",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{ROOT}:/src",
            "-v",
            f"{BUILD}:/out",
            IMAGE,
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:logging",
            "--junitxml=/out/junit.xml",
        ],
        capture_output=True,
        text=True,
    )
    summary = proc.stdout.strip().splitlines()[-1]
    tests = []
    for case in ET.parse(BUILD / "junit.xml").getroot().iter("testcase"):
        outcome, message = "passed", ""
        for child in case:
            if child.tag in ("failure", "error"):
                outcome, message = "failed", (child.get("message") or "")[:300]
            elif child.tag == "skipped":
                kind = child.get("type") or ""
                outcome = "xfailed" if "xfail" in kind else "skipped"
        classname = f".{case.get('classname', '')}."
        group = (
            "ha"
            if ".ha." in classname
            else "engine"
            if ".engine." in classname
            else "repo"
        )
        name = re.match(r"([^\[]+)(?:\[(.*)\])?$", case.get("name", ""))
        tests.append(
            {
                "file": classname.strip(".").split(".")[-1],
                "group": group,
                "name": name.group(1),
                "params": name.group(2) or "",
                "outcome": outcome,
                "message": message,
            }
        )
    return summary, tests


def run_hassfest() -> dict:
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{ROOT}:/github/workspace",
            "ghcr.io/home-assistant/hassfest",
        ],
        capture_output=True,
        text=True,
    )
    out = proc.stdout + proc.stderr
    invalid = re.search(r"Invalid integrations: (\d+)", out)
    return {
        "invalid": int(invalid.group(1)) if invalid else None,
        "errors": re.findall(r"\* \[ERROR\].*", out),
    }


def _why(name: str, mode: str, yaml_: list | None, engine: list) -> str:
    """The decision that explains a difference from the YAML package."""
    if yaml_ is None or yaml_ == engine:
        return ""
    if "bridge" in name:
        return "bridge lifts the surplus to the minimum (B2)"
    if mode == "comfort" and "ems 0" in name:
        return "Comfort above its SOC runs as Solar; EMS blocks only grid (B2)"
    if engine[1] < yaml_[1]:
        return "rounded down at the power limit (D16)"
    return "see the decision record"


def golden_row(name, mode, house, s, m, limit, expected) -> dict:
    out = step(mode, house, s={**s, "power_limit_w": limit}, m=m)
    phase, amps = result(out)
    charger_w = amps * 230 * phase  # efficiency is 1.0 in these cases
    solar_used_w = min(charger_w, max(-house, 0))
    yaml_ = None
    if yaml_available():
        yaml_ = list(
            yaml_result(
                str(mode),
                house,
                limit,
                car_aware=bool(s.get("car_aware")),
                soc=m.get("car_soc", 50),
                ems_control=bool(s.get("ems_control")),
                ems_signal_w=m.get("ems_signal_w"),
                solar_when_ems_blocks=bool(s.get("solar_when_ems_blocks")),
            )
        )
    return {
        "name": name,
        "mode": str(mode),
        "household_w": house,
        "settings": sorted(k for k, v in s.items() if v is True),
        "bridge_w": s.get("solar_bridge_w", 0),
        "soc": m.get("car_soc") if s.get("car_aware") or mode == "comfort" else None,
        "ems_signal_w": m.get("ems_signal_w"),
        "yaml": yaml_,
        "expected": list(expected),
        "engine": [phase, amps],
        "charger_w": round(charger_w),
        "solar_used_w": round(solar_used_w),
        "grid_import_w": round(charger_w - solar_used_w),
        # Meter after charging: positive = import, negative = export.
        "net_w": round(house + charger_w),
        "power_limit_w": limit,
        "reason": out.reason.value,
        "pass": (phase, amps) == tuple(expected),
        "why": _why(name, str(mode), yaml_, [phase, amps]),
    }


def golden_cases() -> dict:
    golden: dict = {"original": {}, "comfort": {}}
    for limit in (6000, 10000):
        table = tc.GOLDEN_6KW if limit == 6000 else {g[0]: g[5] for g in tc.GOLDEN}
        golden["original"][str(limit)] = [
            golden_row(n, mode, house, s, m, limit, table[n])
            for n, mode, house, s, m, _ in tc.GOLDEN
        ]
        golden["comfort"][str(limit)] = [
            golden_row(n, tc.M.COMFORT, house, s, m, limit, exp[limit])
            for n, house, s, m, exp in tc.COMFORT
        ]
    return golden


def decisions() -> list[dict]:
    rows = []
    for line in (ROOT / "docs" / "behaviour.md").read_text("utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and re.fullmatch(r"[DB]\d\d?", cells[0]):
            rows.append({"id": cells[0], "topic": cells[1], "decision": cells[2]})
    return rows


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    summary, tests = run_tests()
    hassfest = run_hassfest()
    requirements = (ROOT / "requirements-dev-windows.txt").read_text("utf-8")
    ha_version = re.search(r"homeassistant==([\d.]+)", requirements)
    data = {
        "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "summary_line": summary,
        "env": {
            "python": platform.python_version(),
            "homeassistant": ha_version.group(1) if ha_version else "?",
            "branch": git("branch", "--show-current"),
            "base_commit": git("rev-parse", "--short", "HEAD"),
            "dirty": bool(git("status", "--porcelain")),
        },
        "counts": dict(Counter(t["outcome"] for t in tests)),
        "group_counts": {
            g: len([t for t in tests if t["group"] == g])
            for g in ("engine", "ha", "repo")
        },
        "tests": tests,
        "golden": golden_cases(),
        "decisions": decisions(),
        "hassfest": hassfest,
    }
    (BUILD / "data.json").write_text(json.dumps(data, indent=1), "utf-8")
    print(summary, data["counts"], "hassfest invalid:", hassfest["invalid"])


if __name__ == "__main__":
    main()
