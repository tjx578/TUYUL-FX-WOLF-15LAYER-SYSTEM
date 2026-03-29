import { PipelineDagSchema } from "@/schema/pipelineDagSchema";
import type { PipelineDagView } from "@/contracts/pipelineDag";
import { apiClient } from "./apiClient";

export async function fetchPipelineDag(
  symbol?: string,
  accountId?: string
): Promise<PipelineDagView> {
  const { data } = await apiClient.get("/api/v1/pipeline/dag", {
    params: { symbol, account_id: accountId },
  });

  return PipelineDagSchema.parse(data);
}
