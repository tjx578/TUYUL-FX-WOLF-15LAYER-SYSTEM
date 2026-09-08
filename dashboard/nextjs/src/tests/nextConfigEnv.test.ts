// @vitest-environment node
import { createRequire } from "node:module";
import { afterEach, describe, expect, it, vi } from "vitest";
const require = createRequire(import.meta.url);
const configPath = require.resolve("../../next.config.js");
function config() { delete require.cache[configPath]; return require(configPath); }
afterEach(() => vi.unstubAllEnvs());
describe("Railway-only server configuration", () => {
  it("requires the server API in production without a public fallback", () => {
    vi.stubEnv("NODE_ENV", "production"); vi.stubEnv("INTERNAL_API_URL", "");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://public.invalid");
    expect(config).toThrow("INTERNAL_API_URL is required");
  });
  it.each(["http://api.invalid", "https://user:password@api.invalid", "https://api.invalid/path", "https://api.invalid?x=1", "https://api.invalid/#x"])("rejects unsafe production origin %s", (url) => {
    vi.stubEnv("NODE_ENV", "production"); vi.stubEnv("INTERNAL_API_URL", url);
    expect(config).toThrow();
  });
  it("produces standalone output without exposing server origin or credentials", () => {
    vi.stubEnv("NODE_ENV", "production"); vi.stubEnv("INTERNAL_API_URL", "https://core-only.invalid");
    vi.stubEnv("API_KEY", "synthetic-machine-value");
    const result = config();
    expect(result.output).toBe("standalone"); expect(result.env).toBeUndefined();
    expect(JSON.stringify(result)).not.toContain("core-only.invalid");
    expect(JSON.stringify(result)).not.toContain("synthetic-machine-value");
    expect(result.typescript.ignoreBuildErrors).toBe(false);
  });
  it("limits browser connections to same origin", async () => {
    vi.stubEnv("NODE_ENV", "production"); vi.stubEnv("INTERNAL_API_URL", "https://core.invalid");
    const headers = (await config().headers())[0].headers;
    const csp = headers.find((h: {key: string}) => h.key === "Content-Security-Policy").value;
    expect(csp.split("; ")).toContain("connect-src 'self'");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).not.toMatch(/vercel|railway\.app|core\.invalid/);
  });
});
