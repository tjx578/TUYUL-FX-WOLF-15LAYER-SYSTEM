"use client";

import { useHealth } from "@/lib/api";

export default function SettingsPage() {
  const { data } = useHealth();
  return (
    <div className="space-y-4">
      <div className="rounded-xl border p-4">
        <div className="font-semibold">Service Area</div>
        <div className="text-sm">API Health: {data?.status ?? "unknown"}</div>
      </div>
      <div className="rounded-xl border p-4 text-sm opacity-80">
        Personalization/notification disimpan di client (localStorage), bukan authority trading.
      </div>
    </div>
  );
}