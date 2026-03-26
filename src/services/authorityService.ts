import { z } from "zod";
import type { AuthoritySurface } from "@/contracts/authority";
import { apiClient } from "./apiClient";

export const AuthoritySurfaceSchema = z.object({
    action: z.string().min(1),
    allowed: z.boolean(),
    reason: z.string().min(1).optional(),
    code: z.string().min(1).optional(),
});

export async function fetchAuthoritySurface(
    action: string,
    accountId?: string,
    tradeId?: string
): Promise<AuthoritySurface> {
    const response = await apiClient.get("/api/v1/authority/surface", {
        params: {
            action,
            account_id: accountId,
            trade_id: tradeId,
        },
    });

    return AuthoritySurfaceSchema.parse(response.data);
}
