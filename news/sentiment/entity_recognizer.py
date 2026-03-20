"""
Entity recognizer for financial news text.

Extracts central bank names, currency codes, and key financial
institutions from news headlines and summaries using regex patterns.

Zone: analysis/ -- pure read-only analysis, no execution side-effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Central Bank Mappings ────────────────────────────────────────────────────
# Maps central bank identifiers to their canonical name and affected currencies.


@dataclass(frozen=True)
class CentralBankEntity:
    canonical_name: str
    abbreviation: str
    currencies: list[str] = field(default_factory=list)


CENTRAL_BANKS: dict[str, CentralBankEntity] = {
    "fed": CentralBankEntity("Federal Reserve", "FED", ["USD"]),
    "federal reserve": CentralBankEntity("Federal Reserve", "FED", ["USD"]),
    "fomc": CentralBankEntity("Federal Reserve", "FED", ["USD"]),
    "powell": CentralBankEntity("Federal Reserve", "FED", ["USD"]),
    "ecb": CentralBankEntity("European Central Bank", "ECB", ["EUR"]),
    "european central bank": CentralBankEntity("European Central Bank", "ECB", ["EUR"]),
    "lagarde": CentralBankEntity("European Central Bank", "ECB", ["EUR"]),
    "boe": CentralBankEntity("Bank of England", "BOE", ["GBP"]),
    "bank of england": CentralBankEntity("Bank of England", "BOE", ["GBP"]),
    "bailey": CentralBankEntity("Bank of England", "BOE", ["GBP"]),
    "boj": CentralBankEntity("Bank of Japan", "BOJ", ["JPY"]),
    "bank of japan": CentralBankEntity("Bank of Japan", "BOJ", ["JPY"]),
    "ueda": CentralBankEntity("Bank of Japan", "BOJ", ["JPY"]),
    "kuroda": CentralBankEntity("Bank of Japan", "BOJ", ["JPY"]),
    "snb": CentralBankEntity("Swiss National Bank", "SNB", ["CHF"]),
    "swiss national bank": CentralBankEntity("Swiss National Bank", "SNB", ["CHF"]),
    "rba": CentralBankEntity("Reserve Bank of Australia", "RBA", ["AUD"]),
    "reserve bank of australia": CentralBankEntity("Reserve Bank of Australia", "RBA", ["AUD"]),
    "rbnz": CentralBankEntity("Reserve Bank of New Zealand", "RBNZ", ["NZD"]),
    "reserve bank of new zealand": CentralBankEntity("Reserve Bank of New Zealand", "RBNZ", ["NZD"]),
    "boc": CentralBankEntity("Bank of Canada", "BOC", ["CAD"]),
    "bank of canada": CentralBankEntity("Bank of Canada", "BOC", ["CAD"]),
    "macklem": CentralBankEntity("Bank of Canada", "BOC", ["CAD"]),
    "pboc": CentralBankEntity("People's Bank of China", "PBOC", ["CNY"]),
    "people's bank of china": CentralBankEntity("People's Bank of China", "PBOC", ["CNY"]),
}

# ISO 4217 currency codes relevant to forex
_CURRENCY_CODES: set[str] = {
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CHF",
    "AUD",
    "NZD",
    "CAD",
    "CNY",
    "SEK",
    "NOK",
    "DKK",
    "SGD",
    "HKD",
    "MXN",
    "ZAR",
    "TRY",
    "PLN",
    "CZK",
    "HUF",
}

# Key economic indicators (for contextual enrichment)
_INDICATOR_PATTERNS: list[tuple[str, str]] = [
    (r"\bnfp\b|non[\s-]?farm\s+payroll", "NFP"),
    (r"\bcpi\b|consumer\s+price\s+index", "CPI"),
    (r"\bppi\b|producer\s+price\s+index", "PPI"),
    (r"\bgdp\b|gross\s+domestic\s+product", "GDP"),
    (r"\bpmi\b|purchasing\s+managers?\s+index", "PMI"),
    (r"\bunemployment\s+rate\b|\bjobless\s+claims?\b", "EMPLOYMENT"),
    (r"\bretail\s+sales\b", "RETAIL_SALES"),
    (r"\btrade\s+balance\b", "TRADE_BALANCE"),
    (r"\bindustrial\s+production\b", "INDUSTRIAL_PRODUCTION"),
    (r"\bhousing\s+starts?\b|\bbuilding\s+permits?\b", "HOUSING"),
    (r"\binterest\s+rate\s+decision\b|\brate\s+decision\b", "RATE_DECISION"),
    (r"\bmonetary\s+policy\b", "MONETARY_POLICY"),
    (r"\bfiscal\s+policy\b", "FISCAL_POLICY"),
]


def extract_entities(text: str) -> list[str]:
    """
    Extract all recognized financial entities from text.

    Returns a deduplicated list of canonical entity names including:
    - Central bank names (e.g. "FED", "ECB")
    - Currency codes (e.g. "USD", "EUR")
    - Economic indicators (e.g. "NFP", "CPI")
    """
    text_lower = text.lower()
    entities: list[str] = []
    seen: set[str] = set()

    # Central banks — match longer phrases first
    for pattern, bank in sorted(CENTRAL_BANKS.items(), key=lambda x: len(x[0]), reverse=True):
        if pattern in text_lower and bank.abbreviation not in seen:
            entities.append(bank.abbreviation)
            seen.add(bank.abbreviation)
            for ccy in bank.currencies:
                if ccy not in seen:
                    entities.append(ccy)
                    seen.add(ccy)

    # Explicit currency codes in uppercase text
    for code in _CURRENCY_CODES:
        if code not in seen and re.search(rf"\b{code}\b", text):
            entities.append(code)
            seen.add(code)

    # Economic indicators
    for pattern, indicator_name in _INDICATOR_PATTERNS:
        if indicator_name not in seen and re.search(pattern, text_lower):
            entities.append(indicator_name)
            seen.add(indicator_name)

    return entities


def extract_affected_currencies(text: str) -> list[str]:
    """
    Extract only currency codes that should be affected by this news.

    Combines currencies from central bank mentions and explicit currency
    code mentions in the text.
    """
    text_lower = text.lower()
    currencies: set[str] = set()

    for pattern, bank in CENTRAL_BANKS.items():
        if pattern in text_lower:
            currencies.update(bank.currencies)

    for code in _CURRENCY_CODES:
        if re.search(rf"\b{code}\b", text):
            currencies.add(code)

    return sorted(currencies)


def identify_central_bank(text: str) -> CentralBankEntity | None:
    """
    Identify the primary central bank mentioned in the text.

    Returns the first match (longer phrases checked first), or None.
    """
    text_lower = text.lower()

    for pattern, bank in sorted(CENTRAL_BANKS.items(), key=lambda x: len(x[0]), reverse=True):
        if pattern in text_lower:
            return bank
    return None
