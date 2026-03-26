/**
 * Risk domain types.
 *
 * Core data shapes (RiskSnapshot, RiskProfile, DrawdownData, etc.) live in
 * the shared @/types barrel. This file holds domain-local UI types that
 * are specific to the risk feature screens and widgets.
 */

/** DD Multiplier rule row displayed in the risk monitor table. */
export interface DdMultiplierRule {
    range: string;
    mult: string;
    effect: string;
    color: string;
}

/** Static DD multiplier rules for the risk monitor table. */
export const DD_MULTIPLIER_RULES: DdMultiplierRule[] = [
    { range: "< 30%", mult: "1.00x", effect: "Full risk", color: "var(--green)" },
    { range: "30–60%", mult: "0.75x", effect: "Reduced", color: "var(--text-secondary)" },
    { range: "60–80%", mult: "0.50x", effect: "Half size", color: "var(--yellow)" },
    { range: "> 80%", mult: "0.25x", effect: "Emergency", color: "var(--red)" },
];
