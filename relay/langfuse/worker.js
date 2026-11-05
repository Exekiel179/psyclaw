/**
 * Cloudflare Worker for PsyClaw Langfuse relay.
 *
 * Receives Langfuse ingestion payloads from production clients and forwards
 * them to Langfuse Cloud with authentication. Supports both legacy batch format
 * (for backward compatibility with old clients) and OTEL spans.
 *
 * Required secrets (set via `wrangler secret put`):
 *   LANGFUSE_PUBLIC_KEY - Langfuse project public key
 *   LANGFUSE_SECRET_KEY - Langfuse project secret key
 *
 * Optional secrets:
 *   LANGFUSE_HOST - Langfuse host (default: https://us.cloud.langfuse.com)
 *   ALLOWED_ORIGINS - Comma-separated allowed origins for CORS (default: *)
 */

export default {
  async fetch(request, env, ctx) {
    const LANGFUSE_PUBLIC_KEY = env.LANGFUSE_PUBLIC_KEY;
    const LANGFUSE_SECRET_KEY = env.LANGFUSE_SECRET_KEY;
    const LANGFUSE_HOST = (env.LANGFUSE_HOST || 'https://us.cloud.langfuse.com').replace(/\/+$/, '');
    const ALLOWED_ORIGINS = env.ALLOWED_ORIGINS || '*';

    // Validate secrets are configured
    if (!LANGFUSE_PUBLIC_KEY || !LANGFUSE_SECRET_KEY) {
      return new Response(
        JSON.stringify({ error: 'Worker not configured: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required' }),
        {
          status: 500,
          headers: { 'content-type': 'application/json' },
        }
      );
    }

    const origin = request.headers.get('Origin');
    const corsHeaders = getCorsHeaders(origin, ALLOWED_ORIGINS);

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: corsHeaders,
      });
    }

    // Only accept POST /ingestion
    const url = new URL(request.url);
    if (request.method !== 'POST' || url.pathname !== '/ingestion') {
      return new Response(
        JSON.stringify({ error: 'Not Found' }),
        {
          status: 404,
          headers: { ...corsHeaders, 'content-type': 'application/json' },
        }
      );
    }

    // Check content length (10MB limit)
    const contentLength = request.headers.get('content-length');
    if (contentLength && parseInt(contentLength, 10) > 10 * 1024 * 1024) {
      return new Response(
        JSON.stringify({ error: 'Payload Too Large' }),
        {
          status: 413,
          headers: { ...corsHeaders, 'content-type': 'application/json' },
        }
      );
    }

    try {
      // Read and parse request body
      const body = await request.text();
      let payload;
      try {
        payload = JSON.parse(body);
      } catch {
        return new Response(
          JSON.stringify({ error: 'Invalid JSON' }),
          {
            status: 400,
            headers: { ...corsHeaders, 'content-type': 'application/json' },
          }
        );
      }

      // Convert legacy batch format to OTLP spans
      const otlpPayload = convertLegacyBatchToOTLP(payload);

      // Build Basic auth header
      const credentials = btoa(`${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}`);
      const authorization = `Basic ${credentials}`;

      // Forward to Langfuse Cloud OTEL endpoint
      const langfuseResponse = await fetch(`${LANGFUSE_HOST}/api/public/otel/v1/traces`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'authorization': authorization,
          'x-langfuse-sdk-name': request.headers.get('x-langfuse-sdk-name') || 'psyclaw-relay',
          'x-langfuse-sdk-version': request.headers.get('x-langfuse-sdk-version') || 'unknown',
          'x-langfuse-ingestion-version': '4',
        },
        body: JSON.stringify(otlpPayload),
      });

      const responseText = await langfuseResponse.text();

      return new Response(responseText, {
        status: langfuseResponse.status,
        headers: {
          ...corsHeaders,
          'content-type': 'application/json',
        },
      });
    } catch (error) {
      console.error('Relay error:', error.message);
      return new Response(
        JSON.stringify({ error: 'Bad Gateway' }),
        {
          status: 502,
          headers: { ...corsHeaders, 'content-type': 'application/json' },
        }
      );
    }
  },
};

function getCorsHeaders(origin, allowedOrigins) {
  const headers = {
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'content-type, x-langfuse-sdk-name, x-langfuse-sdk-version',
  };

  if (allowedOrigins === '*') {
    headers['Access-Control-Allow-Origin'] = '*';
  } else if (origin) {
    const allowed = allowedOrigins.split(',').map((o) => o.trim());
    if (allowed.includes(origin)) {
      headers['Access-Control-Allow-Origin'] = origin;
    }
  }

  return headers;
}

/**
 * Convert legacy Langfuse batch format to OTLP/HTTP JSON format.
 * 
 * Legacy format: { batch: [{ type: "trace-create", body: {...} }, { type: "generation-create", body: {...} }], metadata: {...} }
 * OTLP format: { resourceSpans: [{ scopeSpans: [{ spans: [...] }] }] }
 */
