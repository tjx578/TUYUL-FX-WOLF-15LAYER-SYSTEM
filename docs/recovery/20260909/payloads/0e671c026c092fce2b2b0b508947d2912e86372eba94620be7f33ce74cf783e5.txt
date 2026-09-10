/**
 * Copies all source files from dashboard/nextjs/src/ into the root src/,
 * rewriting path aliases (@/) as needed.  Files already written by previous
 * steps (tokens.css, primitives.css, globals.css, layout.tsx, ClientOnly.tsx)
 * are SKIPPED so we don't clobber in-progress edits.
 *
 * Run with:  node scripts/migrate-src.mjs
 */

import fs from "fs";
import path from "path";

const SOURCE = path.resolve("dashboard/nextjs/src");
const DEST   = path.resolve("src");

// Files we already hand-crafted — keep them untouched.
const SKIP = new Set([
  "app/globals.css",
  "app/layout.tsx",
  "shared/styles/tokens.css",
  "shared/styles/primitives.css",
  "components/ClientOnly.tsx",
]);

let copied = 0;
let skipped = 0;

function walk(dir, relBase = "") {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const relPath = relBase ? `${relBase}/${entry.name}` : entry.name;
    const srcFull  = path.join(dir, entry.name);
    const destFull = path.join(DEST, relPath);

    if (entry.isDirectory()) {
      walk(srcFull, relPath);
    } else {
      if (SKIP.has(relPath)) {
        skipped++;
        continue;
      }
      // Ensure parent directories exist
      fs.mkdirSync(path.dirname(destFull), { recursive: true });
      fs.copyFileSync(srcFull, destFull);
      copied++;
    }
  }
}

walk(SOURCE);

console.log(`[migrate-src] Done — ${copied} files copied, ${skipped} files skipped (already hand-crafted).`);
console.log(`[migrate-src] Destination: ${DEST}`);
