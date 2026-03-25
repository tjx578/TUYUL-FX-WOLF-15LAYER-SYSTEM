"use client";

import { useEffect, useState } from "react";

export function formatDate(
  value: string | number | Date | null | undefined,
  options?: { showTime?: boolean; showSeconds?: boolean }
): string {
  if (value == null) return "—";
  const { showTime = true, showSeconds = false } = options ?? {};
  try {
    const d = value instanceof Date ? value : new Date(value);
    if (isNaN(d.getTime())) return "—";
    const yyyy = d.getUTCFullYear();
    const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(d.getUTCDate()).padStart(2, "0");
    if (!showTime) return `${yyyy}-${mm}-${dd}`;
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const min = String(d.getUTCMinutes()).padStart(2, "0");
    if (!showSeconds) return `${yyyy}-${mm}-${dd} ${hh}:${min} UTC`;
    const ss = String(d.getUTCSeconds()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${min}:${ss} UTC`;
  } catch {
    return "—";
  }
}

export function formatDateTime(
  value: string | number | Date | null | undefined
): string {
  return formatDate(value, { showTime: true, showSeconds: true });
}

export function formatNumber(
  value: number | string | null | undefined,
  decimals: number = 2,
  options?: { fallback?: string }
): string {
  const { fallback = "—" } = options ?? {};
  if (value == null) return fallback;
  const num = typeof value === "string" ? parseFloat(value) : value;
  if (isNaN(num)) return fallback;
  const [intPart, decPart] = num.toFixed(decimals).split(".");
  const withCommas = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return decPart ? `${withCommas}.${decPart}` : withCommas;
}

export function formatCurrency(
  value: number | string | null | undefined,
  options?: { decimals?: number; currency?: string; fallback?: string }
): string {
  const { decimals = 2, currency = "$", fallback = "—" } = options ?? {};
  if (value == null) return fallback;
  const num = typeof value === "string" ? parseFloat(value) : value;
  if (isNaN(num)) return fallback;
  const sign = num < 0 ? "-" : "";
  const abs = Math.abs(num);
  const [intPart, decPart] = abs.toFixed(decimals).split(".");
  const withCommas = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${sign}${currency}${withCommas}${decPart ? "." + decPart : ""}`;
}

export function formatPercent(
  value: number | string | null | undefined,
  decimals: number = 1,
  options?: { fallback?: string }
): string {
  const { fallback = "—" } = options ?? {};
  if (value == null) return fallback;
  const num = typeof value === "string" ? parseFloat(value) : value;
  if (isNaN(num)) return fallback;
  return `${num >= 0 ? "+" : ""}${num.toFixed(decimals)}%`;
}

export function formatPips(
  value: number | string | null | undefined,
  decimals: number = 1
): string {
  if (value == null) return "—";
  const num = typeof value === "string" ? parseFloat(value) : value;
  if (isNaN(num)) return "—";
  return `${num.toFixed(decimals)} pips`;
}

export function formatAge(ageMs: number): string {
  if (ageMs <= 0) return "0s";
  const totalSec = Math.floor(ageMs / 1000);
  if (totalSec < 60) return `${totalSec}s`;
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  if (min < 60) return sec > 0 ? `${min}m ${sec}s` : `${min}m`;
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  return remMin > 0 ? `${hr}h ${remMin}m` : `${hr}h`;
}

export function useHydrated(): boolean {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => { setHydrated(true); }, []);
  return hydrated;
}

export function useHydratedNow(intervalMs: number = 1000): number {
  const [now, setNow] = useState<number>(0);
  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function useClientDate(
  value: string | number | Date | null | undefined,
  options?: Intl.DateTimeFormatOptions
): string {
  const ssrValue = formatDate(value);
  const [display, setDisplay] = useState(ssrValue);
  useEffect(() => {
    if (value == null) return;
    try {
      const d = value instanceof Date ? value : new Date(value);
      if (isNaN(d.getTime())) return;
      setDisplay(d.toLocaleString("en-GB", options ?? {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", timeZoneName: "short",
      }));
    } catch { /* keep SSR value */ }
  }, [value, options]);
  return display;
}

export function useClientNumber(
  value: number | string | null | undefined,
  options?: Intl.NumberFormatOptions
): string {
  const ssrValue = formatNumber(value);
  const [display, setDisplay] = useState(ssrValue);
  useEffect(() => {
    if (value == null) return;
    const num = typeof value === "string" ? parseFloat(value) : value;
    if (isNaN(num)) return;
    try { setDisplay(num.toLocaleString(undefined, options)); } catch { /* keep SSR value */ }
  }, [value, options]);
  return display;
}
