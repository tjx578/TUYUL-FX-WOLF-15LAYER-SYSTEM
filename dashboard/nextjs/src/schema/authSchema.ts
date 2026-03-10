import { z } from "zod";

export const SessionUserSchema = z.object({
  user_id: z.string().min(1),
  email: z.string().email(),
  role: z.enum([
    "viewer",
    "operator",
    "risk_admin",
    "config_admin",
    "approver",
  ]),
  name: z.string().min(1).optional(),
});

export type SessionUserParsed = z.infer<typeof SessionUserSchema>;
