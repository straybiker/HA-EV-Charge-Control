"""Build docs/test-report.html from build/report/data.json.

The page is self-contained: style, script and data are inlined.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]


def main() -> None:
    data = json.loads((ROOT / "build" / "report" / "data.json").read_text("utf-8"))
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # A "</" inside the data would end the inline script early.
    payload = payload.replace("</", "<\\/")
    head = (HERE / "head.html").read_text("utf-8")
    body = (HERE / "body.html").read_text("utf-8").replace("/*__DATA__*/null", payload)
    html = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{head}\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )
    out = ROOT / "docs" / "test-report.html"
    out.write_text(html, "utf-8")
    print(out, len(html))


if __name__ == "__main__":
    main()
