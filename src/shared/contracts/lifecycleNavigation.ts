export type PostTakeRouteTarget = "signals" | "trades" | "accounts";

export interface SignalLifecycleNavigationContext {
    takeId: string;
    signalId: string;
    accountId: string;
    sourcePage: "signals";
    target: PostTakeRouteTarget;
    ts: number;
}

export function buildLifecycleNavigationQuery(
    ctx: SignalLifecycleNavigationContext,
): string {
    const params = new URLSearchParams({
        takeId: ctx.takeId,
        signalId: ctx.signalId,
        accountId: ctx.accountId,
        sourcePage: ctx.sourcePage,
        target: ctx.target,
        ts: String(ctx.ts),
    });

    return params.toString();
}

export function parseLifecycleNavigationContext(
    searchParams: URLSearchParams,
): SignalLifecycleNavigationContext | null {
    const takeId = searchParams.get("takeId");
    const signalId = searchParams.get("signalId");
    const accountId = searchParams.get("accountId");
    const sourcePage = searchParams.get("sourcePage");
    const target = searchParams.get("target");
    const ts = searchParams.get("ts");

    if (!takeId || !signalId || !accountId) return null;
    if (sourcePage !== "signals") return null;
    if (target !== "signals" && target !== "trades" && target !== "accounts")
        return null;

    return {
        takeId,
        signalId,
        accountId,
        sourcePage: "signals",
        target,
        ts: ts ? Number(ts) : Date.now(),
    };
}
