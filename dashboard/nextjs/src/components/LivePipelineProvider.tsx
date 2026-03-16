"use client";

import { useLivePipeline } from "@/hooks/useLivePipeline";

export default function LivePipelineProvider() {
    useLivePipeline();
    return null;
}
