export type CompliancePage =
  | "dashboard"
  | "trades"
  | "risk"
  | "news"
  | "journal"
  | "accounts"
  | "pipeline"
  | "settings";

export type ComplianceTone = "info" | "warning" | "error";

export interface ComplianceSurface {
  page: CompliancePage;
  state: string;
  tone: ComplianceTone;
  title: string;
  description: string;
}
