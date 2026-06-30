"""Shared helpers for the artifacts e2e tests.

Artifacts are produced through the real pipeline (the fake provider drives
write_file + send_file), never seeded, so the tests exercise the feature end
to end.
"""

from __future__ import annotations

from playwright.sync_api import Page

from tests.e2e._helpers import container_exec
from tests.e2e._protocol import send_file, write_file
from tests.e2e.pages import ChatView

VC_HOME = "/home/computron"


def produce(page: Page, *files: tuple[str, str]) -> None:
    """Send each (path, content) file via a single agent turn through send_file.

    Leaves the producing conversation active (no reload afterwards).
    """
    directives = ""
    for path, content in files:
        directives += write_file(path, content) + send_file(path)
    ChatView(page).goto().new_conversation().send(directives).wait_streaming()


def delete_file(filename: str) -> None:
    """Remove a produced file from the VC home, out of band."""
    container_exec(
        "import pathlib\n"
        f"p = pathlib.Path('{VC_HOME}/{filename}')\n"
        "if p.exists(): p.unlink()\n"
    )


def file_exists(filename: str) -> bool:
    out = container_exec(
        f"import pathlib; print(pathlib.Path('{VC_HOME}/{filename}').exists())"
    )
    return out == "True"


def purge(page: Page, *filenames: str) -> None:
    """Remove the named artifacts from the index (and disk) via the real API."""
    resp = page.request.get("/api/artifacts")
    for a in resp.json().get("artifacts", []):
        if a["filename"] in filenames:
            page.request.delete(
                f"/api/artifacts/{a['id']}?delete_file=true",
                fail_on_status_code=False,
            )
