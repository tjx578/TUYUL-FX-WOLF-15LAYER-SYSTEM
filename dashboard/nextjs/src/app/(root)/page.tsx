import { CommandCenterScreen } from "@/features/command/components/CommandCenterScreen";

// Legacy route - delegates to feature screen (will become redirect after full cutover)
export default function RootHomePage() {
  return <CommandCenterScreen />;
}
