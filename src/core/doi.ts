/**
 * DOI utilities: real cross-source verification (Crossref + OpenAlex) and
 * open-access PDF lookup. Moved out of the panel server so the reference
 * archive and any other caller can use them without a server dependency.
 */

export interface DoiVerification {
  schemaVersion: "psyclaw/doi-verify/v1";
  doi: string;
  status: "verified" | "unverified" | "error";
  crossref?: { title?: string; authors?: string[]; year?: number; container?: string };
  openalex?: { title?: string; citedBy?: number };
  mismatch?: string;
  error?: string;
  verifiedAt: string;
}

export interface OpenAlexOaLookup {
  doi: string;
  oaPdfUrl: string | null;
  isOa: boolean;
  queriedAt: string;
}

/**
 * Real cross-source DOI verification via Crossref + OpenAlex. Never fabricates
 * a "verified" status: any network failure returns `error`.
 */
export async function verifyDoi(doi: string, fetchFn: typeof fetch = fetch): Promise<DoiVerification> {
  const normalized = doi.trim();
  const verifiedAt = new Date().toISOString();
  if (!/^10\.\d{4,9}\/\S+$/i.test(normalized)) {
    return { schemaVersion: "psyclaw/doi-verify/v1", doi: normalized, status: "error", error: "不是合法 DOI（应为 10.xxxx/…）", verifiedAt };
  }
  try {
    const [crossrefRes, openalexRes] = await Promise.all([
      fetchFn(`https://api.crossref.org/works/${encodeURIComponent(normalized)}`, { signal: AbortSignal.timeout(12_000) }),
      fetchFn(`https://api.openalex.org/works/doi:${encodeURIComponent(normalized)}`, { signal: AbortSignal.timeout(12_000) }),
    ]);
    const crossref = crossrefRes.ok
      ? await crossrefRes.json() as { message?: { title?: string[]; author?: Array<{ family?: string; given?: string }>; issued?: { "date-parts"?: number[][] }; "container-title"?: string[] } }
      : undefined;
    const openalex = openalexRes.ok
      ? await openalexRes.json() as { title?: string; cited_by_count?: number }
      : undefined;
    const crossTitle = crossref?.message?.title?.[0];
    const openalexTitle = openalex?.title;
    const mismatch = crossTitle && openalexTitle && crossTitle.toLowerCase() !== openalexTitle.toLowerCase()
      ? `Crossref 与 OpenAlex 标题不一致：「${crossTitle}」vs「${openalexTitle}」`
      : undefined;
    const found = Boolean(crossref || openalex);
    return {
      schemaVersion: "psyclaw/doi-verify/v1",
      doi: normalized,
      status: found && !mismatch ? "verified" : mismatch ? "unverified" : "error",
      ...(crossref?.message ? {
        crossref: {
          ...(crossref.message.title?.[0] === undefined ? {} : { title: crossref.message.title[0] }),
          ...(crossref.message.author && crossref.message.author.length > 0
            ? { authors: crossref.message.author.slice(0, 10).map((author) => [author.given, author.family].filter(Boolean).join(" ")).filter(Boolean) }
            : {}),
          ...(crossref.message.issued?.["date-parts"]?.[0]?.[0] === undefined ? {} : { year: crossref.message.issued["date-parts"][0][0] }),
          ...(crossref.message["container-title"]?.[0] === undefined ? {} : { container: crossref.message["container-title"][0] }),
        },
      } : {}),
      ...(openalex ? { openalex: { ...(openalex.title === undefined ? {} : { title: openalex.title }), ...(openalex.cited_by_count === undefined ? {} : { citedBy: openalex.cited_by_count }) } } : {}),
      ...(mismatch ? { mismatch } : {}),
      ...(found ? {} : { error: "Crossref 与 OpenAlex 均未检索到该 DOI" }),
      verifiedAt,
    };
  } catch (error) {
    return { schemaVersion: "psyclaw/doi-verify/v1", doi: normalized, status: "error", error: error instanceof Error ? error.message : String(error), verifiedAt };
  }
}

/**
 * Look up an open-access PDF URL for a DOI via OpenAlex
 * (`open_access.oa_url` / `best_oa_location.pdf_url`). Returns null when the
 * work is not open access or the lookup fails; the caller must still verify
 * the returned URL before downloading it.
 */
export async function lookupOaPdfUrl(doi: string, fetchFn: typeof fetch = fetch): Promise<OpenAlexOaLookup> {
  const normalized = doi.trim();
  const queriedAt = new Date().toISOString();
  if (!/^10\.\d{4,9}\/\S+$/i.test(normalized)) {
    return { doi: normalized, oaPdfUrl: null, isOa: false, queriedAt };
  }
  try {
    const response = await fetchFn(`https://api.openalex.org/works/doi:${encodeURIComponent(normalized)}`, { signal: AbortSignal.timeout(12_000) });
    if (!response.ok) return { doi: normalized, oaPdfUrl: null, isOa: false, queriedAt };
    const body = await response.json() as {
      open_access?: { is_oa?: boolean; oa_url?: string | null };
      best_oa_location?: { pdf_url?: string | null };
    };
    const isOa = Boolean(body.open_access?.is_oa || body.best_oa_location?.pdf_url);
    const oaPdfUrl = body.best_oa_location?.pdf_url ?? body.open_access?.oa_url ?? null;
    return { doi: normalized, oaPdfUrl: isOa ? oaPdfUrl : null, isOa, queriedAt };
  } catch {
    return { doi: normalized, oaPdfUrl: null, isOa: false, queriedAt };
  }
}
