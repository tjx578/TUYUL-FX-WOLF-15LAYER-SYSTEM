// @vitest-environment node
import { spawn, type ChildProcess } from "node:child_process";
import path from "node:path";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "../app/api/auth/owner-login/route";
import { DELETE } from "../app/api/set-session/route";
import { validateSessionToken } from "../lib/serverAuth";
import { middleware } from "../middleware";

let core: ChildProcess;
let url: string;

beforeAll(async () => {
  // Explicit interpreter selection; deliberately do not inherit dotenv/auth/DB env.
  const python = process.env.OWNER_LOGIN_TEST_PYTHON;
  if (!python) throw new Error("Set OWNER_LOGIN_TEST_PYTHON to disposable test Python");
  const env: NodeJS.ProcessEnv = { NODE_ENV: "test", PYTHONUNBUFFERED: "1", PYTHONDONTWRITEBYTECODE: "1" };
  for (const name of ["SystemRoot", "WINDIR", "TEMP", "TMP", "LANG"]) {
    if (process.env[name]) env[name] = process.env[name];
  }
  core = spawn(python, [path.resolve("src/__tests__/fixtures/owner_login_core.py")], { env, stdio: ["ignore", "pipe", "pipe"] });
  // Drain synthetic diagnostics without retaining or emitting child output.
  core.stderr!.resume();
  const port = await new Promise<string>((resolve, reject) => {
    let output = "";
    // Windows cold imports measured 13s; allow contention during the complete suite.
    const timer = setTimeout(() => reject(new Error("Disposable core startup timed out")), 45000);
    core.once("error", error => { clearTimeout(timer); reject(error); });
    core.once("exit", code => { clearTimeout(timer); reject(new Error(`Disposable core exited ${code}`)); });
    core.stdout!.on("data", chunk => {
      output += chunk.toString();
      const match = output.match(/CONTRACT_PORT=(\d+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
  });
  url = `http://127.0.0.1:${port}`;
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(url + "/ready", { signal: AbortSignal.timeout(100) })).ok) break; } catch { /* startup */ }
    if (attempt === 99) throw new Error("Disposable core not ready");
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  vi.stubEnv("INTERNAL_API_URL", url);
  vi.stubEnv("NODE_ENV", "test");
  vi.stubEnv("DASHBOARD_CANONICAL_ORIGIN", "http://localhost");
}, 65000);

afterAll(async () => {
  vi.unstubAllEnvs();
  if (!core?.pid || core.exitCode !== null || core.signalCode !== null) return;
  await new Promise<void>((resolve, reject) => {
    const finish = () => {
      clearTimeout(forceTimer);
      clearTimeout(deadline);
      resolve();
    };
    const forceTimer = setTimeout(() => core.kill("SIGKILL"), 2000);
    const deadline = setTimeout(() => {
      core.removeListener("exit", finish);
      core.stdout?.destroy();
      core.stderr?.destroy();
      core.unref();
      reject(new Error("Disposable core did not confirm exit within five seconds"));
    }, 5000);
    core.once("exit", finish);
    core.kill();
  });
}, 7000);

function login(password: string) {
  return POST(new NextRequest("http://localhost/api/auth/owner-login", {
    method: "POST", headers: { origin: "http://localhost", "content-type": "application/json" },
    body: JSON.stringify({ username: "owner@example.test", password }),
  }));
}

it("uses real HTTP auth authority, denies privilege/expiry, and clears browser access on logout", async () => {
  const wrong = await login("incorrect-test-password");
  expect(wrong.status).toBe(401);
  expect(wrong.headers.get("set-cookie")).toBeNull();
  const result = await login("disposable-test-password");
  expect(result.status).toBe(200);
  expect(await result.json()).toEqual({ ok: true });
  const session = result.cookies.get("wolf15_session")!;
  expect(session.httpOnly).toBe(true);
  expect(session.maxAge).toBeGreaterThan(0);
  expect(session.maxAge).toBeLessThanOrEqual(900);
  const user = await validateSessionToken(session.value);
  expect(user).toMatchObject({ role: "viewer", scopes: ["read:dashboard"], auth_method: "jwt" });
  const denied = await fetch(url + "/privileged", { method: "POST", headers: { authorization: `Bearer ${session.value}` } });
  expect(denied.status).toBe(403);
  const expired = await (await fetch(url + "/expired-fixture")).json();
  expect(await validateSessionToken(expired.token)).toBeNull();
  expect((await fetch(url + "/api/auth/session", { headers: { authorization: `Bearer ${expired.token}` } })).status).toBe(401);
  const logout = await DELETE();
  const removed = logout.cookies.get("wolf15_session")!;
  expect(removed.value).toBe("");
  expect(new Date(removed.expires!).getTime()).toBeLessThan(Date.now());
  const noCookie = middleware(new NextRequest("http://localhost/api/proxy/dashboard/overview"));
  expect(noCookie.status).toBe(401);
  // Stateless logout does not revoke a copied JWT: preserve this explicit limitation.
  expect(await validateSessionToken(session.value)).not.toBeNull();
}, 15000);
