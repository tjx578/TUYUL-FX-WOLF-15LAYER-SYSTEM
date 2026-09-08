import type { ReactNode } from "react";
import type { DashboardSnapshot } from "./contracts";

export type RailwayDashboardProps = {
  snapshot: DashboardSnapshot;
  existingEvidencePage?: ReactNode;
  onRefresh?: () => void;
  onLogout?: () => void;
  route?: string;
  routeBase?: string;
  onNavigate?: (route: string) => void;
};

export default function RailwayDashboard(props: RailwayDashboardProps): ReactNode;
