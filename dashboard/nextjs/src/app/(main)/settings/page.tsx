"use client";

import { useState } from "react";

/* ---- Setting Row ---- */
function SettingRow({
  label,
  desc,
  children,
}: {
  label: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "14px 0",
        borderBottom: "1px solid #30343C",
      }}
    >
      <div>
        <div style={{ color: "#F5F7FA", fontWeight: 600, fontSize: 14 }}>
          {label}
        </div>
        <div style={{ color: "#717886", fontSize: 12, marginTop: 2 }}>
          {desc}
        </div>
      </div>
      {children}
    </div>
  );
}

/* ---- Toggle Switch ---- */
function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <button
      onClick={onChange}
      style={{
        width: 44,
        height: 24,
        borderRadius: 999,
        border: "none",
        background: checked ? "#C8FF1A" : "#30343C",
        position: "relative",
        cursor: "pointer",
        transition: "background 0.15s",
      }}
    >
      <div
        style={{
          width: 18,
          height: 18,
          borderRadius: 999,
          background: checked ? "#0A0B0D" : "#717886",
          position: "absolute",
          top: 3,
          left: checked ? 23 : 3,
          transition: "left 0.15s",
        }}
      />
    </button>
  );
}

export default function SettingsPage() {
  const [darkMode, setDarkMode] = useState(true);
  const [notifications, setNotifications] = useState(true);
  const [autoSync, setAutoSync] = useState(false);
  const [soundAlerts, setSoundAlerts] = useState(true);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* 2-Column Layout */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.4fr 0.6fr",
          gap: 14,
        }}
      >
        {/* Settings Form */}
        <div
          style={{
            background: "#1B1D21",
            border: "1px solid #30343C",
            borderRadius: 14,
            padding: 20,
          }}
        >
          <h3
            style={{
              margin: "0 0 16px",
              fontSize: 16,
              fontWeight: 700,
              color: "#F5F7FA",
            }}
          >
            General Settings
          </h3>

          <SettingRow
            label="Dark Mode"
            desc="Dashboard UI theme preference"
          >
            <Toggle
              checked={darkMode}
              onChange={() => setDarkMode(!darkMode)}
            />
          </SettingRow>

          <SettingRow
            label="Telegram Notifications"
            desc="Send signal alerts via Telegram"
          >
            <Toggle
              checked={notifications}
              onChange={() => setNotifications(!notifications)}
            />
          </SettingRow>

          <SettingRow
            label="Auto Account Sync"
            desc="Sync balance/equity from broker every 5m"
          >
            <Toggle
              checked={autoSync}
              onChange={() => setAutoSync(!autoSync)}
            />
          </SettingRow>

          <SettingRow
            label="Sound Alerts"
            desc="Play audio on new signal or risk warning"
          >
            <Toggle
              checked={soundAlerts}
              onChange={() => setSoundAlerts(!soundAlerts)}
            />
          </SettingRow>

          <div style={{ marginTop: 20 }}>
            <h4
              style={{
                color: "#F5F7FA",
                fontWeight: 700,
                fontSize: 14,
                marginBottom: 12,
              }}
            >
              Risk Defaults
            </h4>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 12,
              }}
            >
              {[
                { label: "Risk Per Trade", value: "0.50%" },
                { label: "Max Open Trades", value: "5" },
                { label: "Correlation Limit", value: "3" },
                { label: "News Lock Window", value: "30 min" },
              ].map((item) => (
                <div
                  key={item.label}
                  style={{
                    background: "#23262C",
                    border: "1px solid #30343C",
                    borderRadius: 10,
                    padding: "10px 14px",
                  }}
                >
                  <div
                    style={{
                      color: "#717886",
                      fontSize: 11,
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                    }}
                  >
                    {item.label}
                  </div>
                  <div
                    style={{
                      color: "#F5F7FA",
                      fontWeight: 700,
                      fontSize: 16,
                      marginTop: 4,
                    }}
                  >
                    {item.value}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Control Notes */}
        <div
          style={{
            background: "#1B1D21",
            border: "1px solid #30343C",
            borderRadius: 14,
            padding: 20,
          }}
        >
          <h3
            style={{
              margin: "0 0 14px",
              fontSize: 16,
              fontWeight: 700,
              color: "#F5F7FA",
            }}
          >
            Notes
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {[
              {
                title: "Authority Boundary",
                note: "Settings do not override L12 verdicts or risk firewall logic.",
              },
              {
                title: "Sync Scope",
                note: "Auto-sync reads balance/equity only. No write access to broker.",
              },
              {
                title: "Notification Delay",
                note: "Telegram alerts may have 2-5s latency depending on network.",
              },
            ].map((n, i) => (
              <div
                key={i}
                style={{
                  background: "#23262C",
                  border: "1px solid #30343C",
                  borderRadius: 12,
                  padding: "12px 14px",
                  borderLeft: "3px solid #C8FF1A",
                }}
              >
                <div
                  style={{
                    fontWeight: 700,
                    fontSize: 13,
                    color: "#F5F7FA",
                    marginBottom: 4,
                  }}
                >
                  {n.title}
                </div>
                <div style={{ color: "#A5ADBA", fontSize: 12 }}>
                  {n.note}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
