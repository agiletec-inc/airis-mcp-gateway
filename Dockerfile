# syntax=docker/dockerfile:1.7
# FastAPI Hybrid MCP Gateway
# Supports both Docker MCP Gateway proxy and direct uvx/npx process management
# Includes browser automation support for Playwright and chrome-devtools MCP servers
#
# Both base images are pinned to specific patch versions (issue #77).
# node:22-slim ships node/npm/npx; they are copied into the Python image
# at build time so we never run a remote shell script as root (issue #137).
FROM node:22.15.0-slim AS node-runtime

FROM python:3.12.13-slim-trixie

# Keep apt lists across layers in a BuildKit cache so repeated builds don't
# re-download the same packages. rm -rf is NOT needed because the cache mount
# is not written into the image layer.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    # Chromium browser for Playwright/chrome-devtools MCP servers
    chromium \
    chromium-driver \
    # Virtual framebuffer for headless browser operation
    xvfb \
    # VNC server for non-headless (headed) browser debugging
    x11vnc \
    # Lightweight window manager for VNC sessions
    fluxbox \
    # Web-based VNC client (access via browser at port 6080)
    novnc \
    websockify \
    # Browser runtime dependencies
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    fonts-noto-color-emoji

# Copy Node.js binaries from the official image (issue #137: avoids curl | bash).
# node_modules is copied first; npm/npx are created as symlinks because Docker
# COPY dereferences symlinks, breaking relative require() paths inside npm-cli.js.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install -g pnpm@10.33.4 \
    && npm cache clean --force

# Install airis CLI (airis-workspace's stdio MCP server, exposed as `airis mcp`).
#
# Uses cargo-binstall, which fetches prebuilt binaries from the upstream
# GitHub release based on the `[package.metadata.binstall]` block in
# airis-workspace's Cargo.toml. This makes airis-workspace the single
# source of truth for release URL conventions — the gateway image does
# not need to know target-triple mapping or release filename schemes.
#
# `--strategies crate-meta-data` disables source-build fallback so a
# missing release artifact fails loudly instead of silently dragging in a
# Rust toolchain at image-build time. cargo-binstall is removed after use
# to keep the runtime image lean.
ARG AIRIS_VERSION=4.0.0
ARG BINSTALL_VERSION=1.18.1
RUN set -eux; \
    curl -fsSL "https://github.com/cargo-bins/cargo-binstall/releases/download/v${BINSTALL_VERSION}/cargo-binstall-$(uname -m)-unknown-linux-musl.tgz" \
      | tar -xz -C /usr/local/bin cargo-binstall; \
    cargo-binstall --no-confirm --no-symlinks \
        --strategies crate-meta-data \
        --root /usr/local \
        airis-workspace --version "${AIRIS_VERSION}"; \
    rm /usr/local/bin/cargo-binstall; \
    airis-workspace --version

# Install uv (for uvx MCP servers)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install uv

# Configure browser paths for MCP servers
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright
ENV CHROME_PATH=/usr/bin/chromium

# VNC configuration for non-headless browser debugging
# Set BROWSER_MODE=headed to enable VNC (default: headless)
ENV BROWSER_MODE=headless
ENV VNC_PORT=5900
ENV NOVNC_PORT=6080
ENV DISPLAY=:99
ENV VNC_RESOLUTION=1920x1080x24

# Create Playwright cache directory
RUN mkdir -p /app/.cache/ms-playwright

# Verify installations
RUN node --version && npm --version && npx --version && uvx --help || true
RUN chromium --version || echo "Chromium installed at /usr/bin/chromium"

# Pre-install Playwright Chromium (uses system chromium, installs dependencies).
# Use /tmp/playwright-cache as a temporary BuildKit cache; the final browsers
# live under PLAYWRIGHT_BROWSERS_PATH (/app/.cache/ms-playwright) and are not
# cached because they must stay in the final image.
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    npx playwright install chromium --with-deps || echo "Playwright will use system Chromium"

WORKDIR /app

# Build the TypeScript MCP servers via the pnpm workspace.
# Workspace manifests (pnpm-workspace.yaml, root package.json, lockfile, .npmrc,
# per-app package.json + tsconfig) are COPYed BEFORE src/ so a source-only change
# reuses the cached `pnpm install` layer. esbuild bundles everything, so no
# node_modules is needed at runtime — only each dist/index.js is kept.
# Use `pnpm install --frozen-lockfile` so the lockfile must be in sync (issue #81).
ENV PNPM_STORE_DIR=/pnpm/store
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml .npmrc /tmp/ts-workspace/
COPY apps/gateway-control/package.json /tmp/ts-workspace/apps/gateway-control/
COPY apps/airis-commands/package.json /tmp/ts-workspace/apps/airis-commands/
COPY apps/gateway-control/tsconfig.json /tmp/ts-workspace/apps/gateway-control/
COPY apps/airis-commands/tsconfig.json /tmp/ts-workspace/apps/airis-commands/
COPY apps/gateway-control/src /tmp/ts-workspace/apps/gateway-control/src/
COPY apps/airis-commands/src /tmp/ts-workspace/apps/airis-commands/src/
RUN --mount=type=cache,target=/pnpm/store,sharing=locked \
    cd /tmp/ts-workspace \
    && pnpm install --frozen-lockfile \
    && pnpm -r run build \
    && mkdir -p /app/gateway-control /app/airis-commands \
    && cp apps/gateway-control/dist/index.js /app/gateway-control/ \
    && cp apps/airis-commands/dist/index.js /app/airis-commands/ \
    && rm -rf /tmp/ts-workspace

# Copy Python API source and install. `-e .` requires the source tree, so we
# keep the single COPY; the uv cache mount still speeds up repeat builds by
# reusing the downloaded wheels.
COPY apps/api /app/api-src
WORKDIR /app/api-src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -e .

# Copy config files (can be overridden by volume mounts)
COPY mcp-config.json.example /app/mcp-config.json
COPY config /app/config

# Create data directory for persistent storage (memory.json, etc.)
RUN mkdir -p /app/data

# Copy startup script (separate file to avoid CRLF issues on Windows)
COPY apps/api/start.sh /app/start.sh
# Convert line endings to Unix format and make executable
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

# Create non-root user for security
# UID 1000 matches typical host user for volume permissions
RUN useradd -m -u 1000 -s /bin/bash appuser

# Create cache directories for appuser
RUN mkdir -p /home/appuser/.cache/uv

# Change ownership of app directories to appuser
RUN chown -R appuser:appuser /app /home/appuser

# Switch to non-root user
USER appuser

# Set HOME for uv/npm cache paths
ENV HOME=/home/appuser
# Use temp-based npm cache to avoid root-owned cache from build stage
ENV NPM_CONFIG_CACHE=/tmp/.npm-cache

# API port
EXPOSE 8000
# VNC port (for VNC clients like RealVNC, TightVNC)
EXPOSE 5900
# noVNC web port (access browser view at http://localhost:6080/vnc.html)
EXPOSE 6080

# Run from api-src directory where the package is installed
CMD ["/app/start.sh"]
