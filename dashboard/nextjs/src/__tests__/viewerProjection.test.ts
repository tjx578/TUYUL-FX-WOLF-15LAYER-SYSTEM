import { describe, expect, it } from "vitest";
import { projectFeed, projectHealth, projectPairStates, projectStatus } from "@/lib/server/viewerProjection";

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
  it("projects only whitelisted verdict fields and derives pair quality from age",()=>{
    const projected=projectPairStates({mode:"LIVE",timestamp:1700000000,stale_seconds:12,verdicts:{
      GBPUSD:{verdict:"EXECUTE_BUY",governance:{action:"ALLOW"},_meta:{age_seconds:600},confidence:0.9,secret:"CANARY"},
      EURUSD:{verdict:"NO_TRADE",governance:{action:"BLOCK"},_meta:{age_seconds:10}},
      "invalid key/CANARY":{verdict:"NO_TRADE"},
    }});
    expect(projected).toEqual({mode:"LIVE",stale_seconds:12,observed_at:"2023-11-14T22:13:20.000Z",count:2,items:[
      {symbol:"EURUSD",lifecycle_state:"NO_TRADE",admission:"BLOCK",age_seconds:10,quality:"LIVE"},
      {symbol:"GBPUSD",lifecycle_state:"EXECUTE_BUY",admission:"ALLOW",age_seconds:600,quality:"STALE"},
    ]});
    expect(JSON.stringify(projected)).not.toContain("CANARY");
  });
  it("accepts every verdict the core contract declares and every one Layer 12 emits",()=>{
    const verdicts=["EXECUTE","EXECUTE_BUY","EXECUTE_SELL","EXECUTE_REDUCED_RISK_BUY","EXECUTE_REDUCED_RISK_SELL","NO_TRADE","HOLD","ABORT"];
    const projected=projectPairStates({mode:"LIVE",verdicts:Object.fromEntries(
      verdicts.map((verdict,i)=>["SYM"+i,{verdict}]),
    )});
    expect((projected.items as Array<Record<string,unknown>>).map(item=>item.lifecycle_state)).toEqual(verdicts);
  });
  it("still rejects a verdict neither the contract nor the emitter produces",()=>{
    const projected=projectPairStates({mode:"LIVE",verdicts:{EURUSD:{verdict:"WAIT"},GBPUSD:{verdict:"CANARY"}}});
    expect((projected.items as Array<Record<string,unknown>>).map(item=>item.lifecycle_state)).toEqual([null,null]);
  });
  it("accepts every governance action and never infers an absent one",()=>{
    const projected=projectPairStates({mode:"LIVE",verdicts:{
      AAAUSD:{verdict:"HOLD",governance:{action:"ALLOW"}},
      BBBUSD:{verdict:"HOLD",governance:{action:"ALLOW_REDUCED"}},
      CCCUSD:{verdict:"HOLD",governance:{action:"BLOCK"}},
      DDDUSD:{verdict:"HOLD",governance:{}},
      EEEUSD:{verdict:"HOLD"},
    }});
    expect((projected.items as Array<Record<string,unknown>>).map(item=>item.admission))
      .toEqual(["ALLOW","ALLOW_REDUCED","BLOCK",null,null]);
  });
  it("reports unmeasured verdict fields as null instead of inferring them",()=>{
    const projected=projectPairStates({mode:"DEGRADED",verdicts:{XAUUSD:{verdict:"CANARY",governance:"CANARY",_meta:"CANARY"}}});
    expect(projected.items).toEqual([{symbol:"XAUUSD",lifecycle_state:null,admission:null,age_seconds:null,quality:null}]);
    expect(projected.observed_at).toBeNull();expect(projected.stale_seconds).toBeNull();
    expect(JSON.stringify(projected)).not.toContain("CANARY");
  });
  it("rejects an unknown snapshot mode and an unbounded verdict collection",()=>{
    expect(()=>projectPairStates({mode:"CANARY",verdicts:{}})).toThrow();
    expect(()=>projectPairStates({mode:"LIVE",verdicts:Object.fromEntries(Array.from({length:257},(_,i)=>["SYM"+i,{}]))})).toThrow();
  });
  it.each([null,[],"CANARY",{error:"CANARY"}])("rejects malformed successful upstream data", value=>{
    expect(()=>projectStatus(value)).toThrow();expect(()=>projectFeed(value)).toThrow();expect(()=>projectHealth(value)).toThrow();expect(()=>projectPairStates(value)).toThrow();
  });
  it("retains health liveness only",()=>{
    expect(projectHealth({status:"alive",service:"tuyul-fx",secret:"CANARY"})).toEqual({status:"alive",service:"tuyul-fx"});
  });
});
