#!/usr/bin/env node

/**
 * Langfuse relay server for PsyClaw production clients.
 *
 * Receives Langfuse ingestion payloads from production clients and forwards
 * them to Langfuse Cloud with proper authentication. This avoids embedding
 * LANGFUSE_SECRET_KEY in release binaries.
 *
 * Required environment variables:
 *   LANGFUSE_PUBLIC_KEY - Langfuse project public key
 *   LANGFUSE_SECRET_KEY - Langfuse project secret key
 *
 * Optional environment variables:
 *   LANGFUSE_HOST - Langfuse host (default: https://cloud.langfuse.com)
 *   PORT - Server port (default: 3000)
 *   ALLOWED_ORIGINS - Comma-separated allowed origins for CORS (default: *)
 *
 * Usage:
 *   node server.mjs
 *   # or with environment variables:
 *   LANGFUSE_PUBLIC_KEY=pk_xxx LANGFUSE_SECRET_KEY=sk_xxx PORT=8080 node server.mjs
 *
 * Deploy:
 *   - Node.js server: Run with process manager (PM2, systemd, etc.)
 *   - Docker: FROM node:22-alpine; COPY server.mjs /app/; CMD ["node", "/app/server.mjs"]
 *   - Cloudflare Workers: Convert to Worker format (see workers/ directory)
 */

import { createServer } from "node:http";

const LANGFUSE_PUBLIC_KEY = process.env.LANGFUSE_PUBLIC_KEY?.trim();
const LANGFUSE_SECRET_KEY = process.env.LANGFUSE_SECRET_KEY?.trim();
const LANGFUSE_HOST = (process.env.LANGFUSE_HOST?.trim() || "https://cloud.langfuse.com").replace(/\/+$/, "");
const PORT = parseInt(process.env.PORT || "3000", 10);
const ALLOWED_ORIGINS = process.env.ALLOWED_ORIGINS?.trim() || "*";

if (!LANGFUSE_PUBLIC_KEY || !LANGFUSE_SECRET_KEY) {
  console.error("ERROR: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required");
  process.exit(1);
}

const authorization = `Basic ${Buffer.from(`${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}`).toString("base64")}`;

function cors(res, origin) {
  if (ALLOWED_ORIGINS === "*") {
    res.setHeader("Access-Control-Allow-Origin", "*");
  } else if (origin) {
    const allowed = ALLOWED_ORIGINS.split(",").map((o) => o.trim());
    if (allowed.includes(origin)) {
      res.setHeader("Access-Control-Allow-Origin", origin);
    }
  }
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "content-type, x-langfuse-sdk-name, x-langfuse-sdk-version");
}

const server = createServer(async (req, res) => {
  const origin = req.headers.origin;

  if (req.method === "OPTIONS") {
    cors(res, origin);
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.method !== "POST" || req.url !== "/ingestion") {
    cors(res, origin);
    res.writeHead(404, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "Not Found" }));
    return;
  }

  let body = "";
  for await (const chunk of req) {
    body += chunk;
    if (body.length > 10 * 1024 * 1024) {
      cors(res, origin);
      res.writeHead(413, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "Payload Too Large" }));
      return;
    }
  }

  let payload;
  try {
    payload = JSON.parse(body);
  } catch {
    cors(res, origin);
    res.writeHead(400, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "Invalid JSON" }));
    return;
  }

  const headers = {
    "content-type": "application/json",
    authorization,
    "x-langfuse-sdk-name": req.headers["x-langfuse-sdk-name"] || "psyclaw-relay",
    "x-langfuse-sdk-version": req.headers["x-langfuse-sdk-version"] || "unknown",
  };

  try {
    const response = await fetch(`${LANGFUSE_HOST}/api/public/ingestion`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });

    cors(res, origin);
    res.writeHead(response.status, { "content-type": "application/json" });

    const text = await response.text();
    res.end(text);
  } catch (error) {
    console.error("Relay error:", error.message);
    cors(res, origin);
    res.writeHead(502, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "Bad Gateway" }));
  }
});

server.listen(PORT, () => {
  console.log(`Langfuse relay listening on port ${PORT}`);
  console.log(`Forwarding to: ${LANGFUSE_HOST}/api/public/ingestion`);
  console.log(`Allowed origins: ${ALLOWED_ORIGINS}`);
});
