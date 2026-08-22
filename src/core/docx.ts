import { spawn } from "node:child_process";

/**
 * Word document conversion via Pandoc. Pandoc is already part of psyclaw's DOCX
 * export path; if it is unavailable, the caller should fall back to the
 * markitdown skill (read) or report the failure (write).
 */
function runPandoc(args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn("pandoc", args, {
      stdio: ["ignore", "pipe", "pipe"],
      shell: process.platform === "win32",
    });
    let output = "";
    let errorText = "";
    child.stdout?.on("data", (chunk) => { output += String(chunk); });
    child.stderr?.on("data", (chunk) => { errorText += String(chunk); });
    child.on("error", (error) => reject(new Error(`pandoc unavailable (${error.message}); install Pandoc or use the markitdown skill`)));
    child.on("close", (code) => {
      if (code === 0) resolve(output);
      else reject(new Error(`pandoc failed (exit ${code ?? "unknown"})${errorText ? `: ${errorText.trim().slice(0, 300)}` : ""}`));
    });
  });
}

/** Plain text (whitespace-unwrapped) for evidence reading. */
export function docxToText(path: string): Promise<string> {
  return runPandoc([path, "-t", "plain", "--wrap=none"]);
}

/** Markdown (structure preserved) for citation-audit and quoting. */
export function docxToMarkdown(path: string): Promise<string> {
  return runPandoc([path, "-t", "markdown", "--wrap=none"]);
}

/**
 * Export a Markdown file to DOCX (the convention target is
 * `paper/<name>_APA7.docx`). An optional reference document (e.g. a black and
 * white APA-7 template) is passed through `--reference-doc` so heading/table
 * styling follows the project template instead of pandoc defaults.
 */
export async function markdownToDocx(markdownPath: string, outputPath: string, referenceDoc?: string): Promise<void> {
  const args = [markdownPath, "-o", outputPath, "--wrap=none"];
  if (referenceDoc) args.push("--reference-doc", referenceDoc);
  await runPandoc(args);
}
