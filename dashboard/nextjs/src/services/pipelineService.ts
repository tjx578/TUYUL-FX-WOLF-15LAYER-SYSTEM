import { PipelineResultSchema } from "@/schema/pipelineResultSchema";
import { apiClient } from "./apiClient";

export class PipelineVerdictUnavailableError extends Error {
  readonly reason = "NO_VERDICT_AVAILABLE" as const;

  constructor(message = "No verdict payload returned by /api/v1/verdict/all.") {
    super(message);
    this.name = "PipelineVerdictUnavailableError";
  }
}

export async function fetchLatestPipelineResult(
  symbol?: string,
  _accountId?: string,
) {
  // Single symbol → /api/v1/l12/{symbol}
  if (symbol) {
    const response = await apiClient.get(`/api/v1/l12/${symbol}`);
    const data = response.data;
    return PipelineResultSchema.parse({
      symbol: data.symbol ?? symbol,
      verdict: data.verdict,
      confidence: data.confidence ?? 0,
      gate_state: data.gate_state,
      governance_state: data.governance_state,
    });
  }

  // No symbol → /api/v1/verdict/all → pick first available
  const response = await apiClient.get("/api/v1/verdict/all");
  const verdicts: Record<string, any> = response.data ?? {};
  const symbols = Object.keys(verdicts);
  if (symbols.length === 0) {
    throw new PipelineVerdictUnavailableError();
  }
  const firstSymbol = symbols[0];
  const data = verdicts[firstSymbol];
  return PipelineResultSchema.parse({
    symbol: data.symbol ?? firstSymbol,
    verdict: data.verdict,
    confidence: data.confidence ?? 0,
    gate_state: data.gate_state,
    governance_state: data.governance_state,
  });
}
