"use client";

import type { AgentProfile, AgentItem } from "@/types/agent-manager";
import { EAClass } from "@/types/agent-manager";

interface Props {
  profiles: AgentProfile[];
  agents: AgentItem[];
  isLoading?: boolean;
}

const CLASS_COLORS: Record<EAClass, string> = {
  [EAClass.PRIMARY]: "var(--cyan, #06b6d4)",
  [EAClass.PORTFOLIO]: "var(--amber, #f59e0b)",
};

export function AgentManagerProfiles({ profiles, agents, isLoading }: Props) {
  if (isLoading) {
    return <div style={{ padding: 16, color: "var(--text-muted)", fontSize: 12 }}>Loading profiles...</div>;
  }

  if (profiles.length === 0) {
    return <div style={{ padding: 16, color: "var(--text-muted)", fontSize: 12, textAlign: "center" }}>No profiles configured.</div>;
  }

  const grouped = new Map<EAClass, AgentProfile[]>();
  for (const profile of profiles) {
    const list = grouped.get(profile.ea_class) ?? [];
    list.push(profile);
    grouped.set(profile.ea_class, list);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {Array.from(grouped.entries()).map(([eaClass, classProfiles]) => (
        <div key={eaClass} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", color: CLASS_COLORS[eaClass] ?? "var(--text-muted)", display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: CLASS_COLORS[eaClass] ?? "var(--text-muted)", display: "inline-block" }} />
            {eaClass}
          </div>

          {classProfiles.map((profile) => {
            const linkedCount = agents.filter((a) => a.linked_profile_id === profile.id).length;
            return (
              <div key={profile.id} style={{ padding: 14, borderRadius: 10, border: "1px solid var(--bg-border)", background: "var(--bg-card)", display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{profile.profile_name}</span>
                  <span style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)", padding: "1px 8px", border: "1px solid var(--bg-border)", borderRadius: 9999 }}>
                    {linkedCount} agent{linkedCount !== 1 ? "s" : ""}
                  </span>
                </div>
                {profile.description && <p style={{ fontSize: 11, color: "var(--text-muted)", margin: 0 }}>{profile.description}</p>}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
                  <DetailRow label="Subtype" value={profile.ea_subtype} />
                  <DetailRow label="Exec Mode" value={profile.execution_mode} />
                  <DetailRow label="Reporter" value={profile.reporter_mode} />
                  <DetailRow label="Risk ×" value={String(profile.default_risk_multiplier)} />
                  {profile.default_news_lock && <DetailRow label="News Lock" value={profile.default_news_lock} />}
                  {profile.allowed_strategies.length > 0 && <DetailRow label="Strategies" value={profile.allowed_strategies.join(", ")} />}
                </div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span className="num" style={{ fontWeight: 600, color: "var(--text-secondary)" }}>{value}</span>
    </div>
  );
}
