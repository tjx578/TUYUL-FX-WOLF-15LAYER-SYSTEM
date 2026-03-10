import { describe, expect, it } from "vitest";
import { PipelineDagSchema } from "@/schema/pipelineDagSchema";

describe("PipelineDagSchema", () => {
  it("parses legacy DAG payload without coordinates", () => {
    const parsed = PipelineDagSchema.parse({
      nodes: [
        { id: "n1", label: "L1", state: "PASS" },
        { id: "n2", label: "L2", state: "ACTIVE" },
      ],
      edges: [{ from: "n1", to: "n2" }],
    });

    expect(parsed.nodes).toHaveLength(2);
    expect(parsed.nodes[0].x).toBeUndefined();
  });

  it("parses DAG payload with optional coordinates", () => {
    const parsed = PipelineDagSchema.parse({
      nodes: [
        { id: "n1", label: "L1", state: "PASS", x: 80, y: 30 },
        { id: "n2", label: "L2", state: "ACTIVE", x: 220, y: 120 },
      ],
      edges: [{ from: "n1", to: "n2" }],
    });

    expect(parsed.nodes[1].x).toBe(220);
    expect(parsed.nodes[1].y).toBe(120);
  });
});
