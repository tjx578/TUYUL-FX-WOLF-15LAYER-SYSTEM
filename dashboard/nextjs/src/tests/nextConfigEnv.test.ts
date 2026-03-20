// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRequire } from "module";
import { fileURLToPath } from "url";
import path from "path";

/**
 * Regression tests for next.config.js env-var validation.
 *
 * The config must:
 *   - Fail fast on protected deployments when critical env vars are missing.
 *   - Warn (not throw) for non-protected production builds with missing API env.
 *   - Resolve the correct apiBase when env vars are provided.
 *   - Fall back to localhost in development when env vars are absent.
 */

const require = createRequire(import.meta.url);
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const CONFIG_PATH = path.resolve(__dirname, "../../next.config.js");

function loadConfig() {
  // Clear the module cache so next.config.js is re-evaluated with fresh env.
  delete require.cache[require.resolve(CONFIG_PATH)];
  return require(CONFIG_PATH);
}

describe("next.config.js env-var validation", () => {
  const originalEnv = { ...process.env };
  const envKeysToClear = new Set([
    "INTERNAL_API_URL",
    "NEXT_PUBLIC_API_BASE_URL",
    "NODE_ENV",
    "VERCEL",
    "VERCEL_ENV",
    "VERCEL_GIT_COMMIT_REF",
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_GIT_BRANCH",
    "GITHUB_REF_NAME",
    "CI_BRANCH",
    "NEXT_CONFIG_FAIL_FAST",
    "NEXT_CONFIG_PROTECTED_ENV",
    "NEXT_PUBLIC_WS_BASE_URL",
    "NEXT_OUTPUT_STANDALONE",
  ]);

  beforeEach(() => {
    // Reset env to a clean baseline before each test.
    process.env = Object.fromEntries(
      Object.entries(process.env).filter(([key]) => !envKeysToClear.has(key)),
    ) as NodeJS.ProcessEnv;
  });

  afterEach(() => {
    // Restore original env.
    process.env = { ...originalEnv };
    vi.restoreAllMocks();
  });

  it("warns but does not throw in non-protected production when API env vars are missing", () => {
    Object.assign(process.env, {
      NODE_ENV: "production",
      VERCEL_GIT_COMMIT_REF: "feature/test-preview",
    });
    const spy = vi.spyOn(console, "error").mockImplementation(() => { });

    expect(() => loadConfig()).not.toThrow();
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining("Missing INTERNAL_API_URL or NEXT_PUBLIC_API_BASE_URL"),
    );
  });

  it("throws in protected production when API env vars are missing", () => {
    Object.assign(process.env, {
      NODE_ENV: "production",
      VERCEL_GIT_COMMIT_REF: "main",
    });

    expect(() => loadConfig()).toThrow(
      /Missing INTERNAL_API_URL or NEXT_PUBLIC_API_BASE_URL/,
    );
  });

  it("throws in protected production when NEXT_PUBLIC_WS_BASE_URL is missing", () => {
    Object.assign(process.env, {
      NODE_ENV: "production",
      VERCEL_GIT_COMMIT_REF: "main",
      INTERNAL_API_URL: "https://wolf15-api-production.up.railway.app",
    });

    expect(() => loadConfig()).toThrow(/Missing NEXT_PUBLIC_WS_BASE_URL/);
  });

  it("throws when NEXT_PUBLIC_WS_BASE_URL points to Vercel domain", () => {
    Object.assign(process.env, {
      NODE_ENV: "production",
      VERCEL_GIT_COMMIT_REF: "main",
      INTERNAL_API_URL: "https://wolf15-api-production.up.railway.app",
      NEXT_PUBLIC_WS_BASE_URL: "wss://project.vercel.app",
    });

    expect(() => loadConfig()).toThrow(/not Vercel domain/);
  });

  it("does not warn when INTERNAL_API_URL is set in production", () => {
    Object.assign(process.env, {
      NODE_ENV: "production",
      NEXT_PUBLIC_WS_BASE_URL: "wss://api.example.railway.app",
      INTERNAL_API_URL: "https://api.example.com",
    });
    const spy = vi.spyOn(console, "error").mockImplementation(() => { });

    const config = loadConfig();
    expect(spy).not.toHaveBeenCalled();
    expect(config).toBeDefined();
  });

  it("does not warn when NEXT_PUBLIC_API_BASE_URL is set in production", () => {
    Object.assign(process.env, {
      NODE_ENV: "production",
      NEXT_PUBLIC_WS_BASE_URL: "wss://api.example.railway.app",
      NEXT_PUBLIC_API_BASE_URL: "https://api.example.com",
    });
    const spy = vi.spyOn(console, "error").mockImplementation(() => { });

    const config = loadConfig();
    expect(spy).not.toHaveBeenCalled();
    expect(config).toBeDefined();
  });

  it("falls back to localhost in development without env vars", () => {
    Object.assign(process.env, { NODE_ENV: "development" });
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => { });

    const config = loadConfig();
    // Trigger rewrites to capture the logged apiBase
    config.rewrites();
    expect(logSpy).toHaveBeenCalledWith(
      "[next.config] rewrites apiBase =",
      "http://localhost:8000",
    );
  });

  it("strips trailing slash and /api suffix from provided URL", () => {
    Object.assign(process.env, {
      NODE_ENV: "production",
      NEXT_PUBLIC_WS_BASE_URL: "wss://api.example.railway.app",
      INTERNAL_API_URL: "https://api.example.com/api/",
    });
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => { });

    const config = loadConfig();
    config.rewrites();
    expect(logSpy).toHaveBeenCalledWith(
      "[next.config] rewrites apiBase =",
      "https://api.example.com",
    );
  });
});
