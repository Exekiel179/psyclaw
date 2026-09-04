/**
 * Global test-environment setup.
 *
 * On macOS the default temp dir lives under /var/folders, and /var is a
 * symlink to /private/var. Security guards in psyclaw reject fixtures whose
 * ancestor chain contains symlinks (they realpath-compare walked paths), so
 * fixtures built on the raw default temp dir false-positive as
 * "symlink-path" / "path-invalid". Point TMPDIR at a canonical (realpath'd)
 * temp dir before any fixture is created so realpath comparisons match,
 * mirroring a plain Linux CI layout. Symlinks created *inside* fixtures by the
 * tests themselves are unaffected and still trigger the guards.
 */
import { mkdtempSync, realpathSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const canonicalBase = realpathSync(tmpdir());
const canonicalTmp = mkdtempSync(join(canonicalBase, "psyclaw-test-tmp-"));

process.env.TMPDIR = canonicalTmp;
process.env.TMP = canonicalTmp;
process.env.TEMP = canonicalTmp;
