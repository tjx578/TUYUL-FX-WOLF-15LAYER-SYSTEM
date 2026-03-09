export type DagNodeState = "PASS" | "FAIL" | "SKIP" | "ACTIVE" | "IDLE";

export interface PipelineDagNode {
  id: string;
  label: string;
  state: DagNodeState;
}

export interface PipelineDagEdge {
  from: string;
  to: string;
}

export interface PipelineDagView {
  nodes: PipelineDagNode[];
  edges: PipelineDagEdge[];
}
