// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRequire } from "module";
import { fileURLToPath } from "url";
import path from "path";

/**
 * Regression tests for next.config.js env-var validation.
 *
 * The config must:
 *   - Warn (not throw) when INTERNAL_API_URL / NEXT_PUBLIC_API_BASE_URL are
 *     missing in production.
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

  beforeEach(() => {
    // Reset env to a clean baseline before each test.
    delete process.env.INTERNAL_API_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    delete process.env.NODE_ENV;
    delete process.env.VERCEL;
    delete process.env.NEXT_OUTPUT_STANDALONE;
  });

  afterEach(() => {
    // Restore original env.
    process.env = { ...originalEnv };
    vi.restoreAllMocks();
  });

  it("does not throw in production when env vars are missing", () => {
    process.env.NODE_ENV = "production";
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => loadConfig()).not.toThrow();
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining("Missing INTERNAL_API_URL or NEXT_PUBLIC_API_BASE_URL"),
    );
  });

  it("does not warn when INTERNAL_API_URL is set in production", () => {
    process.env.NODE_ENV = "production";
    process.env.INTERNAL_API_URL = "https://api.example.com";
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    const config = loadConfig();
    expect(spy).not.toHaveBeenCalled();
    expect(config).toBeDefined();
  });

  it("does not warn when NEXT_PUBLIC_API_BASE_URL is set in production", () => {
    process.env.NODE_ENV = "production";
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.example.com";
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    const config = loadConfig();
    expect(spy).not.toHaveBeenCalled();
    expect(config).toBeDefined();
  });

  it("falls back to localhost in development without env vars", () => {
    process.env.NODE_ENV = "development";
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const config = loadConfig();
    // Trigger rewrites to capture the logged apiBase
    config.rewrites();
    expect(logSpy).toHaveBeenCalledWith(
      "[next.config] rewrites apiBase =",
      "http://localhost:8000",
    );
  });

  it("strips trailing slash and /api suffix from provided URL", () => {
    process.env.NODE_ENV = "production";
    process.env.INTERNAL_API_URL = "https://api.example.com/api/";
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const config = loadConfig();
    config.rewrites();
    expect(logSpy).toHaveBeenCalledWith(
      "[next.config] rewrites apiBase =",
      "https://api.example.com",
    );
  });
});
