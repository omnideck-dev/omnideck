#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--status-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    lanes = []
    if args.status_file.is_file():
        for line in args.status_file.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            name, status, requirement, evidence, detail = line.split("\t", 4)
            lanes.append(
                {
                    "name": name,
                    "status": status,
                    "requirement": requirement,
                    "evidence": evidence,
                    "detail": detail,
                }
            )

    required = [lane for lane in lanes if lane["requirement"] == "required"]
    passed = bool(required) and all(lane["status"] == "passed" for lane in required)
    summary = {
        "schemaVersion": 1,
        "runId": args.run_id,
        "release": args.release,
        "status": "passed" if passed else "failed",
        "startedAt": args.started_at,
        "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "lanes": lanes,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    (args.output / "summary.json").write_text(rendered, encoding="utf-8")
    (args.output / "run.json").write_text(rendered, encoding="utf-8")

    suite = ET.Element(
        "testsuite",
        {
            "name": "omnideck-desktop-published-release",
            "tests": str(len(lanes)),
            "failures": str(sum(lane["status"] == "failed" for lane in lanes)),
            "skipped": str(sum(lane["status"] in {"blocked", "not-run", "dispatched"} for lane in lanes)),
        },
    )
    for lane in lanes:
        case = ET.SubElement(suite, "testcase", {"classname": "desktop-release", "name": lane["name"]})
        if lane["status"] == "failed":
            ET.SubElement(case, "failure", {"message": lane["detail"]})
        elif lane["status"] != "passed":
            ET.SubElement(case, "skipped", {"message": f"{lane['status']}: {lane['detail']}"})
    tree = ET.ElementTree(suite)
    ET.indent(tree, space="  ")
    tree.write(args.output / "junit.xml", encoding="utf-8", xml_declaration=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
