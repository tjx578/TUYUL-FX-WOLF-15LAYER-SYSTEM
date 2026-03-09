export type AuthorityDecision =
  | "ALLOW"
  | "DENY"
  | "REQUIRE_APPROVAL"
  | "REQUIRE_LOCK_OVERRIDE"
  | "DOWNGRADE_TO_SAFE_NOOP";
