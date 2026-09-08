#!/usr/bin/env node

const WARN_ONLY = process.argv.includes("--warn");
const errors = [];
const warnings = [];

function value(name) {
  return (process.env[name] || "").trim();
}

function requireOrigin(name, purpose) {
  const raw = value(name);
  if (!raw) {
    errors.push(name + " is required for " + purpose + ".");
    return;
  }

  try {
    const parsed = new URL(raw);
    const cleanPath = !parsed.pathname || parsed.pathname === "/";
    if (
      !["http:", "https:"].includes(parsed.protocol) ||
      parsed.username ||
      parsed.password ||
      !cleanPath ||
      parsed.search ||
      parsed.hash
    ) {
      errors.push(name + " must be a credential-free HTTP(S) origin with no path.");
    }
  } catch {
    errors.push(name + " must be a valid HTTP(S) origin.");
  }
}

const mode = value("DASHBOARD_MODE").toLowerCase();
if (mode !== "viewer") {
  errors.push('DASHBOARD_MODE must be exactly "viewer".');
}

requireOrigin("DASHBOARD_CANONICAL_ORIGIN", "owner-login browser origin");
try {
  const raw = process.env.DASHBOARD_CANONICAL_ORIGIN || "";
  const parsed = new URL(raw);
  if (raw !== raw.trim() || raw.length > 512 || /[\\\s,%?#]/.test(raw) ||
      !/^https?:\/\/[^/]+\/?$/i.test(raw) || parsed.hostname.includes("*") ||
      ["0.0.0.0", "[::]"].includes(parsed.hostname) ||
      (parsed.protocol === "http:" && !["127.0.0.1", "localhost", "[::1]"].includes(parsed.hostname))) {
    errors.push("DASHBOARD_CANONICAL_ORIGIN must be one HTTPS browser origin (HTTP is loopback-only), never a wildcard or bind address.");
  }
} catch { /* requireOrigin already records a missing or malformed URL. */ }
requireOrigin("INTERNAL_API_URL", "server-side JWT validation");
requireOrigin(
  "INTERNAL_DASHBOARD_BFF_URL",
  "the three read-only dashboard projections",
);

if (value("API_KEY") || value("DASHBOARD_API_KEY")) {
  warnings.push(
    "A machine API-key variable is present. The viewer service does not use it and it should be removed.",
  );
}

if (warnings.length) {
  console.warn("\nDeploy env warnings:\n");
  warnings.forEach((warning, index) => {
    console.warn("  " + (index + 1) + ". " + warning + "\n");
  });
}

if (errors.length) {
  console.error("\nDeploy env errors:\n");
  errors.forEach((error, index) => {
    console.error("  " + (index + 1) + ". " + error + "\n");
  });

  if (!WARN_ONLY) process.exit(1);
  console.warn("  --warn mode: continuing despite errors.\n");
} else {
  console.log("Viewer deployment environment is valid.");
}
