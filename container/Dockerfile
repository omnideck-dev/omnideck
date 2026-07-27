# syntax=docker/dockerfile:1

# ── UI builder stage ─────────────────────────────────────────────────────────
# Builds the React/Vite frontend into static assets. Node and the heavy
# dev-dependency tree live only in this stage — the runtime image ships no
# Node and no node_modules; just the built dist/ is copied across.
FROM docker.io/node:20-bookworm-slim AS ui-builder
WORKDIR /ui
COPY server/ui/package.json server/ui/package-lock.json ./
RUN npm ci
COPY server/ui/ ./
RUN npm run build

# ── Runtime stage ────────────────────────────────────────────────────────────
FROM docker.io/ubuntu:22.04

# ── BuildKit arch detection ──────────────────────────────────────────────────
# TARGETARCH is injected by BuildKit: amd64, arm64, arm/v7, etc.
ARG TARGETARCH
ARG OMNIDECK_VERSION=development

LABEL org.opencontainers.image.title="OmniDeck" \
      org.opencontainers.image.description="Private OmniDeck application runtime" \
      org.opencontainers.image.source="https://github.com/omnideck-dev/omnideck" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${OMNIDECK_VERSION}"

# ── Environment ───────────────────────────────────────────────────────────────
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    DISPLAY=:99 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

RUN ln -fs /usr/share/zoneinfo/Etc/UTC /etc/localtime && \
    echo "Etc/UTC" > /etc/timezone

# ── System packages ──────────────────────────────────────────────────────────
# Single apt layer — one update, one clean. Deliberately lean: heavy media,
# GPU, and desktop-environment stacks are NOT baked in. The feature-gated tools
# that need them (image/music generation, visual grounding, viewable desktop)
# install their dependencies on demand when the feature is toggled on.
#
# NOTE: python3-pip is deliberately omitted.  We bootstrap pip via ensurepip
# for Python 3.12.  The system python3-pip drags in 3.10-era packages (PIL,
# blinker, …) into /usr/lib/python3/dist-packages/ which 3.12 then picks up,
# causing C-extension ABI mismatches.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      # Build tools & CLI
      software-properties-common curl gnupg2 xz-utils ca-certificates jq \
      build-essential git sudo unzip wget gosu file \
      # Search
      ripgrep \
      # X virtual framebuffer + D-Bus. Playwright needs an X display even when
      # the viewable desktop is disabled, and the entrypoint launches dbus
      # unconditionally. tini reaps zombies as PID 1.
      xvfb dbus-x11 tini \
      # Fonts so the browser renders text (it runs headful under Xvfb)
      fonts-dejavu-core && \
    # Python 3.12 via deadsnakes PPA
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      python3.12 python3.12-venv python3.12-dev && \
    # Clean up system Python packages that leak into 3.12's import path.
    # These are 3.10-compiled C extensions — they segfault or ImportError
    # when loaded by 3.12.
    rm -rf /usr/lib/python3/dist-packages/PIL \
           /usr/lib/python3/dist-packages/Pillow* \
           /usr/lib/python3/dist-packages/blinker* && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# ── GitHub CLI ────────────────────────────────────────────────────────────────
RUN mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      > /etc/apt/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends gh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ── uv (fast Python package installer) ───────────────────────────────────────
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    cp /root/.local/bin/uv /usr/local/bin/uv && \
    cp /root/.local/bin/uvx /usr/local/bin/uvx

# ── Python 3.12 setup ────────────────────────────────────────────────────────
RUN python3.12 -m ensurepip --upgrade && \
    rm -f /usr/lib/python3.12/EXTERNALLY-MANAGED && \
    # Consistent python/pip aliases
    ln -sf /usr/bin/python3.12 /usr/local/bin/python && \
    ln -sf /usr/bin/python3.12 /usr/local/bin/python3 && \
    printf '#!/bin/bash\nexec python3.12 -m pip "$@"\n' > /usr/local/bin/pip && \
    chmod +x /usr/local/bin/pip && \
    ln -sf /usr/local/bin/pip /usr/local/bin/pip3 && \
    python3.12 -m pip install --no-cache-dir --upgrade pip

