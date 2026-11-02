# Langfuse Relay Server

Lightweight proxy server that forwards Langfuse ingestion payloads from production PsyClaw clients to Langfuse Cloud with authentication. This allows release binaries to embed only `LANGFUSE_RELAY_URL` (public) instead of `LANGFUSE_SECRET_KEY` (sensitive).

**Important**: Updated for Langfuse OTEL v4 migration. The relay now converts legacy batch format to OTEL spans and forwards to `/api/public/otel/v1/traces`, maintaining backward compatibility with old clients.

## Architecture

```
PsyClaw Client (release build)
  ↓ POST /ingestion (legacy batch format, no auth, LANGFUSE_RELAY_URL)
Relay Server (converts to OTEL format)
  ↓ POST /api/public/otel/v1/traces (OTEL spans, Basic auth, x-langfuse-ingestion-version: 4)
Langfuse Cloud
```

**Note**: The legacy `/api/public/ingestion` endpoint is deprecated and will stop accepting events after November 16, 2026.

## Setup

### Prerequisites

- Node.js 22+ (for standalone Node server)
- Langfuse project credentials:
  - `LANGFUSE_PUBLIC_KEY` (e.g., `pk_lf_...`)
  - `LANGFUSE_SECRET_KEY` (e.g., `sk_lf_...`)

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LANGFUSE_PUBLIC_KEY` | ✅ | - | Langfuse project public key |
| `LANGFUSE_SECRET_KEY` | ✅ | - | Langfuse project secret key |
| `LANGFUSE_HOST` | ❌ | `https://cloud.langfuse.com` | Langfuse host URL |
| `PORT` | ❌ | `3000` | Relay server port |
| `ALLOWED_ORIGINS` | ❌ | `*` | Comma-separated CORS allowed origins |

## Deployment Options

### Option 1: Cloudflare Workers (Recommended)

**Best for production**: Edge deployment with automatic global scaling, zero maintenance, and built-in DDoS protection.

**After merging PR #XX, the Worker must be redeployed** for the OTEL v4 migration to take effect.

#### Prerequisites

- Cloudflare account (free tier works)
- Wrangler CLI: `npm install -g wrangler`

#### Deploy Steps

1. **Authenticate with Cloudflare**:
   ```bash
   wrangler login
   ```

2. **Navigate to relay directory**:
   ```bash
   cd relay/langfuse
   ```

3. **Set secrets** (one-time):
   ```bash
   # Will prompt for each value
   wrangler secret put LANGFUSE_PUBLIC_KEY
   # Enter: pk_lf_...

   wrangler secret put LANGFUSE_SECRET_KEY
   # Enter: sk_lf_...

   # Optional: Override Langfuse host (defaults to us.cloud.langfuse.com)
   wrangler secret put LANGFUSE_HOST
   # Enter: https://cloud.langfuse.com

   # Optional: Restrict CORS (defaults to *)
   wrangler secret put ALLOWED_ORIGINS
   # Enter: https://app.example.com,https://staging.example.com
   ```

4. **Deploy**:
   ```bash
   wrangler deploy
   ```

   Output will show your Worker URL:
   ```
   Published psyclaw-langfuse-relay
   https://psyclaw-langfuse-relay.your-subdomain.workers.dev
   ```

5. **Test the deployed Worker**:
   ```bash
   curl -X POST https://psyclaw-langfuse-relay.your-subdomain.workers.dev/ingestion \
     -H "Content-Type: application/json" \
     -d '{"batch":[],"metadata":{"batch_size":0}}'
   ```

6. **Use the Worker URL** as `LANGFUSE_RELAY_URL`:
   ```bash
   export LANGFUSE_RELAY_URL=https://psyclaw-langfuse-relay.your-subdomain.workers.dev
   pnpm build
   ```

#### Update Secrets

To rotate keys or change configuration:

```bash
cd relay/langfuse
wrangler secret put LANGFUSE_SECRET_KEY
wrangler deploy  # Redeploy to pick up changes
```

#### Custom Domain (Optional)

Add to `wrangler.toml`:

```toml
routes = [
  { pattern = "langfuse-relay.example.com/*", zone_name = "example.com" }
]
```

Then deploy with custom domain:

```bash
wrangler deploy
```

### Option 2: Node.js Server (Standalone)

Simplest deployment for internal servers or VPCs.

```bash
# Run directly
LANGFUSE_PUBLIC_KEY=pk_lf_xxx LANGFUSE_SECRET_KEY=sk_lf_xxx node relay/langfuse/server.mjs

# Or with PM2
pm2 start relay/langfuse/server.mjs --name langfuse-relay --env production
```

