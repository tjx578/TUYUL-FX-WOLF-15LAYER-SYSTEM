// @vitest-environment node
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = path.resolve(__dirname, "../..");
const dockerfile = readFileSync(path.join(root, "Dockerfile"), "utf8");
const builder = dockerfile.split("AS builder")[1].split("AS runner")[0];
const args = Object.fromEntries(
  [...builder.matchAll(/^ARG (\w+)=(.*)$/gm)].map((match) => [match[1], match[2].trim()]),
);
const defaults: Record<string, string> = {};
for (const match of builder.matchAll(/^ENV (\w+)=(.*)$/gm)) {
  defaults[match[1]] = match[2].trim().replace(/\$(\w+)/g, (_, name: string) => args[name] ?? "");
}

function validate(overrides: Record<string, string> = {}) {
  const env: NodeJS.ProcessEnv = { ...defaults, ...overrides };
  for (const key of ["SystemRoot", "WINDIR", "TEMP", "TMP"]) {
    if (process.env[key]) env[key] = process.env[key];
  }
  return spawnSync(process.execPath, [path.join(root, "scripts/validate-deploy-env.mjs")], {
    env,
    encoding: "utf8",
    timeout: 10_000,
  });
}

describe("container builder environment contract", () => {
  it("passes strict validation with the declared non-secret build defaults", () => {
    const result = validate();
    expect(result.error).toBeUndefined();
    expect(result.status, result.stderr).toBe(0);
    expect(defaults.DASHBOARD_CANONICAL_ORIGIN).toBe("http://localhost:3000");
  });

  it("accepts an explicit HTTPS browser origin override", () => {
    expect(validate({ DASHBOARD_CANONICAL_ORIGIN: "https://dashboard.example" }).status).toBe(0);
  });

  it.each(["", "https://*.example", "http://0.0.0.0:3000"])(
    "fails closed for an invalid origin override: %s",
    (origin) => expect(validate({ DASHBOARD_CANONICAL_ORIGIN: origin }).status).toBe(1),
  );
});
