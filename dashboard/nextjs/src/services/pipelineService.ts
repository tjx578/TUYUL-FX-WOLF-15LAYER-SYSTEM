import { PipelineResultSchema } from "@/schema/pipelineResultSchema";
import { apiClient } from "./apiClient";

export async function fetchLatestPipelineResult(
  symbol?: string,
  accountId?: string,
) {
  const response = await apiClient.get("/api/v1/pipeline/latest", {
    params: {
      ...(symbol ? { symbol } : {}),
      ...(accountId ? { account_id: accountId } : {}),
    },
  });

  return PipelineResultSchema.parse(response.data);
}
