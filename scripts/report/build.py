"""Build docs/test-report.html and docs/test-report.md from build/report/data.json.

The HTML page is self-contained: style, script and data are inlined. The
Markdown file shows the same results on GitHub.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
VOLT = 230

MODE = {
    "off": "Off",
    "min_1p": "1-Phase Minimum",
    "min_3p": "3-Phases Minimum",
    "limited": "Limited",
    "fast": "Fast",
    "solar": "Solar",
    "comfort": "Comfort",
}
FILE_LABEL = {
    "test_controller": "Controller rules",
    "test_properties": "Properties (hypothesis)",
    "test_policy": "Mode policy",
    "test_setpoint": "Current and write filter",
    "test_limit": "Power limit",
    "test_energy": "Energy metering",
    "test_config_flow": "Setup and options flow",
    "test_controller_device": "Device, triggers and shadow mode",
    "test_charger_control": "Charger control",
    "test_translations": "Translations",
    "test_specs": "Options to specs",
    "test_manifest": "Repository metadata",
    "test_yaml_import": "Import from EV Load Balancer",
}
GROUP_LABEL = {"engine": "Engine", "ha": "Home Assistant", "repo": "Repository"}
SETS = (("original", "Original cases"), ("comfort", "Comfort cases"))


def html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # A "</" inside the data would end the inline script early.
    payload = payload.replace("</", "<\\/")
    head = (HERE / "head.html").read_text("utf-8")
    body = (HERE / "body.html").read_text("utf-8").replace("/*__DATA__*/null", payload)
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{head}\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


# --- Markdown -------------------------------------------------------------------------


def cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def kw(w: float) -> str:
    return f"{w / 1000:.2f} kW"


def setpoint(value: list | None) -> str:
    if not value:
        return "–"
    phases, amps = value
    if not amps:
        return "0 A, stopped"
    return f"{phases} × {amps:.1f} A ({amps * VOLT * phases / 1000:.2f} kW)"


def house(w: float) -> str:
    return f"export {-w / 1000:.1f} kW" if w < 0 else f"import {w / 1000:.1f} kW"


def settings(g: dict) -> str:
    parts = []
    if g["soc"] is not None:
        aware = "car_aware" in g["settings"]
        parts.append(f"SOC {g['soc']} %" + ("" if aware else ", car aware off"))
    if g["bridge_w"]:
        parts.append(f"bridge {g['bridge_w']} W")
    if "ems_control" in g["settings"]:
        signal = g["ems_signal_w"]
        parts.append(f"EMS {signal} W budget" if signal else "EMS 0 W")
    if "solar_when_ems_blocks" in g["settings"]:
        parts.append("solar when EMS blocks")
    return ", ".join(parts) or "defaults"


def meter(g: dict) -> str:
    net, limit = g["net_w"], g["power_limit_w"]
    text = (
        f"import {kw(net)}" if net > 0 else f"export {kw(-net)}" if net < 0 else "0 kW"
    )
    if net <= limit:
        return text
    if g["charger_w"] == 0:
        return f"{text}, house alone above the limit"
    return f"{text}, **{kw(net - limit)} above the limit**"


def golden_table(rows: list[dict]) -> list[str]:
    out = [
        "| Case | Mode | House | Settings | YAML package | Engine | Solar used | Grid import | Meter | Result |",
        "|---|---|---|---|---|---|--:|--:|---|---|",
    ]
    for g in rows:
        same = not g["yaml"] or g["engine"] == g["yaml"]
        engine = setpoint(g["engine"]) + (
            "" if same or not g["why"] else f"<br>*{g['why']}*"
        )
        out.append(
            "| "
            + " | ".join(
                cell(x)
                for x in (
                    g["name"],
                    MODE.get(g["mode"], g["mode"]),
                    house(g["household_w"]),
                    settings(g),
                    setpoint(g["yaml"]),
                    engine,
                    kw(g["solar_used_w"]) if g["solar_used_w"] else "–",
                    kw(g["grid_import_w"]) if g["grid_import_w"] else "–",
                    meter(g),
                    "✅ passed" if g["pass"] else "❌ failed",
                )
            )
            + " |"
        )
    return out


def markdown(data: dict) -> str:
    env, tests, hf = data["env"], data["tests"], data["hassfest"]
    counts = data["counts"]
    failed = counts.get("failed", 0) + counts.get("error", 0)
    golden = [g for s in data["golden"].values() for rows in s.values() for g in rows]
    same = sum(1 for g in golden if g["yaml"] and g["engine"] == g["yaml"])
    source = env["source"]
    results = (
        f"[{source['label']}]({source['url']})"
        if source.get("url")
        else source["label"]
    )
    gc = data["group_counts"]

    out = [
        "# Test report",
        "",
        "<!-- Generated by scripts/report/build.py. Do not edit. -->",
        "",
        f"Run {data['generated']} · branch `{env['branch']}` · commit `{env['base_commit']}`"
        + (" + uncommitted changes" if env["dirty"] else "")
        + f" · Home Assistant {env['homeassistant']} · Python {env['python']} · results: {results}",
        "",
        "An interactive version is in [test-report.html](test-report.html): download it and open it in a browser.",
        "",
        "## Summary",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| pytest (Linux) | {'✅' if failed == 0 else '❌'} {counts.get('passed', 0)} of {len(tests)} passed: "
        f"{gc['engine']} engine, {gc['ha']} Home Assistant, {gc['repo']} repository |",
        "| hassfest | "
        + (
            "✅ valid"
            if hf["invalid"] == 0
            else "❌ " + cell("; ".join(hf["errors"]) or "not run")
        )
        + " |",
        f"| Golden cases | {sum(g['pass'] for g in golden)} of {len(golden)} as specified; "
        f"{same} identical to the YAML package |",
        "",
        "## Golden cases",
        "",
        "The inputs of the EV Load Balancer YAML package's own test, at two power limits: 6 kW "
        "(a typical household on the capacity tariff) and the test's original 10 kW. A 16 A charger "
        "at 230 V, price 0.20 €/kWh under a 0.30 €/kWh maximum, no car data unless a SOC is shown.",
        "",
        "- **YAML package:** what the YAML package sets for the same inputs.",
        "- **Engine:** what this integration sets. A note explains a difference.",
        "- **Solar used / Grid import:** how the charger power splits.",
        "- **Meter:** house plus charger at the grid connection, checked against the power limit.",
        "",
        "The engine rounds to the nearest 0.1 A when there is headroom and rounds down when rounding "
        "up would exceed the power limit (D16).",
        "",
    ]
    for key, title in SETS:
        for limit, rows in data["golden"][key].items():
            out += [f"### {title} at a {int(limit) // 1000} kW limit", ""]
            out += golden_table(rows)
            out.append("")

    out += ["## All tests", ""]
    order = list(FILE_LABEL)
    files = sorted(
        {t["file"] for t in tests},
        key=lambda f: order.index(f) if f in order else len(order),
    )
    for f in files:
        rows = [t for t in tests if t["file"] == f]
        outcome = Counter(t["outcome"] for t in rows)
        status = ", ".join(f"{n} {o}" for o, n in sorted(outcome.items()))
        out += [
            "<details>",
            f"<summary><b>{FILE_LABEL.get(f, f)}</b> · {GROUP_LABEL[rows[0]['group']]} · "
            f"<code>{f}.py</code> · {status}</summary>",
            "",
            "| Test | Case | Result |",
            "|---|---|---|",
        ]
        for t in rows:
            result = "✅" if t["outcome"] == "passed" else t["outcome"]
            if t["outcome"] == "failed":
                result = f"❌ {cell(t['message'])}"
            name = t["name"].removeprefix("test_").replace("_", " ")
            out.append(f"| {cell(name)} | {cell(t['params']) or '–'} | {result} |")
        out += ["", "</details>", ""]
    return "\n".join(out)


def main() -> None:
    data = json.loads((ROOT / "build" / "report" / "data.json").read_text("utf-8"))
    for name, text in (
        ("test-report.html", html(data)),
        ("test-report.md", markdown(data)),
    ):
        out = ROOT / "docs" / name
        out.write_text(text, "utf-8", newline="\n")
        print(out, len(text))


if __name__ == "__main__":
    main()
