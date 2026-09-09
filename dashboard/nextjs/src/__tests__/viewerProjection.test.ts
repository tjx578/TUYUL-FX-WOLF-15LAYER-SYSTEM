import { describe, expect, it } from "vitest";
import { projectFeed, projectHealth, projectStatus } from "@/lib/server/viewerProjection";

describe("server-side viewer projection", () => {
  it("projects only explicit status fields and excludes fabricated activity counts", () => {
    const projected = projectStatus({status:"ok",service:"tuyul-fx",version:"10.0.0",feed_status:"fresh",engine_alive:true,
      token:"CANARY",nested:{api_key:"CANARY"},detail:"CANARY",router_boot_errors:["CANARY"],active_pairs:0,active_trades:0,mt5_connected:false});
    expect(projected).toMatchObject({status:"ok",version:"10.0.0",feed_status:"fresh",engine_alive:true});
    for(const field of ["token","nested","detail","router_boot_errors","active_pairs","active_trades","mt5_connected"]) expect(projected).not.toHaveProperty(field);
    expect(JSON.stringify(projected)).not.toContain("CANARY");
  });
  it.each([NaN,Infinity,-1,1e13,"12",{secret:"CANARY"}])("rejects invalid numeric values %s", value=>{
    expect(projectStatus({status:"ok",feed_staleness_seconds:value}).feed_staleness_seconds).toBeNull();
  });
  it("does not copy arbitrary strings into recognized status fields",()=>{
    const projected=projectStatus({status:"ok",service:"CANARY",version:"CANARY",feed_status:"CANARY",ingest_health:"CANARY",engine_alive:"CANARY"});
    expect(JSON.stringify(projected)).not.toContain("CANARY");
  });
  it("projects bounded feed rows without unknown provider payloads",()=>{
    const projected=projectFeed({ingest_status:"HEALTHY",provider_connected:true,dsn:"CANARY",symbols:{
      EURUSD:{feed_status:"LIVE",age_seconds:2,provider:"CANARY",nested:{password:"CANARY"}},
      "invalid key/CANARY":{feed_status:"LIVE"},
    }});
    expect(projected).toEqual({ingest_status:"HEALTHY",provider_connected:true,symbols:{EURUSD:{feed_status:"LIVE",age_seconds:2}}});
    expect(JSON.stringify(projected)).not.toContain("CANARY");
  });
  it("rejects unbounded symbol collections",()=>{
    expect(()=>projectFeed({ingest_status:"UNKNOWN",symbols:Object.fromEntries(Array.from({length:257},(_,i)=>["SYM"+i,{}]))})).toThrow();
  });
  it.each([null,[],"CANARY",{error:"CANARY"}])("rejects malformed successful upstream data", value=>{
    expect(()=>projectStatus(value)).toThrow();expect(()=>projectFeed(value)).toThrow();expect(()=>projectHealth(value)).toThrow();
  });
  it("retains health liveness only",()=>{
    expect(projectHealth({status:"alive",service:"tuyul-fx",secret:"CANARY"})).toEqual({status:"alive",service:"tuyul-fx"});
  });
});
