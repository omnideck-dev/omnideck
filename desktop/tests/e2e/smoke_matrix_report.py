#!/usr/bin/env python3

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree


parser = argparse.ArgumentParser()
parser.add_argument("--status-file", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--run-id", required=True)
parser.add_argument("--started-at", required=True)
arguments = parser.parse_args()

cells = []
with Path(arguments.status_file).open(encoding="utf-8") as stream:
    for raw_line in stream:
        line = raw_line.rstrip("\n")
        if not line:
            continue
        guest, package, status, evidence, detail = line.split("\t", 4)
        cells.append(
            {
                "guest": guest,
                "package": package,
                "status": status,
                "evidence": evidence,
                "detail": detail,
            }
        )

failed = [cell for cell in cells if cell["status"] != "passed"]
summary = {
    "schemaVersion": 1,
    "runId": arguments.run_id,
    "scope": "cross-distro-package-open-smoke",
    "status": "failed" if failed else "passed",
    "startedAt": arguments.started_at,
    "finishedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "cells": cells,
}
output = Path(arguments.output)
output.mkdir(parents=True, exist_ok=True)
(output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

suite = ElementTree.Element(
    "testsuite",
    {
        "name": "omnideck-desktop-cross-distro-smoke-matrix",
        "tests": str(len(cells)),
        "failures": str(len(failed)),
    },
)
for cell in cells:
    case = ElementTree.SubElement(
        suite,
        "testcase",
        {
            "classname": f"desktop-vm-smoke.{cell['guest']}",
            "name": cell["package"],
        },
    )
    if cell["status"] != "passed":
        failure = ElementTree.SubElement(case, "failure", {"message": cell["detail"]})
        failure.text = cell["evidence"]
ElementTree.indent(suite)
ElementTree.ElementTree(suite).write(output / "junit.xml", encoding="utf-8", xml_declaration=True)

raise SystemExit(1 if failed else 0)
