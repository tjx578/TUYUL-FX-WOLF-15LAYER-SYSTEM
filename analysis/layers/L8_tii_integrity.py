"""
L8 — TII & Integrity Calculation
"""


class L8TIIIntegrityAnalyzer:
    def analyze(self, layers: dict) -> dict:
        """
        layers: output dict dari L1–L7
        """
        valid_layers = sum(1 for l in layers.values() if l.get("valid"))
        total_layers = len(layers)

        if total_layers == 0:
            return {"valid": False}

        integrity = round(valid_layers / total_layers, 3)
        tii_sym = round(integrity * 0.98, 3)

        return {
            "integrity": integrity,
            "tii_sym": tii_sym,
            "valid": True,
        }
