#!/usr/bin/env python3
"""Exercise hosted-app operations that must cross the native webview boundary."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import Any, Callable

from webdriver_client import DRIVER_URL, WebDriver, WebDriverError


def pack_filename(name: str) -> str:
    """Mirror the server's public download filename contract."""
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-")
    stem = stem[:64].strip("-") or "pack"
    return f"{stem}.agent.omnideck.json"


def is_imported_profile_name(candidate: Any, source_name: str) -> bool:
    return isinstance(candidate, str) and (
        candidate == source_name or candidate.startswith(f"{source_name} (imported")
    )


def wait_until(description: str, timeout: float, probe: Callable[[], Any]) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = probe()
            if last:
                return last
        except WebDriverError as error:
            last = error
        time.sleep(0.25)
    raise AssertionError(f"Timed out waiting for {description}; last={last!r}")


class HostBoundaryJourney:
    def __init__(self, driver: WebDriver, evidence: Path, timeout: float) -> None:
        self.driver = driver
        self.evidence = evidence
        self.timeout = timeout

    def select_hosted_window(self) -> dict[str, Any]:
        observed: list[dict[str, Any]] = []

        def probe() -> dict[str, Any] | None:
            for handle in self.driver.handles():
                try:
                    self.driver.switch_window(handle)
                    state = self.driver.execute(
                        "return {url: location.href, ready: document.readyState, "
                        "bodyText: document.body?.innerText || ''};"
                    )
                except WebDriverError:
                    continue
                if isinstance(state, dict):
                    observed.append(state)
                    if state.get("url", "").startswith("http://127.0.0.1:"):
                        return state
            return None

        selected = wait_until("the hosted application window", self.timeout, probe)
        self.evidence.joinpath("hosted-window.json").write_text(
            json.dumps(selected, indent=2) + "\n", encoding="utf-8"
        )
        return selected

    def api(self, method: str, path: str, body: Any | None = None) -> dict[str, Any]:
        script = """
const done = arguments[arguments.length - 1];
const method = %s;
const body = %s;
const options = {method, headers: {Accept: 'application/json'}};
if (body !== null) {
  options.headers['Content-Type'] = 'application/json';
  options.body = JSON.stringify(body);
}
fetch(%s, options).then(async (response) => {
  const text = await response.text();
  let value = null;
  try { value = text ? JSON.parse(text) : null; } catch (_) { value = text; }
  done({ok: response.ok, status: response.status, body: value});
}).catch((error) => done({ok: false, status: 0, error: String(error)}));
""" % (json.dumps(method), json.dumps(body), json.dumps(path))
        value = self.driver.execute_async(script)
        if not isinstance(value, dict):
            raise AssertionError(f"Unexpected {method} {path} result: {value!r}")
        return value

    def prepare_fixture(self, fixture_id: str, fixture_name: str) -> None:
        settings = self.api("GET", "/api/settings")
        if not settings.get("ok"):
            raise AssertionError(f"Could not read settings: {settings!r}")
        if not settings.get("body", {}).get("setup_complete"):
            updated = self.api("PUT", "/api/settings", {"setup_complete": True})
            if not updated.get("ok"):
                raise AssertionError(f"Could not finish core setup: {updated!r}")

        existing = self.api("GET", f"/api/profiles/{fixture_id}")
        if existing.get("status") == 200:
            removed = self.api("DELETE", f"/api/profiles/{fixture_id}")
            if not removed.get("ok"):
                raise AssertionError(f"Could not remove stale fixture: {removed!r}")
        elif existing.get("status") != 404:
            raise AssertionError(f"Could not inspect fixture: {existing!r}")

        created = self.api(
            "POST",
            "/api/profiles",
            {
                "id": fixture_id,
                "name": fixture_name,
                "description": "Native desktop host-boundary fixture",
                "system_prompt": "Exercise native download and upload behavior.",
            },
        )
        if created.get("status") != 201:
            raise AssertionError(f"Could not create fixture profile: {created!r}")
        self.driver.execute("location.reload(); return true;")
        wait_until(
            "the core application after setup",
            self.timeout,
            lambda: self.driver.execute(
                "return Boolean(document.querySelector('[data-testid=\"sidebar-nav-agents\"]'));"
            ),
        )

    def open_agents(self) -> None:
        # Navigation items intentionally toggle back to Chat when the active
        # item is clicked again. Returning-user state can already restore the
        # Agents view, so avoid turning a correct starting state into Chat.
        if self.driver.execute(
            "return Boolean(document.querySelector('[data-testid=\"agents-list\"]'));"
        ):
            return
        self.driver.click('[data-testid="sidebar-nav-agents"]')
        wait_until(
            "the Agents view",
            self.timeout,
            lambda: self.driver.execute(
                "return Boolean(document.querySelector('[data-testid=\"agents-list\"]'));"
            ),
        )

    def download(self, fixture_id: str, fixture_name: str) -> str:
        initial = self.select_hosted_window()
        self.prepare_fixture(fixture_id, fixture_name)
        self.open_agents()
        before = self.driver.execute("return location.href;")
        clicked = self.driver.execute(
            "const marker = document.querySelector(" +
            json.dumps(f'[data-testid="profile-item-{fixture_id}"]') +
            "); const row = marker?.closest('tr'); "
            "const button = row?.querySelector('[data-testid=\"agent-export\"]'); "
            "if (!button) return false; button.click(); return true;"
        )
        if clicked is not True:
            raise AssertionError("The fixture profile had no export action")
        wait_until(
            "the export options",
            self.timeout,
            lambda: self.driver.execute(
                "return Boolean(document.querySelector('[data-testid=\"export-confirm\"]'));"
            ),
        )
        self.driver.click('[data-testid="export-confirm"]')
        wait_until(
            "the export options to close",
            self.timeout,
            lambda: self.driver.execute(
                "return !document.querySelector('[data-testid=\"export-profile-modal\"]');"
            ),
        )
        time.sleep(1)
        after = self.driver.execute("return location.href;")
        if before != after:
            raise AssertionError(
                f"Export navigated the hosted application instead of downloading: {before!r} -> {after!r}"
            )
        filename = pack_filename(fixture_name)
        self.evidence.joinpath("download.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "hostedUrl": initial.get("url"),
                    "urlBefore": before,
                    "urlAfter": after,
                    "expectedFilename": filename,
                    "fixtureId": fixture_id,
                    "fixtureName": fixture_name,
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        return filename

    def upload(self, fixture_name: str, upload_path: str) -> None:
        initial = self.select_hosted_window()
        wait_until(
            "the core application",
            self.timeout,
            lambda: self.driver.execute(
                "return Boolean(document.querySelector('[data-testid=\"sidebar-nav-agents\"]'));"
            ),
        )
        self.open_agents()
        before = self.api("GET", "/api/profiles?include_disabled=true")
        if not before.get("ok") or not isinstance(before.get("body"), list):
            raise AssertionError(f"Could not read profiles before import: {before!r}")
        before_ids = {profile.get("id") for profile in before["body"]}
        made_interactable = self.driver.execute(
            "const input = document.querySelector('[data-testid=\"agents-import-input\"]'); "
            "if (!input) return false; input.style.display = 'block'; "
            "input.style.position = 'fixed'; input.style.left = '8px'; input.style.bottom = '8px'; "
            "return true;"
        )
        if made_interactable is not True:
            raise AssertionError("Agents import file input was not present")
        self.driver.send_keys('[data-testid="agents-import-input"]', upload_path)

        def imported() -> dict[str, Any] | None:
            profiles = self.api("GET", "/api/profiles?include_disabled=true")
            if not profiles.get("ok") or not isinstance(profiles.get("body"), list):
                return None
            matches = [
                profile for profile in profiles["body"]
                if is_imported_profile_name(profile.get("name"), fixture_name)
                and profile.get("id") not in before_ids
            ]
            return {"profiles": profiles["body"], "matches": matches} if matches else None

        result = wait_until("the uploaded profile to be imported", self.timeout, imported)
        toast_observed = wait_until(
            "the successful import notification",
            10,
            lambda: self.driver.execute(
                "return (document.body?.innerText || '').includes('Imported 1 agent.');"
            ),
        )
        current_url = self.driver.execute("return location.href;")
        if current_url != initial.get("url"):
            raise AssertionError(f"Import changed the hosted application URL: {current_url!r}")
        self.evidence.joinpath("upload.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "hostedUrl": current_url,
                    "uploadPath": upload_path,
                    "fixtureName": fixture_name,
                    "importedIds": [profile["id"] for profile in result["matches"]],
                    "importedNames": [profile["name"] for profile in result["matches"]],
                    "toastObserved": toast_observed is True,
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--application", required=True)
    parser.add_argument("--operation", choices=("download", "upload"), required=True)
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--fixture-name", required=True)
    parser.add_argument("--upload-path", default="")
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--tauri-driver")
    parser.add_argument("--driver-url", default=DRIVER_URL)
    parser.add_argument("--external-driver", action="store_true")
    parser.add_argument("--driver-timeout", type=float, default=30)
    parser.add_argument("--timeout", type=float, default=180)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    if args.operation == "upload" and not args.upload_path:
        raise SystemExit("--upload-path is required for upload")
    if not args.external_driver and not args.tauri_driver:
        raise SystemExit("--tauri-driver is required unless --external-driver is used")
    driver = WebDriver(args.driver_url)
    process: subprocess.Popen[bytes] | None = None
    driver_log = args.evidence / "tauri-driver.log"
    status = "failed"
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with driver_log.open("wb") as log:
            if not args.external_driver:
                process = subprocess.Popen(
                    [args.tauri_driver],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            driver.wait_ready(args.driver_timeout)
            last_error: WebDriverError | None = None
            for attempt in range(1, 4):
                try:
                    driver.new_session(args.application)
                    last_error = None
                    break
                except WebDriverError as error:
                    last_error = error
                    print(f"SESSION RETRY attempt={attempt} error={error}", file=sys.stderr)
                    time.sleep(1)
            if last_error is not None:
                raise last_error
            journey = HostBoundaryJourney(driver, args.evidence, args.timeout)
            if args.operation == "download":
                journey.download(args.fixture_id, args.fixture_name)
            else:
                journey.upload(args.fixture_name, args.upload_path)
            status = "passed"
        return 0
    except Exception as error:
        args.evidence.joinpath("failure.txt").write_text(
            f"{type(error).__name__}: {error}\n", encoding="utf-8"
        )
        print(f"FAIL: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        driver.close()
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        args.evidence.joinpath("summary.json").write_text(
            json.dumps(
                {
                    "status": status,
                    "operation": args.operation,
                    "startedAt": started_at,
                    "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    raise SystemExit(main())
