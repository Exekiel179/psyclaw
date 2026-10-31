/**
 * Cloudflare Worker for PsyClaw Langfuse relay.
 *
 * Receives Langfuse ingestion payloads from production clients and forwards
 * them to Langfuse Cloud with authentication. This avoids embedding
 * LANGFUSE_SECRET_KEY in release binaries.
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

      // Build Basic auth header
      const credentials = btoa(`${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}`);
      const authorization = `Basic ${credentials}`;

      // Forward to Langfuse Cloud
      const langfuseResponse = await fetch(`${LANGFUSE_HOST}/api/public/ingestion`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'authorization': authorization,
          'x-langfuse-sdk-name': request.headers.get('x-langfuse-sdk-name') || 'psyclaw-relay',
          'x-langfuse-sdk-version': request.headers.get('x-langfuse-sdk-version') || 'unknown',
        },
        body: JSON.stringify(payload),
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
