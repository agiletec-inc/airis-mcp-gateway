# FastAPI Hybrid MCP Gateway
# Supports both Docker MCP Gateway proxy and direct uvx/npx process management
FROM python:3.12-slim

# Install system dependencies including Chromium and its dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    # Chromium and browser dependencies for Playwright/chrome-devtools
    chromium \
    chromium-driver \
    # Required for headless browser operation
    xvfb \
    # Common browser dependencies
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

# Set up Playwright browsers path
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright
ENV CHROME_PATH=/usr/bin/chromium

# Create cache directory for Playwright
RUN mkdir -p /app/.cache/ms-playwright

# Verify installations
RUN node --version && npm --version && npx --version && uvx --help || true
RUN chromium --version || true

WORKDIR /app

# Copy API source (context is project root)
COPY apps/api/pyproject.toml ./
COPY apps/api/src ./src

# Copy gateway-control and airis-commands dist files for bundled MCP servers
COPY apps/gateway-control/dist ./gateway-control
COPY apps/airis-commands/dist ./airis-commands

# Install Python dependencies
RUN uv pip install --system -e .

# Install Playwright browsers (Chromium only to save space)
RUN npx playwright install chromium --with-deps || true

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
