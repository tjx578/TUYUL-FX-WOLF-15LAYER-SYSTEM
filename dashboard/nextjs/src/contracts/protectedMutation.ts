export interface ProtectedMutationConfig {
  mutationKey: string;
  accountId?: string;
  tradeId?: string;
  invalidateQueryKeys?: unknown[][];
  successTitle: string;
  successDescription?: string;
}
