import { z } from "zod";

export const SessionUserSchema = z.object({
  user_id: z.string().min(1),
  // Accept any non-empty string — the backend uses `sub` as email fallback
  // when authenticating via static API key (e.g. "api_key_user").
  email: z.string().min(1),
  role: z.enum([
    "owner",
    "viewer",
    "operator",
    "risk_admin",
    "config_admin",
    "approver",
  ]),
  name: z.string().min(1).optional(),
});

export type SessionUserParsed = z.infer<typeof SessionUserSchema>;
