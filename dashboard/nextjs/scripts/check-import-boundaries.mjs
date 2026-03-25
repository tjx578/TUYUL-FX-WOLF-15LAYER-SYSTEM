#!/usr/bin/env node

/**
 * check-import-boundaries.mjs
 * ────────────────────────────
 * Enforces CUTOVER-PHASE-9 import boundary rules.
 *
 * Rules:
 *   1. Route pages in (control) may only import from features
 *   2. features must not import from app
 *   3. shared must not import from app or features
 *   4. widgets must not import from features domain hooks/api
 *
 * Usage:
 *   node scripts/check-import-boundaries.mjs
 *   Returns exit code 1 if violations found.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

const SRC = join(import.meta.dirname, "..", "src");
const IMPORT_RE = /(?:import|from)\s+["'](@\/[^"']+)["']/g;

/** Collect all .ts/.tsx files under a directory */
function walk(dir, files = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, files);
    } else if (/\.tsx?$/.test(entry)) {
      files.push(full);
    }
  }
  return files;
}

/** Extract @/... imports from a file */
function extractImports(filePath) {
  const content = readFileSync(filePath, "utf-8");
  const imports = [];
  let match;
  while ((match = IMPORT_RE.exec(content)) !== null) {
    imports.push({ path: match[1], line: content.slice(0, match.index).split("\n").length });
  }
  return imports;
}

/** Normalize path separators for comparison */
function relPath(filePath) {
  return relative(SRC, filePath).split(sep).join("/");
}

// ── Violations collector ──────────────────────────────────────

const violations = [];

function violation(file, line, rule, importPath) {
  violations.push({ file: relPath(file), line, rule, importPath });
}

// ── Rule 1: Route pages must be thin ──────────────────────────

const controlPages = walk(join(SRC, "app", "(control)")).filter(
  (f) => f.endsWith("page.tsx") && !relPath(f).endsWith("(control)/page.tsx"),
);

for (const file of controlPages) {
  for (const imp of extractImports(file)) {
    if (imp.path.startsWith("@/features/")) continue; // allowed
    violation(file, imp.line, "ROUTE_THIN", imp.path);
  }
}

// ── Rule 2: Features must not import from app/ ────────────────

const featureDir = join(SRC, "features");
try {
  const featureFiles = walk(featureDir);
  for (const file of featureFiles) {
    for (const imp of extractImports(file)) {
      if (imp.path.startsWith("@/app/") || imp.path === "@/app") {
        violation(file, imp.line, "FEATURE_NO_ROUTE", imp.path);
      }
    }
  }
} catch { /* features/ may not exist yet */ }

// ── Rule 3: Shared must be neutral ────────────────────────────

const sharedDir = join(SRC, "shared");
try {
  const sharedFiles = walk(sharedDir);
  for (const file of sharedFiles) {
    for (const imp of extractImports(file)) {
      if (imp.path.startsWith("@/app/") || imp.path.startsWith("@/features/")) {
        violation(file, imp.line, "SHARED_NEUTRAL", imp.path);
      }
    }
  }
} catch { /* shared/ may not exist yet */ }

// ── Rule 4: Widgets must not hold domain logic ────────────────

const widgetsDir = join(SRC, "widgets");
try {
  const widgetFiles = walk(widgetsDir);
  for (const file of widgetFiles) {
    for (const imp of extractImports(file)) {
      if (
        imp.path.match(/^@\/features\/.*\/(hooks|api)\//) ||
        imp.path.match(/^@\/features\/.*\/model\//)
      ) {
        violation(file, imp.line, "WIDGET_NO_DOMAIN", imp.path);
      }
    }
  }
} catch { /* widgets/ may not exist yet */ }

// ── Report ────────────────────────────────────────────────────

if (violations.length === 0) {
  console.log("✓ No import boundary violations found.");
  process.exit(0);
} else {
  console.error(`\n✗ ${violations.length} import boundary violation(s):\n`);
  for (const v of violations) {
    console.error(`  ${v.rule} │ ${v.file}:${v.line} → ${v.importPath}`);
  }
  console.error(`\nSee src/ARCHITECTURE_MANIFEST.md for rules.\n`);
  process.exit(1);
}
