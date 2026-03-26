"use client";

import { useMemo, useState } from "react";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import { DomainHeader } from "@/shared/ui/DomainHeader";
import { API_ENDPOINTS, apiMutate } from "@/shared/api/client";
import { useHealth } from "@/shared/api/system.api";

const TABS = [
  "General",
  "Accounts",
  "Risk & Limits",
  "Execution",
  "Signals & Gates",
  "Prop Firm",
  "News / Calendar Lock",
  "Notifications",
  "Security & Access",
  "Data & Audit",
] as const;

type ScopeType = "global" | "account" | "prop_firm" | "pair";

export function SettingsScreen() {
  const { data } = useHealth();
  const [tab, setTab] = useState<(typeof TABS)[number]>("General");
  const [profileName, setProfileName] = useState("default");
  const [scopeType, setScopeType] = useState<ScopeType>("global");
  const [scopeKey, setScopeKey] = useState("DEFAULT");
  const [overrideJson, setOverrideJson] = useState('{"settings":{}}');
  const [message, setMessage] = useState("");

  const endpointList = useMemo(
    () => [
      API_ENDPOINTS.configProfile,
      API_ENDPOINTS.configActive,
      API_ENDPOINTS.configEffective,
      API_ENDPOINTS.configOverrideLegacy,
      API_ENDPOINTS.configLock,
    ],
    []
  );

  const sendWrite = async (url: string, method: string, body: unknown) => {
    return apiMutate(url, body, method);
  };

  const activate = async () => {
    try {
      await sendWrite(API_ENDPOINTS.configActive, "POST", {
        profile_name: profileName,
      });
      setMessage(`Active profile set to ${profileName}`);
    } catch (err) {
      setMessage(String(err));
    }
  };

  const saveOverride = async () => {
    try {
      const parsed = JSON.parse(overrideJson);
      await sendWrite(API_ENDPOINTS.configOverrideLegacy, "POST", {
        scope: scopeType,
        scope_key: scopeKey,
        override: parsed,
      });
      setMessage(`Saved ${scopeType}:${scopeKey}`);
    } catch (err) {
      setMessage(String(err));
    }
  };

  const lockConfig = async (locked: boolean) => {
    try {
      await sendWrite(API_ENDPOINTS.configLock, "POST", { locked });
      setMessage(locked ? "Config locked" : "Config unlocked");
    } catch (err) {
      setMessage(String(err));
    }
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <PageComplianceBanner page="settings" />

      <DomainHeader
        domain="settings"
        title="SETTINGS CENTER"
        subtitle="Single source of truth for profiles, overrides, effective config, and configuration governance"
        actions={
          <div
            style={{
              fontSize: 11,
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
            }}
          >
            API {data?.status ?? "unknown"}
          </div>
        }
      />

      <div className="rounded-xl border p-4" style={{ display: "grid", gap: 8 }}>
        <div className="font-semibold">CONFIG CONTROL SURFACE</div>
        <div className="text-sm">Health: {data?.status ?? "unknown"}</div>
        <div className="text-xs opacity-80">Endpoints: {endpointList.join(" • ")}</div>
        {message && (
          <div className="text-xs" style={{ color: "#7dd3fc" }}>
            {message}
          </div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 12 }}>
        <aside
          className="rounded-xl border p-2"
          style={{ display: "grid", gap: 6, alignContent: "start" }}
        >
          {TABS.map((item) => (
            <button
              key={item}
              onClick={() => setTab(item)}
              className="rounded-lg border px-3 py-2 text-left"
              style={{
                opacity: tab === item ? 1 : 0.6,
                borderColor: tab === item ? "#00E5FF" : "rgba(255,255,255,0.2)",
              }}
            >
              {item}
            </button>
          ))}
        </aside>

        <section className="rounded-xl border p-4" style={{ display: "grid", gap: 12 }}>
          <div className="font-semibold">{tab}</div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(2, minmax(0,1fr))",
              gap: 10,
            }}
          >
            <label className="text-sm">
              Active Profile
              <input
                name="profile_name"
                value={profileName}
                onChange={(e) => setProfileName(e.target.value)}
                className="mt-1 w-full rounded border px-2 py-1 bg-transparent"
              />
            </label>

            <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
              <button className="rounded-lg border px-3 py-2" onClick={activate}>
                Set Active Profile
              </button>
              <button className="rounded-lg border px-3 py-2" onClick={() => lockConfig(true)}>
                Lock Config
              </button>
              <button className="rounded-lg border px-3 py-2" onClick={() => lockConfig(false)}>
                Unlock
              </button>
            </div>
          </div>

          <div className="text-xs opacity-80">
            Scope hierarchy: <b>global → account → prop_firm → pair</b>. Merge tetap dilakukan backend.
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <label className="text-sm">
              Scope
              <select
                name="scope_type"
                value={scopeType}
                onChange={(e) => setScopeType(e.target.value as ScopeType)}
                className="mt-1 w-full rounded border px-2 py-1 bg-transparent"
              >
                <option value="global">global</option>
                <option value="account">account</option>
                <option value="prop_firm">prop_firm</option>
                <option value="pair">pair</option>
              </select>
            </label>

            <label className="text-sm">
              Scope Key
              <input
                name="scope_key"
                value={scopeKey}
                onChange={(e) => setScopeKey(e.target.value)}
                className="mt-1 w-full rounded border px-2 py-1 bg-transparent"
                placeholder="DEFAULT / ACC-001 / FTMO / EURUSD"
              />
            </label>
          </div>

          <label className="text-sm">
            Override JSON
            <textarea
              name="override_json"
              value={overrideJson}
              onChange={(e) => setOverrideJson(e.target.value)}
              rows={12}
              className="mt-1 w-full rounded border px-2 py-2 bg-transparent"
            />
          </label>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="rounded-lg border px-3 py-2" onClick={saveOverride}>
              Save Changes
            </button>
            <button
              className="rounded-lg border px-3 py-2"
              onClick={() => setOverrideJson('{"settings":{}}')}
            >
              Reset JSON
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
