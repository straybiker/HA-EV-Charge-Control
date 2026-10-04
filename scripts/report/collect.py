"""Collect the test-report data.

Gets the results of the full test suite and hassfest, evaluates the golden
cases with the engine and, when the sibling EV_Loadbalancer checkout exists,
with the YAML package. Writes
build/report/data.json; build.py turns it into docs/test-report.html and .md.

    python scripts/report/collect.py        # run tests and hassfest in Docker
    python scripts/report/collect.py --ci   # use the CI run of the pushed HEAD
    python scripts/report/build.py
"""

from __future__ import annotations

import argparse
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
JUNIT = BUILD / "junit.xml"
IMAGE = "ev-charge-control-tests"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from yaml_golden import available as yaml_available  # noqa: E402
from yaml_golden import yaml_result  # noqa: E402

from tests.engine import test_controller as tc  # noqa: E402
from tests.engine.conftest import result, step  # noqa: E402


def run(*args: str) -> str:
    return subprocess.run(
        list(args), cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()


# --- results from Docker ----------------------------------------------------------


def docker_results() -> tuple[dict, dict]:
    """Run the suite and hassfest locally in Docker."""
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
    subprocess.run(
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
    hassfest = {
        "invalid": int(invalid.group(1)) if invalid else None,
        "errors": re.findall(r"\* \[ERROR\].*", out),
    }
    return hassfest, {"kind": "docker", "label": "local Docker run"}


# --- results from CI ------------------------------------------------------------------


def ci_results() -> tuple[dict, dict]:
    """Download the results of the finished CI run for the pushed HEAD."""
    sha = run("git", "rev-parse", "HEAD")
    if not run("git", "branch", "-r", "--contains", sha):
        sys.exit(f"HEAD {sha[:7]} is not pushed; push it and wait for CI.")
    runs = json.loads(
        run(
            "gh",
            "run",
            "list",
            "--workflow",
            "test.yml",
            "--commit",
            sha,
            "--json",
            "databaseId,status,url",
        )
        or "[]"
    )
    done = [r for r in runs if r["status"] == "completed"]
    if not done:
        sys.exit(f"The Tests run for {sha[:7]} has not finished yet.")
    JUNIT.unlink(missing_ok=True)
    run(
        "gh",
        "run",
        "download",
        str(done[0]["databaseId"]),
        "-n",
        "junit",
        "-D",
        str(BUILD),
    )
    if not JUNIT.is_file():
        sys.exit("The CI run has no junit artifact.")
    repo = run("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
    conclusion = run(
        "gh",
        "api",
        f"repos/{repo}/commits/{sha}/check-runs",
        "--jq",
        '.check_runs[] | select(.name == "hassfest") | .conclusion',
    )
    # Push and pull-request events each run hassfest: one line per run.
    conclusions = set(conclusion.split())
    ok = conclusions == {"success"}
    hassfest = {
        "invalid": 0 if ok else None,
        "errors": [] if ok else [f"hassfest: {', '.join(conclusions) or 'not run'}"],
    }
    return hassfest, {"kind": "ci", "label": "GitHub Actions", "url": done[0]["url"]}


# --- shared ---------------------------------------------------------------------------


def parse_junit() -> tuple[str, list[dict]]:
    tests = []
    for case in ET.parse(JUNIT).getroot().iter("testcase"):
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
    counts = Counter(t["outcome"] for t in tests)
    summary = ", ".join(f"{n} {outcome}" for outcome, n in sorted(counts.items()))
    return summary, tests


def _why(name: str, mode: str, yaml_: list | None, engine: list) -> str:
    """The decision that explains a difference from the YAML package."""
    if yaml_ is None or yaml_ == engine:
        return ""
    if "bridge" in name:
        return "bridge lifts the surplus to the minimum"
    if mode == "comfort" and "ems 0" in name:
        return "Comfort above its SOC runs as Solar; EMS blocks only grid"
    if engine[1] < yaml_[1]:
        return "rounded down at the power limit"
    return "see docs/behaviour.md"


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ci", action="store_true", help="use the CI run of the pushed HEAD"
    )
    args = parser.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    hassfest, source = ci_results() if args.ci else docker_results()
    summary, tests = parse_junit()
    requirements = (ROOT / "requirements-dev-windows.txt").read_text("utf-8")
    ha_version = re.search(r"homeassistant==([\d.]+)", requirements)
    data = {
        "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "summary_line": summary,
        "env": {
            "python": platform.python_version(),
            "homeassistant": ha_version.group(1) if ha_version else "?",
            "branch": run("git", "branch", "--show-current"),
            "base_commit": run("git", "rev-parse", "--short", "HEAD"),
            # Only changes that can alter a result; docs and the report scripts cannot.
            "dirty": bool(
                run(
                    "git",
                    "status",
                    "--porcelain",
                    "--",
                    "custom_components",
                    "tests",
                    "requirements-dev.txt",
                    "pyproject.toml",
                )
            ),
            "source": source,
        },
        "counts": dict(Counter(t["outcome"] for t in tests)),
        "group_counts": {
            g: len([t for t in tests if t["group"] == g])
            for g in ("engine", "ha", "repo")
        },
        "tests": tests,
        "golden": golden_cases(),
        "hassfest": hassfest,
    }
    (BUILD / "data.json").write_text(json.dumps(data, indent=1), "utf-8")
    print(summary, "| hassfest invalid:", hassfest["invalid"], "|", source["label"])


if __name__ == "__main__":
    main()
