import { cpSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(root, "apps", "panel", "index.html");
const target = join(root, "dist", "apps", "panel", "index.html");

mkdirSync(dirname(target), { recursive: true });
cpSync(source, target);
console.log(`copied panel asset -> ${target}`);
