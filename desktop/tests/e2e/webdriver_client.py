#!/usr/bin/env python3
"""Drive the packaged Tauri setup surface through the native WebDriver."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from html.parser import HTMLParser
import re
import signal
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DRIVER_URL = "http://127.0.0.1:4444"
SETUP_SCRIPT = r"""
return (() => {
  const read = (selector) => {
    const element = document.querySelector(selector);
    if (!element) return null;
    return {
      text: element.textContent,
      hidden: Boolean(element.hidden),
      disabled: Boolean(element.disabled),
      tag: element.tagName.toLowerCase(),
    };
  };
  return {
    url: window.location.href,
    stage: document.documentElement.dataset.stage || '',
    title: read('#title'),
    detail: read('#detail'),
    eyebrow: read('#eyebrow'),
    activity: read('#activity'),
    primary: read('#primary'),
    secondary: read('#secondary'),
    progressContext: read('#progress-context'),
    progressStep: read('#progress-step'),
    progressValue: read('#progress-value'),
    actionError: read('#action-error'),
    doctorResult: read('#doctor-result'),
    diagnosticList: read('#diagnostic-list'),
    technicalOutput: read('#technical-output'),
    bodyText: document.body?.innerText || '',
    structure: [...document.querySelectorAll('main,section,header,button,details,[role="progressbar"]')]
      .map((element) => ({
        tag: element.tagName.toLowerCase(),
        id: element.id || '',
        role: element.getAttribute('role') || '',
      })),
  };
})();
"""

UPDATE_BRIDGE_SCRIPT = r"""
return (() => {
  const bridge = window.omnideckHost;
  return {
    frozen: Boolean(bridge && Object.isFrozen(bridge)),
    keys: bridge ? Object.keys(bridge).sort() : [],
  };
})();
"""

EXPECTED_UPDATE_BRIDGE = [
    "beginSetup",
    "onState",
    "openApp",
    "retry",
    "runAction",
]


class WebDriverError(RuntimeError):
    pass


class WebDriver:
    def __init__(self, base_url: str = DRIVER_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_id: str | None = None

    def request(
        self, method: str, path: str, payload: Any | None = None, timeout: float = 20
    ) -> Any:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except HTTPError as error:
            raw = error.read()
            raise WebDriverError(
                f"WebDriver {method} {path} failed with HTTP {error.code}: "
                f"{raw.decode('utf-8', errors='replace')}"
            ) from error
        except (URLError, TimeoutError, ConnectionError) as error:
            raise WebDriverError(f"WebDriver {method} {path} failed: {error}") from error
        if not raw:
            return None
        decoded = json.loads(raw)
        value = decoded.get("value", decoded)
        if isinstance(value, dict) and value.get("error"):
            raise WebDriverError(
                f"WebDriver {method} {path} returned {value['error']}: "
                f"{value.get('message', '')}"
            )
        return value

    def wait_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self.request("GET", "/status")
                return
            except (WebDriverError, json.JSONDecodeError) as error:
                last_error = error
                time.sleep(0.25)
        raise WebDriverError(f"tauri-driver was not ready within {timeout:.0f}s: {last_error}")

    def new_session(self, application: str) -> None:
        value = self.request(
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "browserName": "wry",
                        "tauri:options": {"application": application},
                    }
                }
            },
            timeout=180,
        )
        if not isinstance(value, dict):
            raise WebDriverError(f"Unexpected session response: {value!r}")
        self.session_id = value.get("sessionId")
        if not self.session_id:
            # Some native drivers return the identifier outside value. The
            # proxy normalizes it into capabilities under this private key.
            self.session_id = value.get("tauri:sessionId")
        if not self.session_id:
            raise WebDriverError(f"Session response had no identifier: {value!r}")

    def command(self, method: str, suffix: str, payload: Any | None = None) -> Any:
        if not self.session_id:
            raise WebDriverError("No active WebDriver session")
        return self.request(method, f"/session/{self.session_id}{suffix}", payload)

    def execute(self, script: str) -> Any:
        return self.command("POST", "/execute/sync", {"script": script, "args": []})

    def click(self, selector: str) -> None:
        element = self.command(
            "POST", "/element", {"using": "css selector", "value": selector}
        )
        if not isinstance(element, dict):
            raise WebDriverError(f"Unexpected element response for {selector}: {element!r}")
        element_id = element.get("element-6066-11e4-a52e-4f735466cecf")
        if not element_id:
            raise WebDriverError(f"Element response had no identifier for {selector}: {element!r}")
        self.command("POST", f"/element/{element_id}/click", {})

    def screenshot(self, destination: Path) -> None:
        encoded = self.command("GET", "/screenshot")
        if not isinstance(encoded, str):
            raise WebDriverError(f"Unexpected screenshot response: {encoded!r}")
        destination.write_bytes(base64.b64decode(encoded))

    def handles(self) -> list[str]:
        value = self.command("GET", "/window/handles")
        if not isinstance(value, list):
            raise WebDriverError(f"Unexpected window handles response: {value!r}")
        return value

    def switch_window(self, handle: str) -> None:
        self.command("POST", "/window", {"handle": handle})

    def close(self) -> None:
        if self.session_id:
            try:
                self.request("DELETE", f"/session/{self.session_id}")
            except Exception as error:  # Cleanup must preserve the test failure.
                print(f"WebDriver session cleanup warning: {error}", file=sys.stderr)
            finally:
                self.session_id = None


def text_of(state: dict[str, Any], key: str) -> str:
    value = state.get(key)
    if not isinstance(value, dict):
        return ""
    text = value.get("text")
    return text if isinstance(text, str) else ""


def is_visible(state: dict[str, Any], key: str) -> bool:
    value = state.get(key)
    return isinstance(value, dict) and not value.get("hidden", False)


def slug(value: str) -> str:
    candidate = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return candidate[:50] or "state"


class Journey:
    def __init__(
        self,
        driver: WebDriver,
        parity: dict[str, Any],
        evidence: Path,
        markers: Path,
        timeout: float,
        webdriver_screenshots: bool,
        initial_copy: tuple[str, str],
        hosted_action: str = "",
    ) -> None:
        self.driver = driver
        self.parity = parity
        self.evidence = evidence
        self.markers = markers
        self.timeout = timeout
        self.webdriver_screenshots = webdriver_screenshots
        self.states: list[dict[str, Any]] = []
        self.seen: set[tuple[str, str, str, str]] = set()
        self.screenshot_count = 0
        self.hosted_action = hosted_action
        self.setup_handle: str | None = None
        self.copy_pairs = {
            (entry["title"], entry["detail"]): name
            for name, entry in parity["setupCopy"].items()
        }
        self.copy_pairs[initial_copy] = "starting"
        self.failure_pairs = {
            (entry["title"], entry["detail"]): name
            for name, entry in parity["failureCopy"].items()
        }
        self.retryable_failures = {
            f"failure:{name}"
            for name, entry in parity["failureCopy"].items()
            if entry.get("canRetry") is True
        }
        self.phase_activities = {
            entry["activity"] for entry in parity["setupPhases"]
        }

    def live_state(self) -> dict[str, Any]:
        handles = self.driver.handles()
        ordered_handles = list(handles)
        if self.setup_handle in ordered_handles:
            ordered_handles.remove(self.setup_handle)
            ordered_handles.insert(0, self.setup_handle)

        observed: list[dict[str, Any]] = []
        last_error: Exception | None = None
        for handle in ordered_handles:
            try:
                self.driver.switch_window(handle)
                value = self.driver.execute(SETUP_SCRIPT)
            except WebDriverError as error:
                last_error = error
                continue
            if not isinstance(value, dict):
                observed.append({"handle": handle, "value": repr(value)})
                continue
            observed.append(
                {
                    "handle": handle,
                    "url": value.get("url", ""),
                    "title": text_of(value, "title"),
                    "detail": text_of(value, "detail"),
                }
            )
            # The packaged app deliberately keeps a hidden companion WebView
            # alive for hosted content. Windows WebDriver can select that
            # window first, so identify the setup surface by its copy-bearing
            # DOM rather than relying on handle ordering.
            if text_of(value, "title") and text_of(value, "detail"):
                self.setup_handle = handle
                return value

        self.setup_handle = None
        raise WebDriverError(
            "No copy-bearing setup window was available; "
            f"observed={observed!r}; last_error={last_error}"
        )

    def validate_copy(self, state: dict[str, Any]) -> str:
        title = text_of(state, "title")
        detail = text_of(state, "detail")
        pair = (title, detail)
        stage = state.get("stage")
        if stage == "error":
            name = self.failure_pairs.get(pair)
            if not name:
                raise AssertionError(f"Uncontracted visible error copy: {pair!r}")
            return f"failure:{name}"
        name = self.copy_pairs.get(pair)
        if not name:
            raise AssertionError(f"Uncontracted visible setup copy: {pair!r}")
        return f"setup:{name}"

    def record(self, state: dict[str, Any], force: bool = False) -> str:
        contract = self.validate_copy(state)
        key = (
            str(state.get("stage", "")),
            text_of(state, "title"),
            text_of(state, "detail"),
            text_of(state, "activity")
            if text_of(state, "activity") in self.phase_activities
            else "",
        )
        if key in self.seen and not force:
            return contract
        snapshot = dict(state)
        snapshot["contract"] = contract
        snapshot["observedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.states.append(snapshot)
        self.screenshot_count += 1
        filename = f"{self.screenshot_count:02d}-{slug(contract)}.png"
        (self.evidence / "states.json").write_text(
            json.dumps(self.states, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if self.webdriver_screenshots:
            self.driver.screenshot(self.evidence / filename)
        self.seen.add(key)
        marker_name = f"state-{self.screenshot_count:02d}-{slug(contract)}"
        self.markers.joinpath(marker_name).write_text(contract + "\n", encoding="utf-8")
        print(
            f"STATE {contract} stage={state.get('stage')} "
            f"title={text_of(state, 'title')!r}",
            flush=True,
        )
        if contract in {"setup:permission", "setup:permissionWindows", "setup:permissionMacos"}:
            (self.markers / "permission-visible").touch()
        return contract

    def wait_for(self, predicate: Any, label: str, timeout: float | None = None) -> dict[str, Any]:
        deadline = time.monotonic() + (timeout or self.timeout)
        last_state: dict[str, Any] | None = None
        last_error: Exception | None = None
        reported_error = ""
        while time.monotonic() < deadline:
            try:
                last_state = self.live_state()
                self.record(last_state)
                if predicate(last_state):
                    return last_state
                last_error = None
            except (WebDriverError, AssertionError) as error:
                last_error = error
                rendered = f"{type(error).__name__}: {error}"
                self.evidence.joinpath("poll-error.txt").write_text(
                    rendered + "\n", encoding="utf-8"
                )
                if rendered != reported_error:
                    reported_error = rendered
                    print(f"POLL {rendered}", file=sys.stderr, flush=True)
            time.sleep(0.35)
        if last_error:
            raise AssertionError(f"Timed out waiting for {label}: {last_error}") from last_error
        raise AssertionError(f"Timed out waiting for {label}; last state: {last_state!r}")

    def assert_structure(self, state: dict[str, Any]) -> None:
        structure = state.get("structure")
        if not isinstance(structure, list):
            raise AssertionError("Live setup page did not expose its DOM structure")
        ids = {entry.get("id") for entry in structure if isinstance(entry, dict)}
        expected = {"primary", "secondary", "doctor-panel"}
        missing = sorted(expected - ids)
        if missing:
            raise AssertionError(f"Live setup DOM is missing contract nodes: {missing}")
        if not any(
            isinstance(entry, dict) and entry.get("role") == "progressbar"
            for entry in structure
        ):
            raise AssertionError("Live setup DOM is missing its progressbar")

    def welcome(self) -> dict[str, Any]:
        state = self.wait_for(lambda value: value.get("stage") == "welcome", "Welcome")
        self.assert_structure(state)
        if text_of(state, "primary") != "Set up omnideck" or not is_visible(state, "primary"):
            raise AssertionError(f"Welcome primary action changed: {state.get('primary')!r}")
        if is_visible(state, "secondary"):
            raise AssertionError("Welcome unexpectedly exposed a secondary action")
        return state

    def finish_setup(self, fixture_text: str, hosted_selector: str) -> str:
        retry_count = 0
        while True:
            final = self.wait_for(
                lambda value: value.get("stage") in {"ready", "error"},
                "Ready or a recovery result",
            )
            contract = self.validate_copy(final)
            if final.get("stage") == "error":
                if contract == "failure:restart":
                    if text_of(final, "primary") != "Restart now":
                        raise AssertionError("Restart-now wording changed")
                    if text_of(final, "secondary") != "Restart later":
                        raise AssertionError("Restart-later wording changed")
                    self.markers.joinpath("restart-required").touch()
                    self.driver.click("#secondary")
                    return "restart-required"
                if (contract in self.retryable_failures and retry_count < 2
                        and text_of(final, "primary") == "Try again"):
                    retry_count += 1
                    print(f"RETRY {contract} attempt={retry_count}", flush=True)
                    self.driver.click("#primary")
                    self.wait_for(
                        lambda value: value.get("stage") != "error",
                        f"{contract} retry to start",
                        timeout=60,
                    )
                    continue
                raise AssertionError(f"Setup ended in {contract}: {final!r}")
            if text_of(final, "primary") != "Open omnideck":
                raise AssertionError("Ready primary action wording changed")
            self.driver.click("#primary")
            self.wait_for_hosted(fixture_text, hosted_selector)
            return "opened"

    def run_first_setup(
        self, stop_after: str, fixture_text: str, hosted_selector: str
    ) -> str:
        self.welcome()
        if stop_after == "welcome":
            return "welcome"
        self.driver.click("#primary")
        return self.finish_setup(fixture_text, hosted_selector)

    def run_continuation(
        self, expected_contract: str, fixture_text: str, hosted_selector: str
    ) -> str:
        self.wait_for(
            lambda value: self.validate_copy(value) == expected_contract,
            expected_contract,
        )
        if expected_contract == "setup:updating":
            self.assert_update_bridge()
        return self.finish_setup(fixture_text, hosted_selector)

    def assert_update_bridge(self) -> None:
        """Verify the update state reached the packaged UI through its bridge."""
        value = self.driver.execute(UPDATE_BRIDGE_SCRIPT)
        if not isinstance(value, dict):
            raise AssertionError(f"Unexpected desktop bridge state: {value!r}")
        if value.get("keys") != EXPECTED_UPDATE_BRIDGE:
            raise AssertionError(
                f"Unexpected desktop bridge API: {value.get('keys')!r}"
            )
        if value.get("frozen") is not True:
            raise AssertionError("Desktop bridge must be immutable")
        self.evidence.joinpath("update-bridge.json").write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )
        self.markers.joinpath("update-bridge").write_text(
            "setup:updating\n", encoding="utf-8"
        )

    def run_doctor(self, fixture_text: str, hosted_selector: str) -> str:
        state = self.wait_for(lambda value: value.get("stage") == "error", "diagnostics")
        contract = self.validate_copy(state)
        if not is_visible(state, "primary") or text_of(state, "primary") != "Try again":
            raise AssertionError(f"Recoverable diagnostics lost Try again: {state!r}")
        print(f"RECOVERY {contract}", flush=True)
        self.driver.click("#primary")
        return self.finish_setup(fixture_text, hosted_selector)

    def wait_for_hosted(self, fixture_text: str, hosted_selector: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        observed: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            for handle in self.driver.handles():
                try:
                    self.driver.switch_window(handle)
                    value = self.driver.execute(
                        "return {url: location.href, bodyText: document.body?.innerText || '', "
                        "buttonTexts: [...document.querySelectorAll('button')].map((button) => button.textContent.trim()), "
                        f"selectorFound: Boolean(document.querySelector({json.dumps(hosted_selector)}))}};"
                    )
                    if isinstance(value, dict):
                        observed.append(value)
                        text_matches = not fixture_text or fixture_text in value.get("bodyText", "")
                        selector_matches = not hosted_selector or value.get("selectorFound") is True
                        action_matches = not self.hosted_action or self.hosted_action in value.get("buttonTexts", [])
                        if (value.get("url", "").startswith("http://127.0.0.1:")
                                and text_matches and selector_matches and action_matches):
                            if self.webdriver_screenshots:
                                self.driver.screenshot(self.evidence / "hosted-app.png")
                            self.evidence.joinpath("hosted.json").write_text(
                                json.dumps(value, indent=2) + "\n", encoding="utf-8"
                            )
                            self.markers.joinpath("hosted-app").touch()
                            print(f"HOSTED {value['url']}", flush=True)
                            return value
                except WebDriverError:
                    continue
            time.sleep(0.5)
        raise AssertionError(f"Hosted application did not open: {observed[-10:]!r}")


class InitialCopyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.active: str | None = None
        self.values = {"title": "", "detail": ""}

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = dict(attrs).get("id")
        self.active = element_id if element_id in self.values else None

    def handle_endtag(self, _tag: str) -> None:
        self.active = None

    def handle_data(self, data: str) -> None:
        if self.active:
            self.values[self.active] += data


def load_contract(
    canonical_path: Path, mockup_path: Path, mockup_html: Path
) -> tuple[dict[str, Any], tuple[str, str]]:
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    mockup = json.loads(mockup_path.read_text(encoding="utf-8"))
    if canonical != mockup:
        raise AssertionError("Canonical setup parity no longer exactly matches the frozen UX mockup")
    parser = InitialCopyParser()
    parser.feed(mockup_html.read_text(encoding="utf-8"))
    initial_copy = (parser.values["title"].strip(), parser.values["detail"].strip())
    if not all(initial_copy):
        raise AssertionError("Frozen UX mockup has no initial title/detail copy")
    return canonical, initial_copy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--application", required=True)
    parser.add_argument("--tauri-driver")
    parser.add_argument("--driver-url", default=DRIVER_URL)
    parser.add_argument("--external-driver", action="store_true")
    parser.add_argument("--parity", required=True, type=Path)
    parser.add_argument("--mockup-parity", required=True, type=Path)
    parser.add_argument("--mockup-html", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--markers", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--driver-timeout", type=float, default=30)
    parser.add_argument("--stop-after", choices=("welcome", "open"), default="open")
    parser.add_argument(
        "--scenario", choices=("first-run", "returning", "resume", "update", "doctor"), default="first-run"
    )
    parser.add_argument("--fixture-text", default="Welcome to Omnideck")
    parser.add_argument(
        "--hosted-selector",
        default='[data-testid="desktop-layout"], [role="dialog"][aria-labelledby="wizard-step-title"]',
    )
    parser.add_argument("--hosted-action", default="Get Started")
    parser.add_argument("--webdriver-screenshots", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    args.markers.mkdir(parents=True, exist_ok=True)
    parity, initial_copy = load_contract(args.parity, args.mockup_parity, args.mockup_html)
    driver_log = args.evidence / "tauri-driver.log"
    if not args.external_driver and not args.tauri_driver:
        raise SystemExit("--tauri-driver is required unless --external-driver is used")
    driver = WebDriver(args.driver_url)
    process: subprocess.Popen[bytes] | None = None
    status = "failed"
    result = "not-started"
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
            driver.new_session(args.application)
            args.evidence.joinpath("webdriver-session.txt").write_text(
                f"{driver.session_id}\n", encoding="utf-8"
            )
            journey = Journey(
                driver,
                parity,
                args.evidence,
                args.markers,
                args.timeout,
                args.webdriver_screenshots,
                initial_copy,
                args.hosted_action,
            )
            if args.scenario == "first-run":
                result = journey.run_first_setup(
                    args.stop_after, args.fixture_text, args.hosted_selector
                )
            elif args.scenario == "returning":
                journey.wait_for_hosted(args.fixture_text, args.hosted_selector)
                result = "opened"
            elif args.scenario == "resume":
                result = journey.run_continuation(
                    "setup:resuming", args.fixture_text, args.hosted_selector
                )
            elif args.scenario == "update":
                result = journey.run_continuation(
                    "setup:updating", args.fixture_text, args.hosted_selector
                )
            else:
                result = journey.run_doctor(args.fixture_text, args.hosted_selector)
            status = "passed"
        return 0
    except Exception as error:
        args.evidence.joinpath("failure.txt").write_text(f"{type(error).__name__}: {error}\n", encoding="utf-8")
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
        args.evidence.joinpath("journey-summary.json").write_text(
            json.dumps(
                {
                    "status": status,
                    "result": result,
                    "startedAt": started_at,
                    "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    raise SystemExit(main())
