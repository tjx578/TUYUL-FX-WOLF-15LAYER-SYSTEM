import numpy as np


def auto_tune_risk_multiplier(latency_samples, vr_samples, base_table):
    """
    Simulate risk-multiplier auto-tuning based on regime transitions and latency feed.
    Args:
        latency_samples: List[float] of recent latency measurements (seconds)
        vr_samples: List[float] of recent volatility regime values
        base_table: Dict[str, float] base risk_mult per regime
    Returns:
        Dict[str, float]: Updated risk_mult per regime
    """
    # Example: If latency is high, reduce risk multiplier
    latency = np.median(latency_samples[-100:]) if latency_samples else 0.5
    vr = np.median(vr_samples[-100:]) if vr_samples else 1.0
    tuned = {}
    for regime, base in base_table.items():
        # Example logic: penalize risk if latency > 1.5s or VR > 1.2
        penalty = 1.0
        if latency > 1.5:
            penalty *= 0.8
        if vr > 1.2:
            penalty *= 0.9
        tuned[regime] = round(base * penalty, 3)
    return tuned


# Example usage:
if __name__ == "__main__":
    base_table = {"LOW_VOL": 0.8, "NORMAL_VOL": 1.0, "HIGH_VOL": 1.1}
    latency_samples = [1.0, 1.2, 1.7, 1.8, 1.3]
    vr_samples = [1.0, 1.1, 1.3, 1.2, 1.0]
    print(auto_tune_risk_multiplier(latency_samples, vr_samples, base_table))
