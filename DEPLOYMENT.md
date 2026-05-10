# AIRIS MCP Gateway - Production Deployment Guide

## Prerequisites

- Docker and Docker Compose
- 4GB+ RAM recommended
- Ports: 9400 (API), 9390 (internal gateway)

## Quick Start

```bash
# Clone and configure
git clone https://github.com/agiletec/airis-mcp-gateway.git
cd airis-mcp-gateway
cp mcp-config.json.example mcp-config.json

# Set production environment variables
export ALLOWED_ORIGINS=https://your-app.com
export AIRIS_API_KEY=$(openssl rand -hex 32)

# Start
docker compose up -d

# Initialize the global AIRIS registry
./scripts/airis-gateway init

# Register with Claude Code if needed
claude mcp add --scope user --transport sse airis-mcp-gateway http://localhost:9400/sse
```

If you are migrating existing repositories, import and remove any repo-local `mcp.json` files:

```bash
./scripts/airis-gateway import ~/github --apply
./scripts/airis-gateway clean ~/github
./scripts/airis-gateway doctor ~/github
```

## Environment Variables

### Security (Required for Production)

| Variable | Default | Description |
|----------|---------|-------------|
| `ALLOWED_ORIGINS` | `*` | Comma-separated list of allowed CORS origins. **Set explicitly in production.** |
| `AIRIS_API_KEY` | *(none)* | API key for Bearer token authentication. If not set, auth is disabled. |

### Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_PER_IP` | `100` | Requests per minute per IP address |
| `RATE_LIMIT_PER_API_KEY` | `1000` | Requests per minute per API key |

**Note:** Rate limiting uses in-memory storage (fixed window algorithm). This works well for single-process deployments. For multi-process/multi-instance deployments, implement Redis-backed rate limiting or use an API gateway.

### Request Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_REQUEST_SIZE` | `10485760` | Maximum request body size in bytes (10MB) |
| `TOOL_CALL_TIMEOUT` | `90` | MCP tool call timeout in seconds |

### Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Log level: DEBUG, INFO, WARNING, ERROR |
| `LOG_FORMAT` | `json` | Log format: `json` (production) or `standard` (development) |

### Shutdown

| Variable | Default | Description |
|----------|---------|-------------|
| `SHUTDOWN_TIMEOUT` | `30` | Graceful shutdown timeout in seconds |

### MCP Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_GATEWAY_URL` | `http://gateway:9390` | Internal Docker MCP Gateway URL |
| `MCP_CONFIG_PATH` | `/app/mcp-config.json` | Path to MCP server configuration |
| `DYNAMIC_MCP` | `true` | Enable Dynamic MCP (3 meta-tools only) |

## Resource Limits

The default `docker-compose.yml` sets:
- Memory: 2GB
- CPU: 2 cores

Adjust based on your workload:

```yaml
services:
  api:
    mem_limit: 4g
    cpus: 4
```

For Kubernetes/Swarm, use `deploy.resources`:

```yaml
services:
  api:
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: '4'
        reservations:
          memory: 1G
          cpus: '1'
```

## Monitoring

### Health Checks

```bash
# Liveness
curl http://localhost:9400/health

# Readiness (includes gateway connectivity)
curl http://localhost:9400/ready
```

### Metrics

Prometheus-compatible metrics at `/metrics`:

```bash
curl http://localhost:9400/metrics
```

Metrics exposed:
- `http_requests_total{method,path,status}` - Request count
- `http_request_latency_p50_ms{path}` - Latency percentiles
- `mcp_server_*` - MCP server process metrics

### Request Tracing

All requests include `X-Request-ID` header for correlation:

```bash
curl -v http://localhost:9400/health
# Response includes: X-Request-ID: <uuid>
```

Filter logs by request ID:
```bash
docker compose logs api | grep "request_id\":\"<uuid>\""
```

## Reverse Proxy Setup

### nginx

```nginx
server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate /etc/ssl/certs/api.crt;
    ssl_certificate_key /etc/ssl/private/api.key;

    location / {
        proxy_pass http://localhost:9400;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE support
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400;
    }
}
```

### Traefik

```yaml
# docker-compose.override.yml
services:
  api:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.airis.rule=Host(`api.example.com`)"
      - "traefik.http.routers.airis.tls=true"
      - "traefik.http.services.airis.loadbalancer.server.port=8000"
```

## Scaling

### Single Instance (Recommended for MVP)

The default setup runs a single API instance. This is sufficient for most use cases as:
- MCP tool calls are I/O bound (waiting for subprocess responses)
- Rate limiting works correctly in single-process mode
- Simpler debugging with single log stream

### Multiple Instances

For high availability, consider:
1. External rate limiting (API gateway, nginx)
2. Shared session storage (Redis for SSE session affinity)
3. Centralized logging (ELK, Datadog)

## Troubleshooting

### Common Issues

**"Server not found"**
```bash
# Check mcp-config.json
cat mcp-config.json | jq '.mcpServers | keys'

# Restart after config changes
docker compose restart api
```

**"Connection timeout"**
```bash
# Check gateway connectivity
docker compose logs gateway

# Verify internal network
docker compose exec api curl -v http://gateway:9390/health
```

**"Rate limit exceeded"**
```bash
# Check current limits
curl http://localhost:9400/metrics | grep rate

# Increase limits
export RATE_LIMIT_PER_IP=200
docker compose up -d
```

### Log Analysis

```bash
# All logs (JSON format)
docker compose logs api -f

# Filter errors
docker compose logs api 2>&1 | jq 'select(.level == "ERROR")'

# Filter by request ID
docker compose logs api 2>&1 | jq 'select(.request_id == "abc-123")'
```

## Security Checklist

- [ ] Set `ALLOWED_ORIGINS` (do not use `*` in production)
- [ ] Set `AIRIS_API_KEY` for public-facing deployments
- [ ] Use HTTPS via reverse proxy
- [ ] Review `mcp-config.json` for sensitive credentials
- [ ] Enable log aggregation for audit trails
- [ ] Set up monitoring alerts for 4xx/5xx spikes
- [ ] Regular security updates (`docker compose pull && docker compose up -d`)