# ── Browser (browser automation) ─────────────────────────────────────────────
# amd64: Google Chrome (used by Playwright channel="chrome").
# arm64: Playwright's bundled Chromium (Google does not publish Chrome for
#        linux/arm64). --with-deps installs the runtime shared libraries.
RUN case "${TARGETARCH}" in \
      amd64) \
        curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
          | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg && \
        echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] \
          https://dl.google.com/linux/chrome/deb/ stable main" \
          > /etc/apt/sources.list.d/google-chrome.list && \
        apt-get update && \
        apt-get install -y --no-install-recommends google-chrome-stable && \
        apt-get clean && rm -rf /var/lib/apt/lists/* \
        ;; \
      arm64) \
        python3.12 -m pip install --no-cache-dir playwright==1.52.0 && \
        python3.12 -m playwright install --with-deps chromium \
        ;; \
      *) \
        echo "ERROR: unsupported arch for browser: ${TARGETARCH}"; exit 1 \
        ;; \
    esac

# ── Users & permissions ──────────────────────────────────────────────────────
# Two-user trust split for credential isolation:
#   omnideck (UID 1000) — runs the app server, agent tools, and desktop.
#   broker   (UID 1001) — runs the integrations supervisor and the broker
#                         subprocesses it spawns. Owns the credential vault
#                         (mode 0700) so omnideck can't read decrypted creds.
# omnideck is in the broker group ONLY so it can connect to /run/cvault/app.sock
# (mode 0660 broker:broker) — the entry point that admin RPCs ride.
RUN groupadd --gid 1001 broker && \
    useradd --uid 1001 --gid 1001 --no-create-home --shell /usr/sbin/nologin broker && \
    useradd --create-home --shell /bin/bash --uid 1000 omnideck && \
    usermod -aG broker omnideck && \
    passwd -d omnideck && \
    mkdir -p /var/lib/omnideck && \
    chown omnideck:omnideck /var/lib/omnideck && \
    chmod 755 /var/lib/omnideck && \
    chown -R omnideck:omnideck /home/omnideck && \
    mkdir -p /home/omnideck/Desktop && \
    mkdir -p /home/omnideck/downloads && \
    # Sudoers: omnideck can install packages as root
    echo "omnideck ALL=(root) NOPASSWD: /usr/bin/apt-get, /usr/local/bin/pip, /usr/local/bin/npm" \
      > /etc/sudoers.d/omnideck && \
    chmod 440 /etc/sudoers.d/omnideck && \
    # Safety shims: anything still referencing the old computron paths
    # resolves to the renamed locations. /opt/omnideck is created later in
    # the build; a briefly dangling symlink is fine.
    ln -s /home/omnideck /home/computron && \
    ln -s /var/lib/omnideck /var/lib/computron && \
    ln -s /opt/omnideck /opt/computron

# ── Xfce config ──────────────────────────────────────────────────────────────
# Written ahead of time so the viewable desktop works immediately if its
# packages are installed on demand. Harmless when the desktop is disabled.
RUN mkdir -p /home/omnideck/.config/xfce4/xfconf/xfce-perchannel-xml && \
    printf '<?xml version="1.0" encoding="UTF-8"?>\n\
<channel name="xsettings" version="1.0">\n\
  <property name="Net" type="empty">\n\
    <property name="ThemeName" type="string" value="Greybird"/>\n\
    <property name="IconThemeName" type="string" value="elementary-xfce-dark"/>\n\
    <property name="CursorThemeName" type="string" value="DMZ-White"/>\n\
    <property name="CursorSize" type="int" value="24"/>\n\
  </property>\n\
</channel>\n' \
      > /home/omnideck/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml && \
    printf '<?xml version="1.0" encoding="UTF-8"?>\n\
<channel name="xfwm4" version="1.0">\n\
  <property name="general" type="empty">\n\
    <property name="theme" type="string" value="Greybird"/>\n\
  </property>\n\
</channel>\n' \
      > /home/omnideck/.config/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml && \
    printf '<?xml version="1.0" encoding="UTF-8"?>\n\
<channel name="xfce4-power-manager" version="1.0">\n\
  <property name="xfce4-power-manager" type="empty">\n\
    <property name="dpms-enabled" type="bool" value="false"/>\n\
    <property name="blank-on-ac" type="int" value="0"/>\n\
    <property name="dpms-on-ac-sleep" type="uint" value="0"/>\n\
    <property name="dpms-on-ac-off" type="uint" value="0"/>\n\
  </property>\n\
</channel>\n' \
      > /home/omnideck/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml && \
    chown -R omnideck:omnideck /home/omnideck/.config && \
    printf 'export DISPLAY=:99\n' > /etc/profile.d/display.sh && \
    chmod 644 /etc/profile.d/display.sh

# ── Desktop scripts ───────────────────────────────────────────────────────────
COPY container/a11y_tree.py /opt/desktop/a11y_tree.py
RUN chmod 755 /opt/desktop/a11y_tree.py && \
    mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix

# ── App dependencies (cached unless manifests change) ────────────────────────
WORKDIR /opt/omnideck
COPY pyproject.toml uv.lock ./
RUN uv pip install --system --no-cache -e . 2>/dev/null || true

# ── App source ───────────────────────────────────────────────────────────────
COPY --chmod=755 . /opt/omnideck/
RUN uv pip install --system --no-cache -e .

# Prebuilt UI assets from the ui-builder stage (no node_modules in this image).
COPY --from=ui-builder /ui/dist /opt/omnideck/server/ui/dist

# ── Entrypoint (late COPY so edits don't bust app/UI cache) ─────────────────
COPY container/entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/entrypoint.sh

SHELL ["/bin/bash", "-c"]

EXPOSE 8080 5900 6080

# tini reaps zombie processes; entrypoint starts desktop then app server
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/entrypoint.sh"]
