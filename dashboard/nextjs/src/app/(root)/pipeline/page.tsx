"use client";

import PipelinePanel from "@/components/panels/PipelinePanel";
import PipelineDagCanvas from "@/components/panels/PipelineDagCanvas";
import EntryGovernancePanel from "@/components/panels/EntryGovernancePanel";
import { PanelWrapper } from "@/components/primitives/PanelWrapper";

export default function PipelinePage() {
  return (
    <div className="grid gap-4">
      <PanelWrapper title="Pipeline Runtime">
        <PipelinePanel />
      </PanelWrapper>
      <PanelWrapper title="Pipeline DAG Canvas">
        <PipelineDagCanvas />
      </PanelWrapper>
      <PanelWrapper title="Entry Governance">
        <EntryGovernancePanel />
      </PanelWrapper>
    </div>
  );
}
