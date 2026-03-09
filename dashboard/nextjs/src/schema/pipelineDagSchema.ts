import { z } from "zod";

export const PipelineDagSchema = z.object({
  nodes: z.array(
    z.object({
      id: z.string().min(1),
      label: z.string().min(1),
      state: z.enum(["PASS", "FAIL", "SKIP", "ACTIVE", "IDLE"]),
    })
  ),
  edges: z.array(
    z.object({
      from: z.string().min(1),
      to: z.string().min(1),
    })
  ),
});

export type PipelineDagParsed = z.infer<typeof PipelineDagSchema>;
