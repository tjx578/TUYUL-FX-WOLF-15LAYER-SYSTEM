import { describe, it, expect } from "vitest";
import {
    AUDIT_MANIFEST,
    getDocsByDomain,
    docCountsByDomain,
} from "@/app/(root)/architecture-audit/_audit-data";

describe("AUDIT_MANIFEST structure", () => {
    it("has required top-level fields", () => {
        expect(typeof AUDIT_MANIFEST.version).toBe("string");
        expect(AUDIT_MANIFEST.version.length).toBeGreaterThan(0);
        expect(typeof AUDIT_MANIFEST.generated_at).toBe("string");
        expect(typeof AUDIT_MANIFEST.source).toBe("string");
        expect(typeof AUDIT_MANIFEST.description).toBe("string");
    });

    it("source points to docs/architecture/", () => {
        expect(AUDIT_MANIFEST.source).toBe("docs/architecture/");
    });

    it("has at least one domain", () => {
        expect(AUDIT_MANIFEST.domains.length).toBeGreaterThan(0);
    });

    it("every domain has id, label, and description", () => {
        for (const domain of AUDIT_MANIFEST.domains) {
            expect(typeof domain.id).toBe("string");
            expect(domain.id.length).toBeGreaterThan(0);
            expect(typeof domain.label).toBe("string");
            expect(domain.label.length).toBeGreaterThan(0);
            expect(typeof domain.description).toBe("string");
            expect(domain.description.length).toBeGreaterThan(0);
        }
    });

    it("has at least one doc", () => {
        expect(AUDIT_MANIFEST.docs.length).toBeGreaterThan(0);
    });

    it("every doc has required fields", () => {
        for (const doc of AUDIT_MANIFEST.docs) {
            expect(typeof doc.id).toBe("string");
            expect(doc.id.length).toBeGreaterThan(0);
            expect(typeof doc.title).toBe("string");
            expect(doc.title.length).toBeGreaterThan(0);
            expect(typeof doc.path).toBe("string");
            expect(doc.path.startsWith("docs/architecture/")).toBe(true);
            expect(typeof doc.domain).toBe("string");
            expect(doc.domain.length).toBeGreaterThan(0);
            expect(typeof doc.description).toBe("string");
            expect(doc.description.length).toBeGreaterThan(0);
            expect(doc.status).toBe("canonical");
            expect(typeof doc.last_updated).toBe("string");
        }
    });

    it("every doc.domain references a known domain id", () => {
        const domainIds = new Set(AUDIT_MANIFEST.domains.map((d) => d.id));
        for (const doc of AUDIT_MANIFEST.docs) {
            expect(domainIds.has(doc.domain)).toBe(true);
        }
    });

    it("every doc.id is unique", () => {
        const ids = AUDIT_MANIFEST.docs.map((d) => d.id);
        const unique = new Set(ids);
        expect(unique.size).toBe(ids.length);
    });

    it("every doc.path is unique", () => {
        const paths = AUDIT_MANIFEST.docs.map((d) => d.path);
        const unique = new Set(paths);
        expect(unique.size).toBe(paths.length);
    });

    it("contains no stale PDF audit metadata (no pdfScore, institutionalGrade, claim, actual)", () => {
        // Ensure no old audit fields leaked into the manifest
        const serialised = JSON.stringify(AUDIT_MANIFEST);
        expect(serialised).not.toContain("pdfScore");
        expect(serialised).not.toContain("institutionalGrade");
        expect(serialised).not.toContain('"claim"');
        expect(serialised).not.toContain('"actual"');
        expect(serialised).not.toContain("kondisi aktual repo");
        expect(serialised).not.toContain("PDF analysis");
    });

    it("does not contain any GAP status claims", () => {
        const serialised = JSON.stringify(AUDIT_MANIFEST);
        expect(serialised).not.toContain('"GAP"');
        expect(serialised).not.toContain('"PARTIAL"');
        expect(serialised).not.toContain('"VERIFIED"');
        expect(serialised).not.toContain('"EXCEEDS"');
    });
});

describe("getDocsByDomain", () => {
    it("returns docs matching the given domain id", () => {
        const coreDocs = getDocsByDomain("core");
        expect(coreDocs.length).toBeGreaterThan(0);
        for (const doc of coreDocs) {
            expect(doc.domain).toBe("core");
        }
    });

    it("returns an empty array for an unknown domain", () => {
        expect(getDocsByDomain("nonexistent-domain-xyz")).toEqual([]);
    });

    it("all known domains return at least one doc", () => {
        for (const domain of AUDIT_MANIFEST.domains) {
            const docs = getDocsByDomain(domain.id);
            expect(docs.length).toBeGreaterThan(0);
        }
    });
});

describe("docCountsByDomain", () => {
    it("returns an object with a key per domain", () => {
        const counts = docCountsByDomain();
        for (const domain of AUDIT_MANIFEST.domains) {
            expect(typeof counts[domain.id]).toBe("number");
            expect(counts[domain.id]).toBeGreaterThan(0);
        }
    });

    it("total across all domains equals total doc count", () => {
        const counts = docCountsByDomain();
        const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
        expect(total).toBe(AUDIT_MANIFEST.docs.length);
    });
});
