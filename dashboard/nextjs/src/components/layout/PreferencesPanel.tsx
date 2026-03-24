"use client";

import { useEffect } from "react";
import { Card } from "@/components/primitives/Card";
import type { OperatorPreferences } from "@/contracts/preferences";
import { usePreferencesQuery } from "@/hooks/queries/usePreferencesQuery";
import { useSavePreferencesMutation } from "@/hooks/mutations/useSavePreferencesMutation";
import { usePreferencesStore } from "@/store/usePreferencesStore";

export default function PreferencesPanel() {
  const { data } = usePreferencesQuery();
  const saveMutation = useSavePreferencesMutation();
  const prefs = usePreferencesStore((state) => state.preferences);
  const setPreferences = usePreferencesStore((state) => state.setPreferences);
  const patchPreferences = usePreferencesStore((state) => state.patchPreferences);

  useEffect(() => {
    if (data) {
      setPreferences(data);
    }
  }, [data, setPreferences]);

  return (
    <Card className="mt-4">
      <h3 className="text-sm font-semibold">Operator Preferences</h3>
      <div className="mt-3">
        <label htmlFor="pref-density" className="text-xs">
          Density
          <select
            id="pref-density"
            name="density"
            className="mt-1 w-full rounded border border-white/20 bg-slate-900 px-2 py-1"
            value={prefs.density}
            onChange={(e) =>
              patchPreferences({ density: e.target.value as OperatorPreferences["density"] })
            }
          >
            <option value="comfortable">Comfortable</option>
            <option value="compact">Compact</option>
          </select>
        </label>
      </div>
      <div className="mt-3 flex gap-3 text-xs">
        <label>
          <input
            id="pref-show-latency"
            name="show_latency"
            type="checkbox"
            checked={prefs.showLatency}
            onChange={(e) => patchPreferences({ showLatency: e.target.checked })}
          />{" "}
          Show latency
        </label>
        <label>
          <input
            id="pref-show-hashes"
            name="show_hashes"
            type="checkbox"
            checked={prefs.showHashes}
            onChange={(e) => patchPreferences({ showHashes: e.target.checked })}
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
