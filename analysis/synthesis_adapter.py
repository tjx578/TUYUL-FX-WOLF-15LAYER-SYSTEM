def adapt_synthesis(raw: dict) -> dict:
    """
    Read-only adapter.
    Menjamin output synthesis SELALU cocok kontrak L12.
    """

    required = ["pair", "scores", "layers", "execution", "risk", "propfirm", "bias", "system"]

    for k in required:
        if k not in raw:
            raise ValueError(f"SYNTHESIS CONTRACT ERROR: missing {k}")

    return {
        "pair": raw["pair"],
        "scores": raw["scores"],
        "layers": raw["layers"],
        "execution": raw["execution"],
        "risk": raw["risk"],
        "propfirm": raw["propfirm"],
        "bias": raw["bias"],
        "system": raw["system"],
    }
