#!/usr/bin/env python
"""
Demo script showing Wolf 15-Layer Reasoning Engine integration

This demonstrates the engine calling real analyzers and producing output.
"""

from reasoning import Wolf15LayerEngine, Wolf15LayerTemplatePopulator

print("=" * 80)
print("🐺 WOLF 15-LAYER REASONING ENGINE - INTEGRATION DEMO")
print("=" * 80)
print()

# Initialize engine
print("Initializing Wolf15LayerEngine with real analyzers...")
engine = Wolf15LayerEngine()
print(f"✅ Engine initialized with {len(vars(engine))} components")
print()

# Test with pre-computed data (doesn't require LiveContextBus)
print("Testing execute_from_precomputed() mode...")
sample_data = {
    "pair": "EURUSD",
    "timestamp": "2025-02-13 10:30:00 UTC",
    "current_price": 1.0850,
    "technical_bias": "BULLISH",
}

result = engine.execute_from_precomputed(sample_data)
print(f"✅ Pipeline completed with {len(engine.execution_log)} log entries")
print()

# Display results
print("-" * 80)
print("📊 EXECUTION RESULTS")
print("-" * 80)
print(f"Pair:          {result['pair']}")
print(f"Verdict:       {result['verdict']}")
print(f"Confidence:    {result['confidence']}")
print(f"Wolf Status:   {result['wolf_status']}")
print(f"Gates:         {result['gates']['passed']}/{result['gates']['total']}")
print()

print("📈 Scores:")
print(f"  Wolf 30-Point: {result['scores']['wolf_30']}/30")
print(f"  F-Score:       {result['scores']['f_score']}/7")
print(f"  T-Score:       {result['scores']['t_score']}/13")
print(f"  FTA Score:     {result['scores']['fta_score']:.1f}% (int: {result['scores']['fta_score_int']}/4)")
print(f"  Psychology:    {result['scores']['psychology']}/100")
print()

print("💹 Execution Parameters (TP1_ONLY):")
print(f"  Entry:         {result['execution']['entry']}")
print(f"  Stop Loss:     {result['execution']['stop_loss']}")
print(f"  Take Profit 1: {result['execution']['take_profit_1']}")
print(f"  RR Ratio:      1:{result['execution']['rr_ratio']}")
print(f"  Mode:          {result['execution']['execution_mode']}")
print()

print("📝 Execution Log (first 5 entries):")
for i, log_entry in enumerate(result['execution_log'][:5], 1):
    print(f"  {i}. {log_entry}")
print()

# Test template populator
print("-" * 80)
print("🖼️  TEMPLATE POPULATOR TEST")
print("-" * 80)

populator = Wolf15LayerTemplatePopulator(result)
print(populator.get_l12_verdict())

print()
print("=" * 80)
print("✅ INTEGRATION DEMO COMPLETE")
print("=" * 80)
print()
print("Key Features Demonstrated:")
print("  ✅ Engine initialization with real analyzers (L1-L11)")
print("  ✅ Sequential execution with logging")
print("  ✅ Typed context (WolfContext)")
print("  ✅ Output structure validation")
print("  ✅ Template population for display")
print("  ✅ FTA score both as % and 0-4 integer")
print()
print("Next Steps:")
print("  - Run full pipeline with: engine.execute_full_pipeline('EURUSD')")
print("  - Requires LiveContextBus for real market data")
print("  - See REASONING_ENGINE_INTEGRATION.md for details")
