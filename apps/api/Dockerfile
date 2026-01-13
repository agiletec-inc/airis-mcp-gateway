# FastAPI Hybrid MCP Gateway
# Supports both Docker MCP Gateway proxy and direct uvx/npx process management
# Includes browser automation support for Playwright and chrome-devtools MCP servers
FROM python:3.12-slim

# Install system dependencies including Chromium for browser automation
RUN apt-get update && apt-get install -y --no-install-recommends \
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
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (for npx MCP servers)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install uv (for uvx MCP servers)
RUN pip install --no-cache-dir uv

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

# Pre-install Playwright Chromium (uses system chromium, installs dependencies)
RUN npx playwright install chromium --with-deps || echo "Playwright will use system Chromium"

WORKDIR /app

# Copy MCP server sources and build them (bundled with esbuild, no node_modules needed at runtime)
# Build gateway-control
COPY apps/gateway-control/package*.json /tmp/gateway-control/
COPY apps/gateway-control/src /tmp/gateway-control/src/
COPY apps/gateway-control/tsconfig.json /tmp/gateway-control/
RUN cd /tmp/gateway-control && npm install && npm run build \
    && mkdir -p /app/gateway-control && cp dist/index.js /app/gateway-control/ \
    && rm -rf /tmp/gateway-control

# Build airis-commands
COPY apps/airis-commands/package*.json /tmp/airis-commands/
COPY apps/airis-commands/src /tmp/airis-commands/src/
COPY apps/airis-commands/tsconfig.json /tmp/airis-commands/
RUN cd /tmp/airis-commands && npm install && npm run build \
    && mkdir -p /app/airis-commands && cp dist/index.js /app/airis-commands/ \
    && rm -rf /tmp/airis-commands

# Copy Python API source and install
COPY apps/api /app/api-src
WORKDIR /app/api-src
RUN uv pip install --system -e .

# Copy config files (can be overridden by volume mounts)
COPY mcp-config.json /app/mcp-config.json
COPY config /app/config

# Create data directory for persistent storage (memory.json, etc.)
RUN mkdir -p /app/data

# API port
EXPOSE 8000
# VNC port (for VNC clients like RealVNC, TightVNC)
EXPOSE 5900
# noVNC web port (access browser view at http://localhost:6080/vnc.html)
EXPOSE 6080

# Copy startup script (separate file to avoid CRLF issues on Windows)
COPY apps/api/start.sh /app/start.sh
# Convert line endings to Unix format and make executable
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

# Run from api-src directory where the package is installed
CMD ["/app/start.sh"]
