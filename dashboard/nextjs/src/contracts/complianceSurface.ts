export type CompliancePage =
  | "dashboard"
  | "trades"
  | "analysis"
  | "risk"
  | "news"
  | "journal"
  | "accounts"
  | "pipeline";

export type ComplianceTone = "info" | "warning" | "error";

export interface ComplianceSurface {
  page: CompliancePage;
  state: string;
  tone: ComplianceTone;
  title: string;
  description: string;
}
