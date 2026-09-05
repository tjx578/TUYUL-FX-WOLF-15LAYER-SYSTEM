import { z } from "zod";

export const SessionUserSchema = z.object({
  user_id: z.string().min(1),
  email: z.string().min(1),
  role: z.enum([
    "owner",
    "viewer",
    "operator",
    "risk_admin",
    "config_admin",
    "approver",
  ]),
  name: z.string().min(1).nullable().optional(),
  scopes: z.array(z.string()).optional(),
  auth_method: z.string().optional(),
});

export type SessionUserParsed = z.infer<typeof SessionUserSchema>;
