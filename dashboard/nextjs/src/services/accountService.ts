import { z } from "zod";
import { apiClient } from "./apiClient";

export const AccountViewSchema = z.object({
  account_id: z.string().min(1),
  balance: z.number().finite(),
  equity: z.number().finite().optional(),
  currency: z.string().min(1).optional(),
  risk_state: z.string().min(1).optional(),
});

export const AccountListSchema = z.array(AccountViewSchema);

export type AccountView = z.infer<typeof AccountViewSchema>;

export async function fetchAccounts() {
  const response = await apiClient.get("/api/v1/accounts");
  const payload = response.data;

  if (Array.isArray(payload)) {
    return AccountListSchema.parse(payload);
  }

  return AccountListSchema.parse(payload?.accounts ?? []);
}
