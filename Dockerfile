# syntax=docker/dockerfile:1.7
# FastAPI MCP Gateway for direct on-demand process tools.
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
    curl

# Copy Node.js binaries from the official image (issue #137: avoids curl | bash).
# node_modules is copied first; npm/npx are created as symlinks because Docker
# COPY dereferences symlinks, breaking relative require() paths inside npm-cli.js.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm cache clean --force

# Install uv (for uvx MCP servers)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install uv

# Verify installations
RUN node --version && npm --version && npx --version && uvx --help || true

WORKDIR /app

# Copy Python API source and install. `-e .` requires the source tree, so we
# keep the single COPY; the uv cache mount still speeds up repeat builds by
# reusing the downloaded wheels.
#
# Frozen, lockfile-driven install (issue #192): `uv export --frozen` refuses
# to re-resolve and errors if uv.lock is stale relative to pyproject.toml, so
# the image is built from exactly the versions pinned in uv.lock (including
# the project itself, via `-e .`) instead of a fresh resolve on every build.
COPY apps/api /app/api-src
WORKDIR /app/api-src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --frozen --no-hashes -o requirements.lock.txt \
    && uv pip install --system -r requirements.lock.txt

# Copy config files (can be overridden by volume mounts)
COPY mcp-config.json.example /app/mcp-config.json
COPY config /app/config

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
# Run from api-src directory where the package is installed
CMD ["/app/start.sh"]
