"use client";

import React, { ReactNode } from "react";

export interface TabItem {
  id: string;
  label: string;
  icon?: string;
}

export interface TabsProps {
  tabs: TabItem[];
  activeTab: string;
  onTabChange: (id: string) => void;
  children: ReactNode;
  /** Number of columns for grid layout. Defaults to tabs.length */
  columns?: number;
}

export function Tabs({ tabs, activeTab, onTabChange, children, columns }: TabsProps) {
  const cols = columns ?? tabs.length;

  return (
    <div className="w-full">
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${cols}, 1fr)`,
          gap: 10,
          marginBottom: 10,
        }}
      >
        {tabs.map((tab) => {
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              style={{
                background: active
                  ? "linear-gradient(180deg, rgba(199,255,26,0.18), rgba(199,255,26,0.08))"
                  : "#0A0B0D",
                color: active ? "#C7FF1A" : "#A4ACB9",
                border: `1px solid ${active ? "rgba(199,255,26,0.35)" : "#1A1C1F"}`,
                borderRadius: 14,
                padding: 14,
                textAlign: "center",
                fontWeight: 800,
                cursor: "pointer",
                textTransform: "uppercase",
                letterSpacing: "0.03em",
                fontSize: 13,
                boxShadow: active ? "inset 0 0 0 1px rgba(199,255,26,0.06)" : "none",
              }}
            >
              {tab.icon && <span style={{ marginRight: 8 }}>{tab.icon}</span>}
              {tab.label}
            </button>
          );
        })}
      </div>
      <div>{children}</div>
    </div>
  );
}

export interface TabPanelProps {
  id: string;
  activeTab: string;
  children: ReactNode;
}

export function TabPanel({ id, activeTab, children }: TabPanelProps) {
  if (id !== activeTab) {
    return null;
  }
  return <>{children}</>;
}
