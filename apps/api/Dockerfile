# FastAPI Hybrid MCP Gateway
# Supports both Docker MCP Gateway proxy and direct uvx/npx process management
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (for npx MCP servers)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install uv (for uvx MCP servers)
RUN pip install --no-cache-dir uv

# Verify installations
RUN node --version && npm --version && npx --version && uvx --help || true

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

EXPOSE 8000

# Run from api-src directory where the package is installed
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
