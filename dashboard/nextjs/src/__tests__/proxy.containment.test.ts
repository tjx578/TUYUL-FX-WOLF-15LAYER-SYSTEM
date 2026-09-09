// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { DELETE, GET, PATCH, POST, PUT } from "@/app/api/proxy/[...path]/route";
import { isAllowlistedReadPath, READ_ONLY_PATHS } from "@/lib/server/readOnlyProxyPolicy";
const viewer = {user_id:"viewer-1",email:"viewer@example.test",role:"viewer",scopes:["read:dashboard"],auth_method:"jwt"};
const json = (body: unknown, status=200) => new Response(JSON.stringify(body), {status,headers:{"content-type":"application/json"}});
function request(path: string, method="GET", token="header.payload.signature") {
  return new NextRequest("https://dashboard.example/api/proxy/"+path,{method,headers:{authorization:token?"Bearer "+token:"",cookie:"wolf15_session=must-not-forward"}});
}
const context = (path: string) => ({params:Promise.resolve({path:path.split("/")})});
beforeEach(() => {vi.stubEnv("INTERNAL_API_URL","https://core.example");vi.stubGlobal("fetch",vi.fn());});
afterEach(() => {vi.unstubAllGlobals();vi.unstubAllEnvs();vi.restoreAllMocks();});

describe("direct core viewer proxy containment", () => {
  it("allows exactly three projection paths", () => {
    expect(READ_ONLY_PATHS).toEqual(["dashboard/overview","dashboard/feed-status","dashboard/aggregated-status"]);
    for (const path of READ_ONLY_PATHS) expect(isAllowlistedReadPath(path)).toBe(true);
  });
  it.each(["dashboard", "dashboard/overview/extra", "dashboard/settings", "bff/aggregated-status", "api/v1/status", "api/v1/execution/order", "dashboard/%2e%2e/settings", "dashboard/../settings", "/dashboard/overview", "dashboard/overview/"])("denies %s before fetch", async path => {
    expect(isAllowlistedReadPath(path)).toBe(false);
    expect((await GET(request(path),context(path))).status).toBe(403);expect(fetch).not.toHaveBeenCalled();
  });
  it.each([["POST",POST],["PUT",PUT],["PATCH",PATCH],["DELETE",DELETE]] as const)("denies %s before fetch",async(method,handler)=>{
    expect((await handler(request("dashboard/overview",method),context("dashboard/overview"))).status).toBe(403);expect(fetch).not.toHaveBeenCalled();
  });
  it("does not forward arbitrary query parameters",async()=>{
    expect((await GET(request("dashboard/overview?url=https://other.example"),context("dashboard/overview"))).status).toBe(403);expect(fetch).not.toHaveBeenCalled();
  });
  it.each(["", "machine-key"])("denies missing/malformed JWT before fetch",async token=>{
    expect((await GET(request("dashboard/overview","GET",token),context("dashboard/overview"))).status).toBe(401);expect(fetch).not.toHaveBeenCalled();
  });
  it("rejects a non-viewer before any business read",async()=>{
    vi.mocked(fetch).mockResolvedValueOnce(json({...viewer,role:"admin"}));
    expect((await GET(request("dashboard/overview"),context("dashboard/overview"))).status).toBe(401);expect(fetch).toHaveBeenCalledOnce();
  });
  it("composes overview directly from core and removes unknown fields before browser receipt",async()=>{
    vi.mocked(fetch).mockResolvedValueOnce(json(viewer)).mockResolvedValueOnce(json({status:"ok",service:"tuyul-fx",password:"CANARY",detail:"CANARY",router_boot_errors:["CANARY"],active_pairs:0,active_trades:0,mt5_connected:false})).mockResolvedValueOnce(json({status:"alive",service:"tuyul-fx",api_key:"CANARY"}));
    const response=await GET(request("dashboard/overview"),context("dashboard/overview"));
    expect(response.status).toBe(200);expect(vi.mocked(fetch).mock.calls.map(c=>c[0])).toEqual(["https://core.example/api/auth/session","https://core.example/api/v1/status","https://core.example/healthz"]);
    for(const call of vi.mocked(fetch).mock.calls.slice(1)) {
      const options=call[1];const headers=new Headers(options?.headers);
      expect(headers.get("authorization")).toBe("Bearer header.payload.signature");expect(headers.get("cookie")).toBeNull();
      expect(options?.redirect).toBe("error");expect(options?.signal).toBeInstanceOf(AbortSignal);expect(options?.cache).toBe("no-store");
    }
    const text=await response.text();for(const forbidden of ["CANARY","router_boot_errors","active_pairs","active_trades","mt5_connected"]) expect(text).not.toContain(forbidden);
    expect(JSON.parse(text)).toMatchObject({status:{status:"ok"},health:{status:"alive"},source:"core-api"});
    expect(response.headers.get("x-proxy-surface")).toBe("core-api");expect(response.headers.get("x-bff-cache")).toBeNull();expect(response.headers.get("x-proxy-target")).toBeNull();expect(response.headers.get("set-cookie")).toBeNull();
  });
  it.each(["dashboard/feed-status","dashboard/aggregated-status"])("maps %s only to its fixed route",async path=>{
    vi.mocked(fetch).mockResolvedValueOnce(json(viewer)).mockResolvedValueOnce(json(path.includes("feed")?{ingest_status:"UNKNOWN",provider_connected:false,symbols:{}}:{status:"ok"}));
    expect((await GET(request(path),context(path))).status).toBe(200);
    expect(vi.mocked(fetch).mock.calls[1][0]).toBe("https://core.example"+(path.includes("feed")?"/api/v1/candles/feed-status":"/api/v1/status"));
  });
  it.each(["", "https://dashboard.example"])("rejects missing or recursive upstream before fetch",async origin=>{
    vi.stubEnv("INTERNAL_API_URL",origin);expect((await GET(request("dashboard/overview"),context("dashboard/overview"))).status).toBe(503);expect(fetch).not.toHaveBeenCalled();
  });
  it.each([302,401,403,500,503])("sanitizes HTTP %s without returning upstream body",async status=>{
    vi.mocked(fetch).mockResolvedValueOnce(json(viewer)).mockResolvedValueOnce(json({error:"CANARY"},status));
    const response=await GET(request("dashboard/feed-status"),context("dashboard/feed-status"));
    expect(response.status).toBe(502);expect(await response.text()).not.toContain("CANARY");
  });
  it("sanitizes timeout/connection errors",async()=>{
    vi.mocked(fetch).mockResolvedValueOnce(json(viewer)).mockRejectedValueOnce(new DOMException("CANARY","TimeoutError"));
    const response=await GET(request("dashboard/feed-status"),context("dashboard/feed-status"));
    expect(response.status).toBe(502);expect(await response.text()).toContain("UPSTREAM_UNAVAILABLE");
  });
  it("rejects oversized bodies before any browser serialization",async()=>{
    vi.mocked(fetch).mockResolvedValueOnce(json(viewer)).mockResolvedValueOnce(json({ingest_status:"UNKNOWN",symbols:{},ignored:"x".repeat(128*1024)}));
    expect((await GET(request("dashboard/feed-status"),context("dashboard/feed-status"))).status).toBe(502);
  });
});
