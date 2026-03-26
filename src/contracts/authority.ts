export type AuthorityDecision =
    | "ALLOW"
    | "DENY"
    | "REQUIRE_APPROVAL"
    | "REQUIRE_LOCK_OVERRIDE"
    | "DOWNGRADE_TO_SAFE_NOOP";

export interface AuthoritySurface {
    action: string;
    allowed: boolean;
    reason?: string;
    code?: string;
}
