#!/usr/bin/env python3
"""
Manual integration test for Wolf Constitutional Pipeline.

Tests the complete pipeline with real layer analyzers.
Updated to use WolfConstitutionalPipeline (single canonical pipeline).
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import WolfConstitutionalPipeline


def test_complete_pipeline():
    """Test complete pipeline execution."""
    print("\n" + "=" * 70)
    print("Wolf Constitutional Pipeline - Manual Integration Test")
    print("=" * 70 + "\n")

    # Create pipeline
    print("1. Creating WolfConstitutionalPipeline...")
    pipeline = WolfConstitutionalPipeline()
    print("   ✓ Pipeline created\n")

    # Run pipeline for EURUSD
    print("2. Running complete pipeline for EURUSD...")
    try:
        result = pipeline.execute("EURUSD")

        print("   ✓ Pipeline completed successfully\n")

        # Display results
        print("3. Pipeline Results:")
        print(f"   Symbol: EURUSD")
        print(f"   Latency: {result['latency_ms']:.2f}ms")
        print(f"   Errors: {result['errors'] if result['errors'] else 'None'}")
        print()

        # L12 Verdict
        verdict = result["l12_verdict"]
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
        synthesis = result["synthesis"]
        if synthesis:
            scores = synthesis.get("scores", {})
            print("5. Synthesis Summary:")
            print(f"   Wolf 30-Point: {scores.get('wolf_30_point', 'N/A')}")
            print(f"   FTA Score: {scores.get('fta_score', 'N/A'):.3f}")
            print(f"   Exec Score: {scores.get('exec_score', 'N/A')}")
            print()

        # L13 Reflective (if executed)
        if result["reflective"]:
            print("6. L13 Reflective Pass:")
            print(f"   LRCE: {result['reflective'].get('lrce_score', 'N/A'):.3f}")
            print(f"   FRPC: {result['reflective'].get('frpc_score', 'N/A'):.3f}")
            print(f"   αβγ Score: {result['reflective'].get('abg_score', 'N/A'):.3f}")
            print()

        # L14 Sovereignty
        if result["sovereignty"]:
            print("7. L14 Sovereignty Enforcement:")
            print(
                f"   Execution Rights: {result['sovereignty'].get('execution_rights', 'N/A')}"
            )
            print(
                f"   Lot Multiplier: {result['sovereignty'].get('lot_multiplier', 'N/A')}"
            )
            print(f"   Vault Sync: {result['sovereignty'].get('vault_sync', 'N/A'):.3f}")
            print(f"   Meta Integrity: {result['sovereignty'].get('meta_integrity', 'N/A'):.3f}")
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
