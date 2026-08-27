import { cpSync, existsSync, mkdirSync, rmSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(root, "apps", "panel", "index.html");
const target = join(root, "dist", "apps", "panel", "index.html");
const inheritedIgnore = join(root, "dist", ".gitignore");

// A legacy Python distribution left a catch-all ignore file in dist/. npm
// applies nested ignore rules while packing, which otherwise strips the built
// CLI from the published package.
if (existsSync(inheritedIgnore)) rmSync(inheritedIgnore);
if (!existsSync(source) || !statSync(source).isFile() || statSync(source).size === 0) {
  throw new Error(`panel asset is missing or empty: ${source}`);
}
mkdirSync(dirname(target), { recursive: true });
cpSync(source, target);
if (statSync(target).size === 0) throw new Error(`copied panel asset is empty: ${target}`);
console.log(`copied panel asset -> ${target}`);
