"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/primitives/Card";
import type { OperatorPreferences } from "@/contracts/preferences";
import { usePreferencesQuery } from "@/hooks/queries/usePreferencesQuery";
import { useSavePreferencesMutation } from "@/hooks/mutations/useSavePreferencesMutation";

const defaultPrefs: OperatorPreferences = {
  density: "comfortable",
  showLatency: true,
  showHashes: false,
  layoutPreset: "default",
};

export default function PreferencesPanel() {
  const { data } = usePreferencesQuery();
  const saveMutation = useSavePreferencesMutation();
  const [prefs, setPrefs] = useState<OperatorPreferences>(defaultPrefs);

  useEffect(() => {
    if (data) {
      setPrefs(data);
    }
  }, [data]);

  return (
    <Card className="mt-4">
      <h3 className="text-sm font-semibold">Operator Preferences</h3>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        <label className="text-xs">
          Density
          <select
            className="mt-1 w-full rounded border border-white/20 bg-slate-900 px-2 py-1"
            value={prefs.density}
            onChange={(e) => setPrefs((p) => ({ ...p, density: e.target.value as OperatorPreferences["density"] }))}
          >
            <option value="comfortable">Comfortable</option>
            <option value="compact">Compact</option>
          </select>
        </label>
        <label className="text-xs">
          Layout preset
          <select
            className="mt-1 w-full rounded border border-white/20 bg-slate-900 px-2 py-1"
            value={prefs.layoutPreset}
            onChange={(e) =>
              setPrefs((p) => ({ ...p, layoutPreset: e.target.value as OperatorPreferences["layoutPreset"] }))
            }
          >
            <option value="default">Default</option>
            <option value="risk_focus">Risk focus</option>
            <option value="pipeline_focus">Pipeline focus</option>
          </select>
        </label>
      </div>
      <div className="mt-3 flex gap-3 text-xs">
        <label>
          <input
            type="checkbox"
            checked={prefs.showLatency}
            onChange={(e) => setPrefs((p) => ({ ...p, showLatency: e.target.checked }))}
          />{" "}
          Show latency
        </label>
        <label>
          <input
            type="checkbox"
            checked={prefs.showHashes}
            onChange={(e) => setPrefs((p) => ({ ...p, showHashes: e.target.checked }))}
          />{" "}
          Show hashes
        </label>
      </div>
      <button
        type="button"
        onClick={() => saveMutation.mutate(prefs)}
        className="mt-4 rounded-lg border border-cyan-400/40 px-3 py-2 text-xs"
      >
        Save preferences
      </button>
    </Card>
  );
}
