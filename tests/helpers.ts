import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import { createPanelServer } from "../src/panel/server.js";

/** Boot an in-process panel server on an ephemeral port and run the probe. */
export async function withServer(root: string, fn: (base: string) => Promise<void>): Promise<void> {
  const htmlPath = join(root, "panel.html");
  await writeFile(htmlPath, "<!DOCTYPE html><title>panel</title>", "utf8");
  const server = createPanelServer(root, { panelHtmlPath: htmlPath });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  try {
    await fn(`http://127.0.0.1:${port}`);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

/** POST JSON helper for panel endpoints. */
export const postJson = (base: string, path: string, body: unknown) =>
  fetch(`${base}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
