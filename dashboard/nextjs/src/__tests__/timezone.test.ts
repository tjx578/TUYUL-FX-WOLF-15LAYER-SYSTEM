/**
 * Unit tests for lib/timezone.ts
 *
 * Tests:
 *  - formatTime, formatLocalDate, formatLocalDateTime
 *  - sessionLabel (ASIA / LONDON / NEW_YORK / OFF_SESSION)
 *  - msUntilNextHour returns a positive number
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { formatTime, formatLocalDate, formatLocalDateTime, sessionLabel, msUntilNextHour, nowInTz, nowHourInTz } from "@/lib/timezone";

afterEach(() => {
    vi.useRealTimers();
});

// ══════════════════════════════════════════════════════════════
//  Formatting
// ══════════════════════════════════════════════════════════════

describe("formatTime", () => {
    it("should format a timestamp as HH:MM:SS", () => {
        // Use UTC timezone for deterministic test
        const result = formatTime(new Date("2025-06-15T10:30:45Z"), "UTC");
        expect(result).toBe("10:30:45");
    });
});

describe("formatLocalDate", () => {
    it("should format a timestamp as DD/Mon/YYYY", () => {
        const result = formatLocalDate(new Date("2025-06-15T10:30:45Z"), "UTC");
        // en-US format: "Jun 15, 2025" or similar
        expect(result).toContain("Jun");
        expect(result).toContain("15");
        expect(result).toContain("2025");
    });
});

describe("formatLocalDateTime", () => {
    it("should combine date and time", () => {
        const result = formatLocalDateTime(new Date("2025-06-15T10:30:45Z"), "UTC");
        expect(result).toContain("Jun");
        expect(result).toContain("10:30:45");
    });

    it("should handle numeric timestamp input", () => {
        const ts = new Date("2025-06-15T10:30:45Z").getTime();
        const result = formatLocalDateTime(ts, "UTC");
        expect(result).toContain("Jun");
    });

    it("should handle string timestamp input", () => {
        const result = formatLocalDateTime("2025-06-15T10:30:45Z", "UTC");
        expect(result).toContain("Jun");
    });
});

// ══════════════════════════════════════════════════════════════
//  Session Label
// ══════════════════════════════════════════════════════════════

describe("sessionLabel", () => {
    it("should return a valid session string", () => {
        const label = sessionLabel();
        expect(["ASIA", "LONDON", "NEW_YORK", "OFF_SESSION"]).toContain(label);
    });
});

// ══════════════════════════════════════════════════════════════
//  msUntilNextHour
// ══════════════════════════════════════════════════════════════

describe("msUntilNextHour", () => {
    it("should return a positive number", () => {
        const ms = msUntilNextHour();
        expect(ms).toBeGreaterThan(0);
    });

    it("should return less than 3600000ms (one hour)", () => {
        const ms = msUntilNextHour();
        expect(ms).toBeLessThanOrEqual(3600000);
    });
});

// ══════════════════════════════════════════════════════════════
//  nowInTz (deprecated) + nowHourInTz
// ══════════════════════════════════════════════════════════════

describe("nowInTz", () => {
    it("should return a Date object", () => {
        const now = nowInTz();
        expect(now).toBeInstanceOf(Date);
    });
});

describe("nowHourInTz", () => {
    it("should return a number between 0 and 23", () => {
        const h = nowHourInTz();
        expect(h).toBeGreaterThanOrEqual(0);
        expect(h).toBeLessThanOrEqual(23);
    });
});