function convertLegacyBatchToOTLP(payload) {
  const batch = payload.batch || [];
  const spans = [];

  // Group events by trace ID to build parent-child relationships
  const traceMap = new Map();
  const generationMap = new Map();

  // First pass: collect trace and generation data
  for (const event of batch) {
    if (event.type === 'trace-create' && event.body) {
      traceMap.set(event.body.id, event.body);
    } else if (event.type === 'generation-create' && event.body) {
      generationMap.set(event.body.id, event.body);
    }
  }

  // Second pass: build OTLP spans
  for (const event of batch) {
    if (event.type === 'generation-create' && event.body) {
      const gen = event.body;
      const trace = traceMap.get(gen.traceId);

      // Convert timestamps to nanoseconds
      const startTimeNanos = dateToNanos(gen.startTime);
      const endTimeNanos = dateToNanos(gen.endTime);

      // Build OTLP span
      const span = {
        traceId: hexToBase64(gen.traceId),
        spanId: hexToBase64(gen.id),
        name: gen.name || 'generation',
        kind: 1, // SPAN_KIND_INTERNAL
        startTimeUnixNano: startTimeNanos,
        endTimeUnixNano: endTimeNanos,
        attributes: [
          { key: 'langfuse.observation.type', value: { stringValue: 'generation' } },
          { key: 'langfuse.observation.id', value: { stringValue: gen.id } },
          { key: 'langfuse.trace.id', value: { stringValue: gen.traceId } },
        ],
      };

      // Add trace-level attributes from trace-create event
      if (trace) {
        if (trace.name) {
          span.attributes.push({ key: 'langfuse.trace.name', value: { stringValue: trace.name } });
        }
        if (trace.sessionId) {
          span.attributes.push({ key: 'langfuse.session.id', value: { stringValue: trace.sessionId } });
        }
        if (trace.userId) {
          span.attributes.push({ key: 'langfuse.user.id', value: { stringValue: trace.userId } });
        }
        if (trace.metadata) {
          for (const [key, value] of Object.entries(trace.metadata)) {
            span.attributes.push({
              key: `langfuse.trace.metadata.${key}`,
              value: { stringValue: String(value) },
            });
          }
        }
      }

      // Add generation-specific attributes
      if (gen.model) {
        span.attributes.push({ key: 'gen_ai.system', value: { stringValue: 'langfuse' } });
        span.attributes.push({ key: 'gen_ai.request.model', value: { stringValue: gen.model } });
      }

      // Add usage details
      if (gen.usageDetails) {
        const usage = gen.usageDetails;
        if (usage.input !== undefined) {
          span.attributes.push({
            key: 'gen_ai.usage.input_tokens',
            value: { intValue: String(usage.input) },
          });
        }
        if (usage.output !== undefined) {
          span.attributes.push({
            key: 'gen_ai.usage.output_tokens',
            value: { intValue: String(usage.output) },
          });
        }
        if (usage.total !== undefined) {
          span.attributes.push({
            key: 'langfuse.usage.total',
            value: { intValue: String(usage.total) },
          });
        }
        if (usage.cache_read !== undefined) {
          span.attributes.push({
            key: 'langfuse.usage.cache_read',
            value: { intValue: String(usage.cache_read) },
          });
        }
        if (usage.cache_write !== undefined) {
          span.attributes.push({
            key: 'langfuse.usage.cache_write',
            value: { intValue: String(usage.cache_write) },
          });
        }
      }

      // Add cost details
      if (gen.costDetails && gen.costDetails.total !== undefined) {
        span.attributes.push({
          key: 'langfuse.usage.cost',
          value: { doubleValue: Number(gen.costDetails.total) },
        });
      }

      // Add level/status
      if (gen.level) {
        span.attributes.push({
          key: 'langfuse.observation.level',
          value: { stringValue: gen.level },
        });
        // Map ERROR level to OTEL status
        if (gen.level === 'ERROR') {
          span.status = { code: 2 }; // STATUS_CODE_ERROR
        }
      }

      // Add status message
      if (gen.statusMessage) {
        span.attributes.push({
          key: 'langfuse.observation.status_message',
          value: { stringValue: gen.statusMessage },
        });
        if (!span.status) {
          span.status = { code: 2, message: gen.statusMessage };
        }
      }

      // Add metadata
      if (gen.metadata) {
        for (const [key, value] of Object.entries(gen.metadata)) {
          span.attributes.push({
            key: `langfuse.observation.metadata.${key}`,
            value: { stringValue: String(value) },
          });
        }
      }

      spans.push(span);
    }
  }

  // Build OTLP payload
  return {
    resourceSpans: [
      {
        resource: {
          attributes: [
            { key: 'service.name', value: { stringValue: 'psyclaw' } },
          ],
        },
        scopeSpans: [
          {
            scope: {
              name: 'psyclaw-relay',
              version: '1.0.0',
            },
            spans: spans,
          },
        ],
      },
    ],
  };
}

/**
 * Convert ISO 8601 timestamp to nanoseconds since Unix epoch
 */
function dateToNanos(dateString) {
  return String(new Date(dateString).getTime() * 1_000_000);
}

/**
 * Convert hex trace/span ID to base64 for OTLP
 */
function hexToBase64(hexString) {
  // Remove any hyphens (UUID format)
  const clean = hexString.replace(/-/g, '');
  
  // Pad to 32 chars (16 bytes) for trace ID or 16 chars (8 bytes) for span ID
  const padded = clean.length === 32 ? clean : clean.padStart(32, '0');
  
  // Convert hex to bytes
  const bytes = [];
  for (let i = 0; i < padded.length; i += 2) {
    bytes.push(parseInt(padded.substr(i, 2), 16));
  }
  
  // Convert to base64
  return btoa(String.fromCharCode.apply(null, bytes));
}
