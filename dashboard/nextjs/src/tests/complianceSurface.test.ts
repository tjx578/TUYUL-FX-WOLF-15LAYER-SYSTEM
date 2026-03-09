import { describe, expect, it } from "vitest";
import { buildComplianceSurface } from "@/lib/complianceSurface";

describe("buildComplianceSurface", () => {
  it("returns null for normal compliance", () => {
    expect(buildComplianceSurface("dashboard", "COMPLIANCE_NORMAL")).toBeNull();
    expect(buildComplianceSurface("dashboard", undefined)).toBeNull();
  });

  it("maps caution state to warning tone", () => {
    const surface = buildComplianceSurface("risk", "COMPLIANCE_CAUTION");
    expect(surface).not.toBeNull();
    expect(surface?.tone).toBe("warning");
    expect(surface?.title).toContain("Caution");
  });

  it("maps block state to error tone", () => {
    const surface = buildComplianceSurface("trades", "COMPLIANCE_BLOCK");
    expect(surface).not.toBeNull();
    expect(surface?.tone).toBe("error");
    expect(surface?.title).toContain("Block");
  });
});
