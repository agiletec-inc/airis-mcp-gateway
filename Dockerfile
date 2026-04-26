# syntax=docker/dockerfile:1.7

# NOTE: This file is NOT used by docker-compose.yml. The active build is
# apps/api/Dockerfile. This multi-stage definition is retained for external
# tooling (e.g. `docker build --target measurement`). Base image tags are
# pinned (issue #77) so that whatever still consumes it is reproducible.

###########################################
# API (FastAPI + uv + Alembic)
###########################################
FROM python:3.12.13-slim-trixie AS api

RUN pip install --no-cache-dir uv
WORKDIR /app

COPY apps/api/pyproject.toml ./pyproject.toml
RUN uv pip install --system -r pyproject.toml
RUN uv pip install --system pytest pytest-asyncio httpx pytest-cov

COPY apps/api/src ./src
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

ENV PYTHONPATH=/app/src
ENTRYPOINT ["./entrypoint.sh"]


###########################################
# Settings UI (Vite + pnpm + nginx)
###########################################
FROM node:24.9.0-alpine3.20 AS settings-builder

RUN corepack enable && corepack prepare pnpm@latest --activate
WORKDIR /monorepo

COPY package.json pnpm-workspace.yaml ./
COPY apps/settings ./apps/settings
COPY apps/mindbase/package.json ./apps/mindbase/package.json
COPY apps/airis-commands/package.json ./apps/airis-commands/package.json
COPY apps/gateway-control/package.json ./apps/gateway-control/package.json

RUN pnpm install
WORKDIR /monorepo/apps/settings
RUN pnpm build

FROM nginx:1.27.5-alpine AS settings
ENV UI_PORT=5273 \
    API_PROXY_URL=http://api:9400

COPY --from=settings-builder /monorepo/apps/settings/out /usr/share/nginx/html
COPY apps/settings/nginx/default.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 5273
CMD ["sh", "-c", "envsubst '$$UI_PORT $$API_PROXY_URL' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && exec nginx -g 'daemon off;'"]


###########################################
# Gateway (docker/mcp-gateway base)
###########################################
# NOTE: docker/mcp-gateway does not publish versioned tags on Docker Hub, so
# we track :latest here. Pin by digest once upstream tags are available.
FROM docker/mcp-gateway:latest AS gateway

LABEL maintainer="AIRIS MCP Gateway Team"
LABEL description="AIRIS MCP Gateway - Centralized MCP Server routing with docker/mcp-gateway"

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
  CMD wget --no-verbose --tries=1 --spider "http://127.0.0.1:9390/health" || exit 1


###########################################
# MindBase MCP Server Builder
###########################################
FROM node:24.9.0-alpine3.20 AS mindbase-builder

RUN corepack enable && corepack prepare pnpm@latest --activate
WORKDIR /app
CMD ["sh", "-c", "pnpm install && pnpm build && sleep infinity"]


###########################################
# Gateway Control MCP Server Builder
###########################################
FROM node:24.9.0-alpine3.20 AS gateway-control-builder

WORKDIR /app
CMD ["sh", "-c", "npm install && npm run build && sleep infinity"]


###########################################
# Token Measurement
###########################################
FROM python:3.12.13-slim-trixie AS measurement

WORKDIR /app
COPY tools/measurement/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tools/measurement/measure_token_reduction.py .
RUN chmod +x measure_token_reduction.py
CMD ["python", "measure_token_reduction.py"]
