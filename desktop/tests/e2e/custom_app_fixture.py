#!/usr/bin/env python3
"""Install the deterministic Custom App used by packaged Desktop VM journeys."""

from __future__ import annotations

import shutil
from pathlib import Path


APP_ROOT = Path("/home/omnideck/apps/desktop-smoke")
FILES = {
    "omnideck.json": """{
  "title": "Desktop Custom App Smoke",
  "description": "Packaged Tauri WebView compatibility fixture",
  "icon": "bi-window"
}
""",
    "app.py": """from custom_apps import action


@action
def echo(value: str):
    return {"value": value}
""",
    "web/index.html": """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Desktop Custom App Smoke</title>
  </head>
  <body>
    <h1>Desktop Custom App Smoke</h1>
    <button id="smoke-invoke" type="button">Invoke packaged action</button>
    <output id="smoke-result">Ready</output>
    <a id="smoke-route" href="#details">Internal custom route</a>
    <a id="smoke-external" href="https://example.com/omnideck-macos-link-test">External browser link</a>
    <a id="smoke-external-blank" href="https://example.com/omnideck-macos-blank-link-test" target="_blank">External browser link in new window</a>
    <script src="/api/custom-apps/sdk.js"></script>
    <script src="app.js"></script>
  </body>
</html>
""",
    "web/app.js": """document.querySelector('#smoke-invoke').addEventListener('click', async () => {
  const output = document.querySelector('#smoke-result');
  try {
    const result = await window.omnideck.invoke('echo', { value: 'tauri-webview' });
    output.textContent = `Action result: ${result.value}`;
  } catch (error) {
    output.textContent = `Action failed: ${error.message}`;
  }
});
""",
}


def main() -> None:
    shutil.rmtree(APP_ROOT, ignore_errors=True)
    for relative, content in FILES.items():
        target = APP_ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
