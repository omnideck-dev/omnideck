"""Validate the read-only sidecar proof without overlooking renderer crashes."""

import json
from pathlib import Path
import re
import sys


def verify(smoke_dir: Path, cli_version: str, cli_commit: str) -> None:
    proof = json.loads((smoke_dir / "smoke-proof.json").read_text(encoding="utf-8"))
    expected = {
        "cliVersion": cli_version,
        "cliCommit": cli_commit,
        "schemaVersion": 4,
        "operations": ["--version", "--json runtime status"],
        "mutation": False,
    }
    for key, value in expected.items():
        if type(proof.get(key)) is not type(value) or proof.get(key) != value:
            raise ValueError(f"Packaged smoke {key} mismatch: {proof!r}")
    stderr = (smoke_dir / "host.stderr.log").read_text(encoding="utf-8", errors="replace")
    # The proof is produced by the host/CLI, not the WebKit renderer. A renderer
    # may abort while both of those processes continue successfully.
    if re.search(r"EGL_BAD_PARAMETER|Aborting\.\.\.|segmentation fault|core dumped", stderr, re.I):
        raise ValueError(f"Packaged renderer failed despite sidecar proof:\n{stderr}")


if __name__ == "__main__":
    verify(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
