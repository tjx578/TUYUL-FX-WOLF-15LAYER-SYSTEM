"""
Fibonacci Levels Calculator
"""

from typing import Dict


class FibonacciEngine:
    @staticmethod
    def retracement(high: float, low: float) -> Dict[str, float]:
        diff = high - low
        return {
            "0.236": high - diff * 0.236,
            "0.382": high - diff * 0.382,
            "0.5": high - diff * 0.5,
            "0.618": high - diff * 0.618,
            "0.786": high - diff * 0.786,
        }

    @staticmethod
    def extension(high: float, low: float) -> Dict[str, float]:
        diff = high - low
        return {
            "1.272": high + diff * 0.272,
            "1.618": high + diff * 0.618,
            "2.0": high + diff,
        }
# Placeholder
