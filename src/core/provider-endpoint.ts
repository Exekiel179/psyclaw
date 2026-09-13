/** Shared http(s) provider endpoint rules for catalog, setup, and panel saves. */

export function normalizeEndpoint(value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("Provider endpoint must be a valid URL");
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new Error("Provider endpoint must use http or https");
  }
  if (url.username || url.password || url.hash) {
    throw new Error("Provider endpoint must not contain credentials or a fragment");
  }
  return url.toString().replace(/\/$/, "");
}

/** Empty submitted URL falls back to the preset/catalog endpoint. */
export function resolveProviderBaseUrl(submitted: unknown, fallback = ""): string {
  const value = (typeof submitted === "string" ? submitted.trim() : "") || fallback.trim();
  return value ? normalizeEndpoint(value) : "";
}
