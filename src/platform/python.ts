import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export interface PythonInvocation {
  /** Executable name or path (e.g. `python3`, `py`, `python`). */
  command: string;
  /** Args that must precede the script or `-c` payload (e.g. `["-3"]` for the Windows launcher). */
  prefixArgs: string[];
}

const CANDIDATES: readonly PythonInvocation[] = [
  { command: "python3", prefixArgs: [] },
  { command: "py", prefixArgs: ["-3"] },
  { command: "python", prefixArgs: [] },
];

let cached: PythonInvocation | undefined | null = null;

export function resetPythonCache(): void {
  cached = null;
}

export function pythonCandidates(): readonly PythonInvocation[] {
  return CANDIDATES;
}

async function probe(candidate: PythonInvocation): Promise<boolean> {
  try {
    await execFileAsync(candidate.command, [...candidate.prefixArgs, "--version"], {
      timeout: 3000,
      windowsHide: true,
    });
    return true;
  } catch {
    return false;
  }
}

/** Resolve a usable Python 3 interpreter once per process. */
export async function resolvePython(): Promise<PythonInvocation | undefined> {
  if (cached !== null) return cached ?? undefined;
  for (const candidate of CANDIDATES) {
    if (await probe(candidate)) {
      cached = candidate;
      return candidate;
    }
  }
  cached = undefined;
  return undefined;
}

export async function requirePython(): Promise<PythonInvocation> {
  const python = await resolvePython();
  if (!python) {
    throw new Error("Python 3 is required (tried python3, py -3, python). Install Python 3 and retry.");
  }
  return python;
}

export type ExecPythonOptions = {
  cwd?: string;
  timeout?: number;
  maxBuffer?: number;
  encoding?: BufferEncoding;
};

/** Run `python <prefix> ...args` with the resolved interpreter. */
export async function execPython(
  args: readonly string[],
  options: ExecPythonOptions = {},
): Promise<{ stdout: string; stderr: string }> {
  const python = await requirePython();
  const result = await execFileAsync(python.command, [...python.prefixArgs, ...args], {
    cwd: options.cwd,
    timeout: options.timeout ?? 60_000,
    maxBuffer: options.maxBuffer ?? 2 * 1024 * 1024,
    encoding: options.encoding ?? "utf8",
    windowsHide: true,
  });
  return {
    stdout: typeof result.stdout === "string" ? result.stdout : String(result.stdout),
    stderr: typeof result.stderr === "string" ? result.stderr : String(result.stderr),
  };
}
