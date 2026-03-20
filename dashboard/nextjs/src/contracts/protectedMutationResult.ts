export interface ProtectedMutationResult {
  ok: boolean;
  correlation_id: string;
  message?: string;
}