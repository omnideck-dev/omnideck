FROM node:24-bookworm-slim@sha256:3638d9a6fe4030bd716be989438248074489337ba3275657f93595428be4fc03 AS node-runtime

FROM rust:1.89.0-bookworm@sha256:948f9b08a66e7fe01b03a98ef1c7568292e07ec2e4fe90d88c07bb14563c84ff

LABEL org.opencontainers.image.title="omnideck desktop Windows builder" \
      org.opencontainers.image.description="Pinned cross-toolchain for local Windows desktop packaging" \
      org.opencontainers.image.source="https://github.com/omnideck-dev/omnideck/tree/main/desktop/containers/windows-builder"

ARG PNPM_VERSION=11.20.0

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
      ca-certificates \
      clang \
      gcc-mingw-w64-x86-64 \
      g++-mingw-w64-x86-64 \
      lld \
      nsis \
      pkg-config \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack \
    && ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

RUN rustup target add x86_64-pc-windows-gnu \
    && npm install --global --no-update-notifier "pnpm@${PNPM_VERSION}"

ENV PATH="/usr/local/cargo/bin:/usr/local/bin:${PATH}" \
    CARGO_TERM_COLOR=always \
    npm_config_update_notifier=false \
    npm_config_fund=false \
    RUSTFLAGS="-C target-feature=+crt-static"

WORKDIR /workspace/desktop
