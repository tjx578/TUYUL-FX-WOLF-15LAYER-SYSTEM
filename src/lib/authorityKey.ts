export function buildAuthorityKey(
    action: string,
    accountId?: string,
    tradeId?: string
): string {
    return [action, accountId ?? "-", tradeId ?? "-"].join("::");
}
