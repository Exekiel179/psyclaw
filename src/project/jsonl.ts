import { appendFile, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { basename, dirname, join } from "node:path";
import { randomUUID } from "node:crypto";

const writeQueues = new Map<string, Promise<unknown>>();

/**
 * Serialize all mutations for one JSONL path in this process. A rejected
 * operation must not poison later writes, so the next operation starts after
 * the previous one settles.
 */
function enqueue<T>(path: string, operation: () => Promise<T>): Promise<T> {
  const previous = writeQueues.get(path) ?? Promise.resolve();
  const next = previous.catch(() => undefined).then(operation);
  writeQueues.set(path, next);
  void next.finally(() => {
    if (writeQueues.get(path) === next) writeQueues.delete(path);
  }).catch(() => undefined);
  return next;
}

export async function appendJsonl<T>(path: string, value: T): Promise<void> {
  await enqueue(path, async () => {
    await mkdir(dirname(path), { recursive: true });
    await appendFile(path, `${JSON.stringify(value)}\n`, "utf8");
  });
}

/**
 * Check for an existing logical record and append only when its key is new.
 * The read and append happen inside the same per-path queue, making this
 * operation safe for concurrent callers in the current process.
 */
export async function appendJsonlIfMissing<T>(
  path: string,
  value: T,
  key: (value: T) => string,
): Promise<{ appended: boolean }> {
  return enqueue(path, async () => {
    const existing = await readJsonl<T>(path);
    const wanted = key(value);
    if (existing.some((item) => key(item) === wanted)) return { appended: false };
    await mkdir(dirname(path), { recursive: true });
    await appendFile(path, `${JSON.stringify(value)}\n`, "utf8");
    return { appended: true };
  });
}

/**
 * Replace a file through a same-directory temporary file and rename. Keeping
 * the temporary file beside the destination preserves rename atomicity on
 * filesystems that support it and avoids partially written JSON/Markdown.
 */
export async function atomicWriteFile(path: string, contents: string): Promise<void> {
  const directory = dirname(path);
  await mkdir(directory, { recursive: true });
  const temporary = join(directory, `.${basename(path)}.${randomUUID()}.tmp`);
  try {
    await writeFile(temporary, contents, { encoding: "utf8", flag: "wx" });
    try {
      await rename(temporary, path);
    } catch (error) {
      // Windows may reject replacing an existing file with rename. Remove
      // only the exact destination, then complete the same-directory move.
      const code = (error as NodeJS.ErrnoException).code;
      if (code !== "EEXIST" && code !== "EPERM" && code !== "EACCES") throw error;
      await rm(path, { force: true });
      await rename(temporary, path);
    }
  } finally {
    await rm(temporary, { force: true }).catch(() => undefined);
  }
}

export async function readJsonl<T>(path: string): Promise<T[]> {
  let text: string;
  try {
    text = await readFile(path, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
  const rows: T[] = [];
  for (const [index, line] of text.split(/\r?\n/).entries()) {
    if (!line.trim()) continue;
    try {
      rows.push(JSON.parse(line) as T);
    } catch {
      throw new Error(`Invalid JSONL at ${path}:${index + 1}`);
    }
  }
  return rows;
}
