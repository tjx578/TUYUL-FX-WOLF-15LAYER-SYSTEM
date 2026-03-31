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
}

export function Tabs({ tabs, activeTab, onTabChange, children }: TabsProps) {
  return (
    <div className="w-full">
      <div
        className="flex border-b"
        style={{
          borderColor: "var(--border)",
          backgroundColor: "var(--bg-card)",
        }}
      >
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className="px-4 py-3 font-mono text-sm transition-colors relative whitespace-nowrap"
            style={{
              color:
                activeTab === tab.id
                  ? "var(--accent)"
                  : "var(--text-muted)",
              backgroundColor: "transparent",
              border: "none",
              cursor: "pointer",
              fontFamily: "var(--font-mono)",
            }}
          >
            {tab.icon && <span className="mr-2">{tab.icon}</span>}
            {tab.label}
            {activeTab === tab.id && (
              <div
                className="absolute bottom-0 left-0 right-0 h-0.5"
                style={{
                  backgroundColor: "var(--accent)",
                }}
              />
            )}
          </button>
        ))}
      </div>
      <div style={{ backgroundColor: "var(--bg-elevated)" }}>{children}</div>
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
