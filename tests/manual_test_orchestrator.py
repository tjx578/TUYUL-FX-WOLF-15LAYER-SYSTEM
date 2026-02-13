#!/usr/bin/env python3
"""
Manual integration test for Wolf Sovereign Pipeline.

Tests the complete pipeline with real layer analyzers.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.orchestrators.wolf_sovereign_pipeline import WolfSovereignPipeline


def test_complete_pipeline():
    """Test complete pipeline execution."""
    print("\n" + "=" * 70)
    print("Wolf Sovereign Pipeline - Manual Integration Test")
    print("=" * 70 + "\n")

    # Create pipeline
    print("1. Creating WolfSovereignPipeline...")
    pipeline = WolfSovereignPipeline()
    print("   ✓ Pipeline created\n")

    # Run pipeline for EURUSD
    print("2. Running complete pipeline for EURUSD...")
    try:
        result = pipeline.run(
            symbol="EURUSD",
            system_metrics={"latency_ms": 45, "safe_mode": False},
        )

        print("   ✓ Pipeline completed successfully\n")

        # Display results
        print("3. Pipeline Results:")
        print(f"   Symbol: {result.symbol}")
        print(f"   Latency: {result.latency_ms:.2f}ms")
        print(f"   Errors: {result.errors if result.errors else 'None'}")
        print()

        # L12 Verdict
        verdict = result.l12_verdict
        print("4. L12 Constitutional Verdict:")
        print(f"   Verdict: {verdict.get('verdict', 'N/A')}")
        print(f"   Confidence: {verdict.get('confidence', 'N/A')}")
        print(f"   Wolf Status: {verdict.get('wolf_status', 'N/A')}")
        print(f"   Proceed to L13: {verdict.get('proceed_to_L13', False)}")
        print()

        # Gates
        if "gates" in verdict:
            gates = verdict["gates"]
            passed = gates.get("passed", 0)
            total = gates.get("total", 10)
            print(f"   Gates: {passed}/{total} passed")
            print()

        # Synthesis summary
        if result.synthesis:
            scores = result.synthesis.get("scores", {})
            print("5. Synthesis Summary:")
            print(f"   Wolf 30-Point: {scores.get('wolf_30_point', 'N/A')}")
            print(f"   FTA Score: {scores.get('fta_score', 'N/A'):.3f}")
            print(f"   Exec Score: {scores.get('exec_score', 'N/A')}")
            print()

        # L13/L15 Governance (if executed)
        if result.reflective_pass1:
            print("6. L13 Reflective Pass 1:")
            print(f"   LRCE: {result.reflective_pass1.get('lrce_score', 'N/A'):.3f}")
            print(f"   FRPC: {result.reflective_pass1.get('frpc_score', 'N/A'):.3f}")
            print(f"   αβγ Score: {result.reflective_pass1.get('abg_score', 'N/A'):.3f}")
            print()

        if result.meta:
            print("7. L15 Meta Sovereignty:")
            print(
                f"   Meta Integrity: {result.meta.get('meta_integrity', 'N/A'):.3f}"
            )
            print(f"   Vault Sync: {result.meta.get('vault_sync', 'N/A'):.3f}")
            print(
                f"   Valid Layers: {result.meta.get('valid_layers', 'N/A')}/{result.meta.get('total_layers', 'N/A')}"
            )
            print()

        if result.reflective_pass2:
            print("8. L13 Reflective Pass 2:")
            print(f"   Drift Ratio: {result.reflective_pass2.get('drift_ratio', 'N/A'):.3f}")
            print(f"   αβγ Score: {result.reflective_pass2.get('abg_score', 'N/A'):.3f}")
            print()

        if result.enforcement:
            print("9. Sovereignty Enforcement:")
            print(
                f"   Execution Rights: {result.enforcement.get('execution_rights', 'N/A')}"
            )
            print(
                f"   Lot Multiplier: {result.enforcement.get('lot_multiplier', 'N/A')}"
            )
            print(f"   Reason: {result.enforcement.get('reason', 'N/A')}")
            print()

        print("=" * 70)
        print("✓ Integration test completed successfully!")
        print("=" * 70 + "\n")

        return True

    except Exception as exc:
        print(f"   ✗ Pipeline failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_complete_pipeline()
    sys.exit(0 if success else 1)
