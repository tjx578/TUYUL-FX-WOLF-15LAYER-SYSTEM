import { z } from "zod";

export const PreferencesSchema = z.object({
  density: z.enum(["compact", "comfortable"]),
  showLatency: z.boolean(),
  layoutPreset: z.enum(["default", "risk_focus", "pipeline_focus"]),
});

export type PreferencesParsed = z.infer<typeof PreferencesSchema>;
