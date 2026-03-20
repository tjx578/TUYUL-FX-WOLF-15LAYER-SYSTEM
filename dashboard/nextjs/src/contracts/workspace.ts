export type WorkspacePreset = "default" | "risk_focus" | "pipeline_focus";

export interface WorkspaceWidget {
  id: string;
  title: string;
  visible: boolean;
}

export interface WorkspaceLayout {
  preset: WorkspacePreset;
  widgets: WorkspaceWidget[];
}
