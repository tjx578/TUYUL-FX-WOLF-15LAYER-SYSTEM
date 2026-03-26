"use client";

import { IMPACT_STYLES } from "../model/news.types";

export function ImpactBadge({ impact }: { impact: string }) {
    const s = IMPACT_STYLES[impact as keyof typeof IMPACT_STYLES] ?? IMPACT_STYLES.LOW;
    return <span className={`badge ${s.cls}`}>{impact}</span>;
}