### Option 3: Docker

```dockerfile
# Dockerfile
FROM node:22-alpine
WORKDIR /app
COPY relay/langfuse/server.mjs .
ENV PORT=3000
EXPOSE 3000
CMD ["node", "server.mjs"]
```

```bash
# Build and run
docker build -t psyclaw-langfuse-relay -f relay/langfuse/Dockerfile .
docker run -d \
  -p 3000:3000 \
  -e LANGFUSE_PUBLIC_KEY=pk_lf_xxx \
  -e LANGFUSE_SECRET_KEY=sk_lf_xxx \
  --name langfuse-relay \
  psyclaw-langfuse-relay
```

### Option 4: AWS Lambda / Google Cloud Functions

Serverless deployment with API Gateway:

- Package `server.mjs` as Lambda function handler
- Set environment variables in Lambda/Cloud Function config
- Expose via API Gateway / Cloud Function URL

## Testing

### Health Check

```bash
# Should return 404 (expected, relay only accepts POST /ingestion)
curl http://localhost:3000/
```

### Send Test Payload (Legacy Format)

```bash
curl -X POST http://localhost:3000/ingestion \
  -H "Content-Type: application/json" \
  -H "x-langfuse-sdk-name: psyclaw-test" \
  -H "x-langfuse-sdk-version: 0.31.1" \
  -d '{
    "batch": [],
    "metadata": { "batch_size": 0, "sdk_integration": "psyclaw" }
  }'
```

The relay will automatically convert the legacy format to OTEL spans.

### Verify Logs

```bash
# Node.js / PM2
pm2 logs langfuse-relay

# Docker
docker logs langfuse-relay
```

## Production Checklist

- [ ] Deploy relay to internal/private network (not publicly exposed)
- [ ] **Redeploy Worker after merging this PR** to enable OTEL v4 migration
- [ ] Set `ALLOWED_ORIGINS` to restrict CORS if needed
- [ ] Store `LANGFUSE_SECRET_KEY` in secrets manager (AWS Secrets Manager, GCP Secret Manager, etc.)
- [ ] Set up monitoring / alerting for relay health
- [ ] Verify traces appear in Langfuse Cloud project (v4 ingestion)
- [ ] Configure PsyClaw release builds with `LANGFUSE_RELAY_URL`:
  ```bash
  # Example: GitHub Actions secret / CI environment variable
  export LANGFUSE_RELAY_URL=https://langfuse-relay.internal.example.com
  ```

## Client Configuration

Once the relay is deployed, configure PsyClaw release builds:

### Build Time (embed in binary)

Set `LANGFUSE_RELAY_URL` environment variable at build time:

```bash
export LANGFUSE_RELAY_URL=https://your-relay.example.com
pnpm build
```

The build script (`scripts/inject-build-env.mjs`) automatically rewrites the compiled `PUBLIC_LANGFUSE_RELAY_URL` constant in `dist/src/observability/public-keys.js` after TypeScript compilation.

### Runtime Override (optional, for testing)

Users can override at runtime:

```bash
LANGFUSE_RELAY_URL=http://localhost:3000 psyclaw chat
```

## Security Notes

- **Do NOT expose the relay to the public internet** unless you implement additional authentication (API keys, IP allowlist, etc.)
- Relay forwards all payloads to Langfuse; no user PII is captured (PsyClaw telemetry uses privacy mode)
- `LANGFUSE_SECRET_KEY` must never be committed to git or included in release artifacts
- Consider rate limiting in production (e.g., via reverse proxy or API Gateway)

## OTEL v4 Migration

This relay has been updated to support Langfuse OTEL v4:

- **Backward compatible**: Old clients can still send legacy batch format
- **Automatic conversion**: Relay converts `trace-create` and `generation-create` events to OTEL spans
- **New endpoint**: Forwards to `/api/public/otel/v1/traces` with `x-langfuse-ingestion-version: 4`
- **Client updates**: New PsyClaw builds send OTEL format directly in direct mode (with keys set)

See [Langfuse OTEL v4 Migration Guide](https://langfuse.com/integrations/native/opentelemetry/migration-to-v4) for details.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `502 Bad Gateway` | Check `LANGFUSE_HOST` is correct; verify network connectivity to Langfuse Cloud |
| `401 Unauthorized` | Verify `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are correct |
| `413 Payload Too Large` | Increase relay limit or reduce client batch size |
| No traces in Langfuse | Check relay logs; verify client is sending to correct `LANGFUSE_RELAY_URL` |

## License

CC-BY-NC-4.0 (same as PsyClaw)
