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


def assert_zoom_layout(snapshot: Any, target: float) -> dict[str, Any]:
    """Reject viewport overflow, iframe scaling, and detached tab menus."""
    if not isinstance(snapshot, dict):
        raise AssertionError(f"Missing zoom layout snapshot at {target}: {snapshot!r}")
    if snapshot.get("cssZoom"):
        raise AssertionError(f"CSS zoom remained active at {target}: {snapshot!r}")

    viewport = snapshot.get("viewport", {})
    overflow = viewport.get("overflow", {})
    if any(value > 2 for value in overflow.values() if isinstance(value, (int, float))):
        raise AssertionError(f"Zoom {target} overflowed the desktop viewport: {snapshot!r}")

    menu = snapshot.get("menu")
    if not isinstance(menu, dict):
        raise AssertionError(f"Zoom {target} had no measurable tab actions menu: {snapshot!r}")
    errors = menu.get("anchorError", {})
    if any(value > 3 for value in errors.values() if isinstance(value, (int, float))):
        raise AssertionError(f"Zoom {target} detached the tab actions menu: {snapshot!r}")
    if menu.get("insideViewport") is not True:
        raise AssertionError(f"Zoom {target} moved the tab actions menu offscreen: {snapshot!r}")

    frames = snapshot.get("frames", [])
    if not frames:
        raise AssertionError(f"Zoom {target} had no iframe viewport measurement: {snapshot!r}")
    mismatched = [
        frame for frame in frames
        if frame.get("insideViewport") is not True
        or (
            frame.get("viewportWidthError") is not None
            and frame["viewportWidthError"] > 4
        )
    ]
    if mismatched:
        raise AssertionError(f"Zoom {target} desynchronized iframe layouts: {mismatched!r}")
    return snapshot


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

    def wait_for_download_toast(self, filename: str) -> bool:
        deadline = time.monotonic() + 15
        last: Any = None
        while time.monotonic() < deadline:
            try:
                last = self.driver.execute(
                    "const text = document.body?.innerText || ''; "
                    "const expected = "
                    + json.dumps(f"{filename} was saved to Downloads.")
                    + "; "
                    "return { observed: text.includes('Download complete') && text.includes(expected), "
                    "bodyText: text.slice(-2000), "
                    "pending: window.__omnideckPendingDownload || null };"
                )
                if isinstance(last, dict) and last.get("observed") is True:
                    return True
            except WebDriverError as error:
                last = error
            time.sleep(0.25)
        raise AssertionError(
            f"Timed out waiting for the native download completion notification for "
            f"{filename}; last={last!r}"
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
        toast_observed = self.wait_for_download_toast(pack_filename(fixture_name))
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
                    "toastObserved": toast_observed,
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        return filename

    def artifact_download(self, artifact_filename: str) -> None:
        initial = self.select_hosted_window()
        wait_until(
            "the core application",
            self.timeout,
            lambda: self.driver.execute(
                "return Boolean(document.querySelector('[data-testid=\"sidebar-nav-artifacts\"]'));"
            ),
        )
        self.driver.click('[data-testid="sidebar-nav-artifacts"]')
        wait_until(
            "the Artifacts view",
            self.timeout,
            lambda: self.driver.execute(
                "return Boolean(document.querySelector('[data-testid=\"artifacts-hub\"]'));"
            ),
        )

        opened = wait_until(
            f"the {artifact_filename} artifact card",
            self.timeout,
            lambda: self.driver.execute(
                "const filename = " + json.dumps(artifact_filename) + "; "
                "const card = [...document.querySelectorAll('[data-testid=\"artifact-card\"]')]"
                ".find((candidate) => (candidate.innerText || '').includes(filename)); "
                "if (!card) return false; card.click(); return true;"
            ),
        )
        if opened is not True:
            raise AssertionError(f"Could not open artifact {artifact_filename}")
        wait_until(
            "the artifact preview download action",
            self.timeout,
            lambda: self.driver.execute(
                "return Boolean(document.querySelector('[data-testid=\"file-download\"]'));"
            ),
        )
        before = self.driver.execute("return location.href;")
        self.driver.click('[data-testid="file-download"]')
        toast_observed = self.wait_for_download_toast(artifact_filename)
        after = self.driver.execute("return location.href;")
        if before != after:
            raise AssertionError(
                f"Artifact download navigated the hosted application: {before!r} -> {after!r}"
            )
        self.evidence.joinpath("artifact-download.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "hostedUrl": initial.get("url"),
                    "urlBefore": before,
                    "urlAfter": after,
                    "expectedFilename": artifact_filename,
                    "toastObserved": toast_observed,
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    def zoom(
        self,
        native_input_signal_dir: Path | None = None,
    ) -> None:
        initial = self.select_hosted_window()
        self.driver.execute("""
document.body.tabIndex = -1;
document.body.focus();
return true;
""")
        baseline_width = self.driver.execute("return window.innerWidth;")
        if not isinstance(baseline_width, (int, float)) or baseline_width <= 0:
            raise AssertionError(f"Invalid native zoom baseline width: {baseline_width!r}")

        def measured_zoom() -> float | None:
            width = self.driver.execute("return window.innerWidth;")
            if not isinstance(width, (int, float)) or width <= 0:
                return None
            return round(float(baseline_width) / float(width), 2)

        def wait_for_zoom(description: str, predicate: Callable[[float], bool]) -> float:
            value = wait_until(
                description,
                self.timeout,
                lambda: (
                    current
                    if (current := measured_zoom()) is not None
                    and predicate(current)
                    else None
                ),
            )
            return float(value)

        def layout_snapshot(target: float) -> dict[str, Any]:
            def probe() -> dict[str, Any] | None:
                return self.driver.execute("""
const trigger = document.querySelector('[data-testid^="view-tab-actions-"]');
if (!trigger) return null;
let menu = document.querySelector('[data-testid^="view-tab-menu-"]');
if (!menu) {
  const triggerRect = trigger.getBoundingClientRect();
  window.__omnideckZoomMenuOpeningAnchor = {
    left: triggerRect.left,
    bottom: triggerRect.bottom,
  };
  trigger.click();
  return null;
}
const triggerRect = trigger.getBoundingClientRect();
const menuRect = menu.getBoundingClientRect();
const openingAnchor = window.__omnideckZoomMenuOpeningAnchor;
if (!openingAnchor) return null;
const margin = 8;
const expectedLeft = Math.max(
  margin,
  Math.min(openingAnchor.left, window.innerWidth - menuRect.width - margin),
);
const expectedTop = Math.max(
  margin,
  Math.min(openingAnchor.bottom, window.innerHeight - menuRect.height - margin),
);
const root = document.documentElement;
const body = document.body;
let frameProbe = document.querySelector('[data-zoom-layout-probe]');
if (!frameProbe) {
  frameProbe = document.createElement('iframe');
  frameProbe.dataset.zoomLayoutProbe = 'true';
  frameProbe.srcdoc = '<!doctype html><meta charset="utf-8"><style>html,body{margin:0}</style>';
  Object.assign(frameProbe.style, {
    position: 'fixed', left: '8px', top: '8px', width: '320px', height: '180px',
    border: '0', visibility: 'hidden', pointerEvents: 'none',
  });
  body.append(frameProbe);
}
const frames = [...document.querySelectorAll('iframe')]
  .filter((frame) => {
    const rect = frame.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  })
  .map((frame) => {
    const rect = frame.getBoundingClientRect();
    let contentViewportWidth = null;
    try { contentViewportWidth = frame.contentWindow?.innerWidth ?? null; } catch (_) {}
    return {
      left: rect.left,
      right: rect.right,
      width: rect.width,
      contentViewportWidth,
      viewportWidthError: contentViewportWidth === null
        ? null
        : Math.abs(contentViewportWidth - rect.width),
      insideViewport: rect.left >= -2 && rect.right <= window.innerWidth + 2,
    };
  });
return {
  cssZoom: root.style.zoom || '',
  viewport: {
    width: window.innerWidth,
    height: window.innerHeight,
    overflow: {
      documentX: Math.max(0, root.scrollWidth - root.clientWidth),
      documentY: Math.max(0, root.scrollHeight - root.clientHeight),
      bodyX: Math.max(0, body.scrollWidth - root.clientWidth),
      bodyY: Math.max(0, body.scrollHeight - root.clientHeight),
    },
  },
  menu: {
    openingTriggerLeft: openingAnchor.left,
    openingTriggerBottom: openingAnchor.bottom,
    triggerLeft: triggerRect.left,
    triggerBottom: triggerRect.bottom,
    left: menuRect.left,
    top: menuRect.top,
    right: menuRect.right,
    bottom: menuRect.bottom,
    expectedLeft,
    expectedTop,
    anchorError: {
      x: Math.abs(menuRect.left - expectedLeft),
      y: Math.abs(menuRect.top - expectedTop),
    },
    insideViewport: menuRect.left >= margin - 1
      && menuRect.top >= margin - 1
      && menuRect.right <= window.innerWidth - margin + 1
      && menuRect.bottom <= window.innerHeight - margin + 1,
  },
  frames,
};
""")

            snapshot = wait_until(
                f"stable tab menu layout at native zoom {target}",
                self.timeout,
                probe,
            )
            self.driver.execute("""
document.dispatchEvent(new KeyboardEvent('keydown', {
  key: 'Escape', bubbles: true, cancelable: true,
}));
return true;
""")
            wait_until(
                "tab actions menu to close after zoom layout capture",
                self.timeout,
                lambda: self.driver.execute(
                    "return !document.querySelector('[data-testid^=\"view-tab-menu-\"]');"
                ),
            )
            self.driver.execute(
                "delete window.__omnideckZoomMenuOpeningAnchor; return true;"
            )
            return assert_zoom_layout(snapshot, target)

        external_input_count = 0

        def external_shortcut(action: str) -> None:
            nonlocal external_input_count
            if native_input_signal_dir is None:
                raise AssertionError("External native input is unavailable")
            external_input_count += 1
            stem = f"zoom-input-{external_input_count:03d}-{action}"
            request = native_input_signal_dir / f"{stem}.request"
            acknowledgement = native_input_signal_dir / f"{stem}.ack"
            acknowledgement.unlink(missing_ok=True)
            request.write_text(action + "\n", encoding="utf-8")
            wait_until(
                f"VM hardware input acknowledgement for {action}",
                self.timeout,
                acknowledgement.is_file,
            )

        def keyboard_shortcut(key: str) -> None:
            if native_input_signal_dir is not None:
                action = "reset" if key == "0" else "in" if key == "=" else "out"
                external_shortcut(action)
            else:
                self.driver.send_keys("body", f"\ue009{key}\ue000")

        keyboard_shortcut("=")
        keyboard_zoom = wait_for_zoom(
            "one native zoom-in step",
            lambda current: current >= 1.05,
        )
        layouts = {"keyboardIn": layout_snapshot(keyboard_zoom)}
        keyboard_shortcut("0")
        wait_for_zoom("native zoom reset", lambda current: abs(current - 1) <= 0.03)
        keyboard_shortcut("-")
        keyboard_zoom_out = wait_for_zoom(
            "one native zoom-out step",
            lambda current: current <= 0.95,
        )
        layouts["keyboardOut"] = layout_snapshot(keyboard_zoom_out)
        keyboard_shortcut("0")
        wait_for_zoom("final native zoom reset", lambda current: abs(current - 1) <= 0.03)

        result = {
            "status": "passed",
            "hostedUrl": initial.get("url"),
            "keyboardZoom": keyboard_zoom,
            "keyboardZoomOut": keyboard_zoom_out,
            "testedZoomLevels": [keyboard_zoom, keyboard_zoom_out],
            "nativeWebviewZoomApplied": True,
            "cssZoomApplied": False,
            "primaryInput": (
                "vm-hardware-keyboard"
                if native_input_signal_dir is not None
                else "webdriver-keyboard"
            ),
            "layouts": layouts,
            "nativeInputSignalDir": (
                str(native_input_signal_dir) if native_input_signal_dir is not None else None
            ),
        }
        self.evidence.joinpath("zoom.json").write_text(
            json.dumps(result, indent=2) + "\n",
            encoding="utf-8",
        )

    def update_bridge(self, expected_version: str) -> None:
        initial = self.select_hosted_window()
        result = self.driver.execute_async("""
const done = arguments[arguments.length - 1];
const finish = (value) => done(JSON.stringify(value));
(async () => {
  const bridge = window.omnideckHost;
  if (!bridge) throw new Error('Desktop update bridge was not exposed');
  const events = [];
  const unsubscribe = bridge.onUpdate((value) => events.push(value));
  const checked = await bridge.checkForUpdate();
  await bridge.deferUpdate();
  const deferred = await bridge.currentUpdate();
  await bridge.skipUpdate();
  const skipped = await bridge.currentUpdate();
  unsubscribe();
  finish({
    ok: true,
    frozen: Object.isFrozen(bridge),
    keys: Object.keys(bridge).sort(),
    checked,
    deferred,
    skipped,
    events,
  });
})().catch((error) => finish({
  ok: false,
  error: error?.message || String(error),
  code: error?.code || null,
  detail: error && typeof error === 'object' ? JSON.stringify(error) : null,
}));
""")
        if isinstance(result, str):
            result = json.loads(result)
        expected_keys = [
            "checkForUpdate", "currentUpdate", "deferUpdate", "installUpdate", "onUpdate",
            "openExternal", "skipUpdate",
        ]
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise AssertionError(f"Native update bridge failed: {result!r}")
        if result.get("frozen") is not True or result.get("keys") != expected_keys:
            raise AssertionError(f"Native update bridge exposed an unexpected API: {result!r}")
        if result.get("checked") != {"version": expected_version, "deferred": False}:
            raise AssertionError(f"Native update discovery was unexpected: {result!r}")
        if result.get("deferred") != {"version": expected_version, "deferred": True}:
            raise AssertionError(f"Native update deferral was not persisted: {result!r}")
        if result.get("skipped") is not None:
            raise AssertionError(f"Skipped native update remained available: {result!r}")
        events = result.get("events")
        if not isinstance(events, list) or not events or events[-1] is not None:
            raise AssertionError(f"Native update events were not delivered: {result!r}")
        self.evidence.joinpath("update-bridge.json").write_text(
            json.dumps({"status": "passed", "hostedUrl": initial.get("url"), **result}, indent=2)
            + "\n",
            encoding="utf-8",
        )

    def external_links(
        self, expected_browser_process: str, skip_browser_process_check: bool
    ) -> None:
        initial = self.select_hosted_window()
        inserted = self.driver.execute("""
const sameOrigin = document.createElement('a');
sameOrigin.dataset.testid = 'desktop-same-origin-link';
sameOrigin.href = `${location.pathname}${location.search}#desktop-link-route`;
sameOrigin.textContent = 'Same-origin route';
const external = document.createElement('a');
external.dataset.testid = 'desktop-external-link';
external.href = 'https://example.com/omnideck-external-link-test';
external.textContent = 'External link';
const externalBlank = document.createElement('a');
externalBlank.dataset.testid = 'desktop-external-blank-link';
externalBlank.href = 'https://example.com/omnideck-external-blank-link-test';
externalBlank.target = '_blank';
externalBlank.textContent = 'External link in new window';
const probe = document.createElement('div');
probe.dataset.testid = 'desktop-link-probe';
Object.assign(probe.style, {
  position: 'fixed', inset: '8px 8px auto auto', zIndex: '2147483647',
  display: 'grid', gap: '8px', padding: '12px', background: 'white', color: 'black',
});
probe.append(sameOrigin, external, externalBlank);
document.body.append(probe);
return true;
""")
        if inserted is not True:
            raise AssertionError("Could not install the packaged link probes")

        self.driver.click('[data-testid="desktop-same-origin-link"]')
        same_origin = wait_until(
            "same-origin navigation to remain in the hosted webview",
            self.timeout,
            lambda: self.driver.execute(
                "return location.hash === '#desktop-link-route' ? location.href : '';"
            ),
        )

        def browser_pids() -> list[int]:
            completed = subprocess.run(
                ["pgrep", "-u", str(os.getuid()), "-x", expected_browser_process],
                check=False,
                capture_output=True,
                text=True,
            )
            return sorted(
                int(value) for value in completed.stdout.split() if value.isdigit()
            )

        before_pids = [] if skip_browser_process_check else browser_pids()
        self.driver.click('[data-testid="desktop-external-link"]')
        if skip_browser_process_check:
            time.sleep(2)
            opened_pids = []
        else:
            opened_pids = wait_until(
                f"the system browser process {expected_browser_process}",
                self.timeout,
                lambda: browser_pids() or None,
            )
        after_external = self.driver.execute("return location.href;")
        if after_external != same_origin:
            raise AssertionError(
                "External navigation replaced the hosted application: "
                f"{same_origin!r} -> {after_external!r}"
            )

        self.driver.click('[data-testid="desktop-external-blank-link"]')
        time.sleep(2)
        after_blank = self.driver.execute("return location.href;")
        if after_blank != same_origin:
            raise AssertionError(
                "Target-blank navigation replaced the hosted application: "
                f"{same_origin!r} -> {after_blank!r}"
            )

        self.evidence.joinpath("external-links.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "hostedUrl": initial.get("url"),
                    "sameOriginUrl": same_origin,
                    "externalUrl": "https://example.com/omnideck-external-link-test",
                    "externalBlankUrl": "https://example.com/omnideck-external-blank-link-test",
                    "hostedUrlAfterExternal": after_external,
                    "hostedUrlAfterExternalBlank": after_blank,
                    "browserProcess": expected_browser_process,
                    "browserProcessVerified": not skip_browser_process_check,
                    "browserPidsBefore": before_pids,
                    "browserPidsAfter": opened_pids,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

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
    parser.add_argument(
        "--operation",
        choices=(
            "download", "upload", "artifact-download", "zoom", "update-bridge",
            "external-links",
        ),
        required=True,
    )
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--fixture-name", required=True)
    parser.add_argument("--upload-path", default="")
    parser.add_argument("--artifact-filename", default="")
    parser.add_argument("--expected-update-version", default="0.1.5")
    parser.add_argument("--expected-browser-process", default="firefox")
    parser.add_argument("--skip-browser-process-check", action="store_true")
    parser.add_argument("--native-input-signal-dir", type=Path)
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
    if args.operation == "artifact-download" and not args.artifact_filename:
        raise SystemExit("--artifact-filename is required for artifact-download")
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
            elif args.operation == "upload":
                journey.upload(args.fixture_name, args.upload_path)
            elif args.operation == "artifact-download":
                journey.artifact_download(args.artifact_filename)
            elif args.operation == "zoom":
                journey.zoom(args.native_input_signal_dir)
            elif args.operation == "update-bridge":
                journey.update_bridge(args.expected_update_version)
            else:
                journey.external_links(
                    args.expected_browser_process, args.skip_browser_process_check
                )
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
