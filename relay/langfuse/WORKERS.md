# Cloudflare Workers Deployment Guide

## Important: OTEL v4 Migration

**The legacy `/api/public/ingestion` endpoint is deprecated and will stop accepting events after November 16, 2026.**

This Worker has been updated to:
- Convert legacy batch payloads from old clients to OTEL format
- Forward to Langfuse's new `/api/public/otel/v1/traces` endpoint with `x-langfuse-ingestion-version: 4`
- Maintain backward compatibility with existing PsyClaw releases

**After merging this PR, the Worker must be redeployed** using `wrangler deploy` for the migration to take effect.

## Quick Start

### 1. Install Wrangler CLI

```bash
npm install -g wrangler
```

### 2. Authenticate

```bash
wrangler login
```

### 3. Set Secrets

```bash
cd relay/langfuse

wrangler secret put LANGFUSE_PUBLIC_KEY
# Paste your pk_lf_... key

wrangler secret put LANGFUSE_SECRET_KEY
# Paste your sk_lf_... key
```

### 4. Deploy

```bash
wrangler deploy
```

You'll get a URL like:
```
https://psyclaw-langfuse-relay.your-account.workers.dev
```

### 5. Test

```bash
curl -X POST https://psyclaw-langfuse-relay.your-account.workers.dev/ingestion \
  -H "Content-Type: application/json" \
  -d '{"batch":[],"metadata":{"batch_size":0}}'
```

### 6. Configure PsyClaw

```bash
export LANGFUSE_RELAY_URL=https://psyclaw-langfuse-relay.your-account.workers.dev
pnpm build
```

## Configuration

### Optional Secrets

```bash
# Override Langfuse host (default: https://us.cloud.langfuse.com)
wrangler secret put LANGFUSE_HOST

# Restrict CORS (default: *)
wrangler secret put ALLOWED_ORIGINS
# Example: https://app.example.com,https://staging.example.com
```

### Custom Domain

Edit `wrangler.toml`:

```toml
routes = [
  { pattern = "langfuse-relay.example.com/*", zone_name = "example.com" }
]
```

Deploy:

```bash
wrangler deploy
```

## Monitoring

View logs:

```bash
wrangler tail
```

View metrics in Cloudflare dashboard:
- Requests per second
- Error rate
- Latency (p50, p95, p99)

## Updating

To rotate secrets or change configuration:

```bash
wrangler secret put LANGFUSE_SECRET_KEY
wrangler deploy
```

## Production Checklist

- [ ] Worker deployed and tested
- [ ] Secrets rotated from initial test values
- [ ] `LANGFUSE_RELAY_URL` set in PsyClaw CI/release env
- [ ] Traces verified in Langfuse Cloud dashboard (v4 ingestion)
- [ ] Monitoring/alerting configured (optional, via Cloudflare dashboard)
- [ ] Custom domain configured (optional)

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `Worker not configured` error | Run `wrangler secret put LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` |
| 502 Bad Gateway | Check `LANGFUSE_HOST` is correct; verify network connectivity to Langfuse |
| 401 Unauthorized | Verify secrets are correct: `wrangler secret put LANGFUSE_PUBLIC_KEY` |
| No traces in Langfuse | Check Worker logs: `wrangler tail`; verify v4 endpoint is being used |

## Migration Details

### What Changed

1. **Endpoint**: `/api/public/ingestion` → `/api/public/otel/v1/traces`
2. **Format**: Legacy batch format → OTLP/HTTP JSON format
3. **Header**: Added `x-langfuse-ingestion-version: 4`
4. **Backward Compatibility**: Old clients sending legacy format are automatically converted

### Format Conversion

The Worker converts legacy events:
- `trace-create` → OTEL trace context
- `generation-create` → OTEL span with `langfuse.observation.type: generation`
- Preserves: session IDs, user IDs, metadata, usage, cost

### Client Migration

- **Relay mode** (production): Old clients still send legacy format; relay converts it
- **Direct mode** (local dev): Updated to send OTEL format directly to v4 endpoint
- **No client changes required** for existing releases using the relay

## Advantages

✅ **Zero maintenance** - Cloudflare handles scaling, availability, SSL  
✅ **Global edge network** - Low latency worldwide  
✅ **Free tier** - 100k requests/day included  
✅ **Built-in DDoS protection**  
✅ **Automatic HTTPS**  
✅ **Simple secrets management** - `wrangler secret put`

## Cost

Cloudflare Workers pricing (as of 2024):

- **Free tier**: 100,000 requests/day
- **Paid**: $5/month for 10M requests, then $0.50 per additional 1M

For typical PsyClaw usage (hundreds of LLM calls per day), the free tier is sufficient.

## References

- [Langfuse OTEL v4 Migration Guide](https://langfuse.com/integrations/native/opentelemetry/migration-to-v4)
- [Deprecated API Migration](https://langfuse.com/faq/all/deprecated-api-migration)
- [OTLP/HTTP Endpoint Configuration](https://langfuse.com/docs/integrations/opentelemetry/get-started#endpoint-configuration)
